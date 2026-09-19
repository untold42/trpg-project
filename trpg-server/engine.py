# -*- coding: utf-8 -*-
"""
engine.py
=========
游戏引擎：回合运行 + 会话状态 + 过程日志。

职责边界（见 README.md §5.4）：
    - GameSession  : 持有 history（纯叙事）与 current.jsonl（过程真相），负责落盘/恢复
    - TurnRunner   : 一次玩家动作的完整回合（LLM 工具循环），产出给前端的
                    统一事件流（叙事指令 + 工具 UI 事件）
    - 状态注入      : 每次调用 LLM 都从 state_manager 现拼「当前状态」，只出现一次

main.py 只负责 bootstrap（建 session/runner）与路由，不再持有 history、不再写工具循环。

关键设计（为什么这么做）：
    - history 只存 user / assistant 正文，工具中间消息不进 history（原先靠
      collapse_tool_messages 事后清理，现在从源头就不落进去）。
    - 状态不进 history，而是每次 build_messages 时现拼、放在 messages 末尾。
      这样上下文里的状态永远唯一且最新，落实「数据先于叙述」。
    - current.jsonl 每轮追加：唯一的「边玩边写」。一次磁盘 append 成本可忽略，
      换来崩溃安全与后续「存档誊写」的原始素材。
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections import deque
from pathlib import Path

from tools.大模型.folder_to_prompt import folder_to_prompt  # noqa: F401  (供 main 使用)
from tools.核心.state_manager import state
from tools.核心.game_clock import clock
from tools.核心 import derived
from tools.核心 import hunger
from tools.核心 import weather_system
from tools.核心.ui_events import UI_EVENTS_KEY, music_event, bg_event, mode_event
from tools.核心 import world_threads
from tools.核心 import macro_timeline
from tools.导演 import director
from tools.小模型 import world_worker
from tools.小模型 import ui_sim
from tools.核心 import map_query
from tools.小模型 import expression_sim
from tools.核心 import audit
from tools.大模型.registry import SAVE_TOOLS, ALL_TOOL_NAMES, SAVE_TOOL_NAMES

# ------------------------------------------------------------
# 路径
# ------------------------------------------------------------
SERVER_DIR = Path(__file__).resolve().parent
SESSIONS_DIR = SERVER_DIR / "sessions"
CURRENT_LOG = SESSIONS_DIR / "current.jsonl"
GAME_DATA_DIR = SERVER_DIR / "游戏数据"
SAVE_TRANSCRIPT = GAME_DATA_DIR / "游戏存档.md"

# 规则文件（主持人/*.md）热更新：按文件夹最新 mtime 缓存，改文件即时生效
_rules_cache: dict = {}


def _rules_text(folder: str) -> str:
    try:
        m = max(p.stat().st_mtime for p in Path(folder).rglob("*") if p.is_file())
    except (OSError, ValueError):
        m = 0
    cached = _rules_cache.get(folder)
    if cached and cached[0] == m:
        return cached[1]
    text = folder_to_prompt(folder)
    _rules_cache[folder] = (m, text)
    return text


# ------------------------------------------------------------
# 上下文素材
# ------------------------------------------------------------
def state_dict() -> dict:
    """现拼的机械状态 dict（排除 足迹 / 时钟 / **属性**；世界线程已按上下文裁剪）。

    世界线程（NPC 推演）来自 `游戏数据/世界线程.json`，按「纳入上下文」裁后注入；
    宏观时间线**不落档**——从只读剧本按当前日期现切窗口（`macro_timeline.view`）。
    """
    clock.sync_state()  # 连续时钟 → 基本信息.时间（仅刻变化时落盘）
    derived.sync()      # 上限对齐属性（体力→生命上限、內力→精力上限）
    hunger.sync()       # 饥饿归一化为 0~100 并回写挡位
    weather_system.ensure_today()   # 天气惰性同步：日期变了就重查（场景：叙事跨日后）
    snapshot = state.snapshot()
    if "世界线程" in snapshot:
        snapshot["世界线程"] = world_threads.threads_view()
    for _skip in ("足迹", "时钟", "属性"):
        snapshot.pop(_skip, None)
    # 导演简报：只在生成成功且有内容时注入（生成中/失败不占上下文）
    _b = snapshot.get("导演简报")
    if isinstance(_b, dict) and not str(_b.get("内容", "")).strip():
        snapshot.pop("导演简报", None)
    # 宏观时间线：只读剧本 + 时间窗（近 N 月已发生 / 未来 N 月预兆），不落档
    snapshot["宏观时间线"] = macro_timeline.view(world_threads.current_date())
    return snapshot


def render_state(snapshot: dict) -> str:
    """把状态 dict 渲染成发给 LLM 的文本块。"""
    if not snapshot:
        return "（暂无状态数据）"
    blocks = []
    for name in sorted(snapshot):
        body = json.dumps(snapshot[name], ensure_ascii=False, indent=2)
        blocks.append(f"===== {name}.json =====\n{body}")
    return "\n\n".join(blocks)


def snapshot_state() -> str:
    """现拼当前机械状态（游戏数据/*.json）为一段文本。不含 游戏存档.md。

    特殊处理：
      - **世界线程**：按「纳入上下文」裁剪人物线程（只裁**注入**，不裁存储）；
      - **宏观时间线**：从只读剧本按当前日期现切窗口（不落档）；
      - **连续时钟**：先把派生时刻写回 `基本信息.时间`（保证 LLM 看到的是最新时间）；
      - **不进 LLM 上下文的文件**（`足迹` / `时钟` / **`属性`**）：从前端 `/state` 仍可读到，
        但**不发给大模型**（足迹白占上下文；时钟只有一个裸秒数，徒增困惑；
        **`属性`体量大且几乎不变——需要时由大模型自行调 `get_ability`**）。
    """
    return render_state(state_dict())


def nearby_places_text(radius_km: float = 0.6, limit: int = 12) -> str:
    """玩家附近 0.6km 内的**实名地点**清单（供「地名必须真实」规则）。

    每轮注入，给主持人真实地名可用；附近没有实名地点时给「用泛称」的兜底提示。
    """
    pos = (state.load("基本信息", {}) or {}).get("位置", {}) or {}
    lon, lat = pos.get("经度"), pos.get("纬度")
    if not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)):
        return ""
    try:
        places = map_query.nearby_places_brief(lon, lat, radius_km=radius_km, limit=limit)
    except Exception:
        return ""
    if not places:
        return "（附近 0.6km 内没有实名的店铺/坊巷——**不要编具体店名**，用「一家客栈」「街口酒肆」这类泛称。）"
    lines = []
    for p in places:
        d = p.get("距玩家（米）")
        dist = f"{d}米" if isinstance(d, int) else ""
        lines.append(f"- {p['name']}（{p['kind']}，{p.get('方位', '')}{dist}）")
    return "\n".join(lines)


def load_previous_story() -> str:
    """读取上一轮游戏的叙事存档（前情提要）。开局时注入一次。"""
    try:
        return SAVE_TRANSCRIPT.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def current_game_time() -> str:
    """当前游戏内时间（**刻级**，日期 + 时辰 + 刻），形如 '1220-01-15 酉时二刻'。"""
    return clock.render()


# 「时间权威」检测：叙述里出现明确的时间推进标记（用于提醒 LLM 补 advance_time）
_TIME_ADVANCE_RE = re.compile(
    r"翌日|次日|第二天|隔日|隔天|隔夜|转天|翌晨|次晨|"
    r"过了一夜|一夜过去|一夜无话|一宿|"
    r"数日|数天|几日|几天|半月|数月|"
    r"(?:[一二两三四五六七八九十百千半\d]+)\s*(?:天|日|个月|月)\s*(?:之?后|过去|已过)|"
    r"赶了[^。，；\n]{0,6}[天日]|走了[^。，；\n]{0,6}[天日]|"
    # 时辰级：只抓**明确表示已流逝**的说法（「过了两个时辰」「两个时辰后」），
    # 避免「约两个时辰的路程」这类纯描述误报。
    r"过了[^。，；\n]{0,4}时辰|"
    r"(?:[一二两三四五六七八九十半几\d]+)\s*个?\s*时辰\s*(?:之?后|过去|已过)"
)


def _time_advanced(events) -> str:
    """若叙述里出现明确的时间推进标记，返回命中片段（否则空串）。"""
    text = "".join(
        str(it.get("content", ""))
        for it in events
        if isinstance(it, dict) and it.get("type") in ("narration", "chat")
    )
    m = _TIME_ADVANCE_RE.search(text)
    return m.group(0) if m else ""


def _to_explore(ui_events) -> bool:
    """本轮是否切到探索模式（`mode:"explore"` UI 事件：探索按钮 / 旧工具）。"""
    for e in ui_events or []:
        if not isinstance(e, dict) or e.get("type") != "ui" or e.get("kind") != "mode":
            continue
        if (e.get("data") or {}).get("mode") == "explore":
            return True
    return False


# ------------------------------------------------------------
# 过程日志的读取与渲染（单一真相源：current.jsonl）
# ------------------------------------------------------------
_IC_PREFIX = "梁峰："
_SAY_PREFIX = "梁峰开口说：「"
_SAY_SUFFIX = "」"
_GM_PREFIX = "玩家的对主持人说的话："

#: 「继续」按钮（mode="continue"）：ke = 推进的刻数（0 = 不推进时间，只看更多信息）
def continue_cue(ke: int = 2) -> str:
    if ke <= 0:
        return (
            "（静观其变：玩家停下细看，**不推进时间**。"
            "请就**当前场景**给出更多可观察的细节——环境、在场人物、可注意之处（声音、气味、异样之物）。"
            "不要推进时间，也不要替玩家做决定。）"
        )
    return (
        f"（静观其变：玩家不做特别动作，让时间流逝约 {ke} 刻（约 {ke * 15} 分钟）。"
        "请推进眼前的场景与 NPC 的行动、让已有线索自然发酵，"
        "到玩家可能想介入的地方即止；不要替玩家做决定。"
        f"时间确有流逝时请调用 advance_time（ke={ke}）推进时间。）"
    )


CONTINUE_CUE = continue_cue(2)  # 默认（兼容）


def observe_cue(place: str) -> str:
    """「观察」按钮：玩家输入（短）。真正的要求走 `OBSERVE_NOTE` 系统提醒。"""
    p = (place or "").strip() or "此处"
    return f"梁峰在「{p}」近旁驻足察看。"


#: 「观察」回合的系统提醒（只注入本轮，不写进 history / 存档）
OBSERVE_NOTE = (
    "本轮是「观察」：只给 1~3 句**简短**的可观察细节（外观、声响、气味、进出的人）；"
    "**不进入、不与 NPC 长谈、不推进时间、不替梁峰决定下一步**。"
)


#: 【场外话（主持人 OOC）】的系统提醒：元对话要用现代白话直答，不得入戏
OOC_NOTE = (
    "本轮是**场外话（玩家 ⇄ 主持人，OOC / 元对话）**，**不是游戏世界里发生的事**。"
    "请**用现代白话、直接**回答玩家的问题（规则 / 写法 / 系统 / 剧情疑问等），简短。"
    "**禁止**：文言 / 话本体 /「某」「在下」这类书中口吻；「你正立在…」这类入戏句；"
    "代替玩家叙述或行动；用书中旁白口吻把回答包成剧情。"
)


def read_turns(log_path) -> list[dict]:
    """读取 current.jsonl（跳过写了一半的坏行）。"""
    turns = []
    try:
        text = Path(log_path).read_text(encoding="utf-8")
    except OSError:
        return turns
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            turns.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return turns


def parse_instructions(raw) -> list:
    """解析 assistant_raw 里的指令数组（容错 JSON，见 parse_instruction_array）。"""
    return parse_instruction_array(raw) or []


def history_lines(turns: list[dict]) -> list[str]:
    """把回合渲染成历史面板的文本行（供 GET /history）。"""
    lines = []
    for turn in turns:
        s = (turn.get("user") or "").strip()
        if turn.get("mode") == "continue":
            lines.append("（静观其变，时间流逝）")
        elif turn.get("mode") == "observe":
            lines.append("（驻足观察）")
        elif turn.get("mode") == "say":
            body = s.removeprefix(_SAY_PREFIX)
            if body.endswith(_SAY_SUFFIX):
                body = body[:-len(_SAY_SUFFIX)]
            lines.append("梁峰说：「" + body + "」")
        elif turn.get("mode") == "gm" or s.startswith(_GM_PREFIX):
            lines.append("场外：" + s.removeprefix(_GM_PREFIX))
        else:
            lines.append(_IC_PREFIX + s.removeprefix(_IC_PREFIX))
        for it in parse_instructions(turn.get("assistant_raw")):
            if not isinstance(it, dict):
                continue
            if it.get("type") == "chat":
                lines.append(f"{it.get('speaker', '?')}：{it.get('content', '')}")
            elif it.get("type") == "narration":
                lines.append(f" 旁白：{it.get('content', '')}")
    return lines


# ------------------------------------------------------------
# 会话
# ------------------------------------------------------------
class GameSession:
    """一局游戏的状态容器。

    - history      : LLM 工作上下文里的纯叙事（user / assistant 正文）
    - current.jsonl  : 过程真相，每轮一行，重启可恢复
    """

    def __init__(self, rules_prompt: str = "", log_path: Path = CURRENT_LOG,
                 rules_dir: str = None):
        self.rules_prompt = rules_prompt
        self.rules_dir = rules_dir  # 若给了目录，则每回合热读（改规则免重启）
        self.log_path = Path(log_path)
        self.history: list[dict] = []
        self.previous_story = load_previous_story()
        self.pending_time_note = ""  # 「时间权威」提醒：下一轮注入，补上 advance_time 后清除
        self.pending_notes: list[str] = []  # 其他系统提醒（下一轮注入一次）
        #: 状态栈（**长度上限 2**）：每轮末 append 本轮结束时的状态。
        #: 下一轮把栈顶（=上一轮的状态）与现场现拼的「当前状态」一起发给 LLM ——
        #: 只维护两份、不累积（栈顶之外的旧状态自动被 deque 挤掉）。
        self.state_stack: deque = deque(maxlen=2)
        self.last_bg = None       # 上次发给前端的背景 (position, time)，用于去重
        self.last_bg_location = None  # 上次换背景时的地点（场景状态机用）
        self.last_music = None    # 上次发给前端的音乐 track
        self._lock = threading.RLock()
        self._restore()
        # 新一局开张：异步生成一次《导演简报》（每局一次；失败保留上一版）
        if not self.history:
            director.refresh_async(self.previous_story)
        # 本局尚未开始且没有快照 → 记录「本局开局状态」（放弃本轮时回滚用）
        if not self.history and not self._snapshot_path().exists():
            self._take_snapshot()

    # ---- 本局开局快照（放弃本轮时回滚）----
    def _snapshot_path(self) -> Path:
        return self.log_path.parent / "run_start_state.json"

    def _take_snapshot(self):
        """把当前玩家状态记为本局开局状态。

        世界线程也纳入快照（它存在 游戏数据/ 下）：首次尚不存在时补一份空白的，
        保证「放弃本轮」也能把世界推演一起回滚。
        """
        with self._lock:
            clock.persist()  # 先把连续时钟冻结落盘，保证快照里的时钟是最新值
            snap = state.snapshot()
            snap.setdefault("世界线程", world_threads.default())
            path = self._snapshot_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(snap, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def _restore_snapshot(self) -> bool:
        """把玩家状态回滚到本局开局。返回是否成功。"""
        try:
            data = json.loads(self._snapshot_path().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        for name, value in data.items():
            state.save(name, value)
        clock.reload()  # 时钟也随快照回滚
        return True

    # ---- 日志 / 恢复 ----
    def _restore(self):
        """从 current.jsonl 重建 history（崩溃/重启后继续同一局）。"""
        if not self.log_path.exists():
            return
        try:
            lines = self.log_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                turn = json.loads(line)
            except json.JSONDecodeError:
                continue  # 跳过写了一半的坏行
            if turn.get("user"):
                self.history.append({"role": "user", "content": turn["user"]})
            if turn.get("assistant_raw"):
                self.history.append(
                    {"role": "assistant", "content": normalized_assistant(turn["assistant_raw"])}
                )

    def append_turn(self, turn: dict):
        """追加一轮到 current.jsonl（原子性由单行写入保证）。"""
        with self._lock:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(turn, ensure_ascii=False) + "\n")

    def reset(self):
        """结束本局：清空 history 与 current.jsonl。玩家状态保留（故事连续）。

        重置后重新读取刚写好的 游戏存档.md 作为下一局的前情提要，
        并记录新本局的开局状态快照。
        """
        with self._lock:
            world_worker.clear(wait=True)  # 先停在途推演，避免旧任务写脏下一局的快照
            self.history = []
            self.pending_time_note = ""
            self.pending_notes = []
            self.state_stack.clear()
            self.last_bg = None
            self.last_bg_location = None
            self.last_music = None
            if self.log_path.exists():
                self.log_path.unlink()
            self.previous_story = load_previous_story()
            director.refresh_async(self.previous_story)   # 新一局：重生成导演简报
            self._take_snapshot()

    def abandon(self) -> bool:
        """放弃本轮：玩家状态**回滚到本局开始**，丢弃本局日志，开始新本局。

        与 reset 的区别：reset 保留现状（存档用），abandon 先回滚快照（放弃用）。
        返回是否成功回滚。
        """
        with self._lock:
            world_worker.clear(wait=True)  # 先停在途推演（必须在回滚之前，否则在途写入会晚于回滚落地）
            restored = self._restore_snapshot()
            self.history = []
            self.pending_time_note = ""
            self.pending_notes = []
            self.state_stack.clear()
            self.last_bg = None
            self.last_bg_location = None
            self.last_music = None
            if self.log_path.exists():
                self.log_path.unlink()
            self.previous_story = load_previous_story()
            director.refresh_async(self.previous_story)   # 新一局：重生成导演简报
            self._take_snapshot()  # 新本局从回滚后的状态开始
            return restored

    # ---- 历史视图（供前端 GET /history）----
    def history_view(self) -> dict:
        """当前本局的历史：面板文本行 + 最后一轮的指令（用于续玩）。"""
        turns = read_turns(self.log_path)
        tail = parse_instructions(turns[-1].get("assistant_raw")) if turns else []
        return {"active": bool(turns), "lines": history_lines(turns), "tail": tail}

    # ---- 上下文组装 ----
    def _rules(self) -> str:
        return _rules_text(self.rules_dir) if self.rules_dir else self.rules_prompt

    def _system_messages(self) -> list[dict]:
        msgs = [{"role": "system", "content": self._rules()}]
        if self.previous_story:
            msgs.append({
                "role": "system",
                "content": "===== 前情提要（上一轮存档）=====\n" + self.previous_story,
            })
        return msgs

    def build_messages(self, tool_msgs: list[dict] | None = None) -> list[dict]:
        """组装本次发往 LLM 的 messages。

        结构：[规则, 前情?, ...history, ...本轮工具消息, 时间提醒?, 上一轮状态?, 当前状态]
        状态放末尾（稳定前缀利于上下文缓存）；**只保留两份**：栈顶（上一轮）+ 现拼当前。
        """
        msgs = self._system_messages() + self.history + list(tool_msgs or [])
        if self.pending_time_note:
            msgs.append({
                "role": "system",
                "content": "===== 时间提醒 =====\n" + self.pending_time_note,
            })
        if self.pending_notes:
            msgs.append({
                "role": "system",
                "content": "===== 系统提醒 =====\n" + "\n".join(self.pending_notes),
            })
        if self.state_stack:
            # 栈顶 = 上一轮的状态；与现拼的「当前状态」一起给出，让模型**自行对比**
            # 时间 / 地点 / 数值的变化（探索时时间在流动、玩家在走动，无需代码计算差值）
            msgs.append({
                "role": "system",
                "content": "===== 上一轮状态（供对比：时间 / 地点 / 数值发生了什么变化）=====\n"
                           + render_state(self.state_stack[-1]),
            })
        msgs.append({
            "role": "system",
            "content": "===== 当前状态 =====\n" + snapshot_state(),
        })
        # 「地名必须真实」——附玩家附近实名地点，供主持人取用真名（禁止生造）
        nearby = nearby_places_text()
        if nearby:
            msgs.append({
                "role": "system",
                "content": "===== 附近实名地点（NPC 提地名只能用真实存在的，禁止生造）=====\n" + nearby,
            })
        return msgs

# ------------------------------------------------------------
# JSON 容错解析（大模型偶发输出非法 JSON，尤其是 content 里未转义的英文双引号）
# ------------------------------------------------------------
def _strip_code_fence(s: str) -> str:
    """去掉 ```json ... ``` 围栏。"""
    s = (s or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else ""
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    return s.strip()


def _escape_inner_quotes(s: str) -> str:
    """把 JSON 字符串值里**未转义的内层双引号**转义。

    模型写对白时常直接写 `"..."`（英文引号），把 JSON 字符串提前截断。
    规则：字符串里的 `"`，只有当它后面（跳空白）是 `, : } ]` 或行尾时，才算字符串结束；
    否则视为内层引号 → 转义为 `\"`。已转义的 `\"` 原样保留。
    """
    out, in_str, i, n = [], False, 0, len(s)
    while i < n:
        ch = s[i]
        if not in_str:
            out.append(ch)
            if ch == '"':
                in_str = True
            i += 1
            continue
        if ch == "\\":                     # 已转义：原样带走
            out.append(ch)
            if i + 1 < n:
                out.append(s[i + 1]); i += 2
            else:
                i += 1
            continue
        if ch == '"':
            j = i + 1
            while j < n and s[j] in " \t\r\n":
                j += 1
            if j >= n or s[j] in ",:}]":   # 后面是分隔符/结尾 → 字符串结束
                out.append(ch); in_str = False
            else:                            # 内层引号 → 转义
                out.append('\\"')
            i += 1
            continue
        out.append(ch); i += 1
    return "".join(out)


def _try_json_array(s: str):
    try:
        data = json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, list) else None


def parse_instruction_array(raw: str):
    """容错解析指令数组，失败返回 None。

    容忍大模型常见的 JSON 毛病：``` 围栏、前后废话、字符串里未转义的英文双引号。
    注意：本函数定义在 `parse_instructions` 之后，但调用时模块已加载完成，可正常引用。
    """
    if not raw:
        return None
    s = _strip_code_fence(raw)
    data = _try_json_array(s)
    if data is not None:
        return data
    # 修复：转义字符串值里未转义的内层双引号
    data = _try_json_array(_escape_inner_quotes(s))
    if data is not None:
        return data
    # 再退一步：截取最外层 [...]（去掉前后废话）再试一次
    a, b = s.find("["), s.rfind("]")
    if a != -1 and b > a:
        seg = s[a:b + 1]
        for cand in (seg, _escape_inner_quotes(seg)):
            data = _try_json_array(cand)
            if data is not None:
                return data
    return None


def normalized_assistant(raw: str) -> str:
    """喂回模型的 assistant 文本：能解析就回写**规范 JSON**。

    避免把模型自己的非法输出（未转义引号等）原样再喂回去，恶性循环。
    日志仍保留原始 `assistant_raw` 便于排查。
    """
    ev = parse_instruction_array(raw)
    if isinstance(ev, list):
        try:
            return json.dumps(ev, ensure_ascii=False)
        except (TypeError, ValueError):
            return raw
    return raw


# ------------------------------------------------------------
# 回合运行
# ------------------------------------------------------------
class TurnRunner:
    """执行一次玩家动作：LLM → 工具循环 → 最终指令数组。"""

    #: 格式修正提示（最终回复不是合法 JSON 时追加一次）
    FORMAT_CORRECTION = (
        "后端发现你的最终回复格式有误，请严格按照系统规定输出合法JSON数组，"
        "不要输出任何额外内容。"
        "⚠️ 最常见的原因：`content` 里直接写了英文双引号 `\"`（把 JSON 字符串提前截断了）。"
        "对白/引语一律用中文引号「」，`content` 里**不得出现英文双引号**（除非写成 `\\\"`）。"
    )

    #: 时间权威提醒（叙述推进了时间却未调用 advance_time / update_time）
    _TIME_NOTE = (
        "上一轮叙述里出现了时间流逝（「{hit}」），但你**没有调用 `advance_time`**。"
        "世界日期未推进 —— 世界推演不会触发，天气 / 饥饿 / 精力也不会更新。"
        "请在本轮先用 `advance_time` 把时间补到正确值"
        "（短时间用 `ke` 推进几刻，较久用 `shichen` 推进时辰；12 时辰＝1 天），再继续叙述。"
    )

    #: 「台词 / 场外」回合允许的最大时间推进（刻）。说话不该让时间跳时辰、过夜。
    SAY_MAX_KE = 2

    #: 台词回合试图推进时间时的驳回语（回给 LLM）——规则 12 的机械兼底
    _SAY_TIME_BLOCK = (
        "本轮是玩家的**台词 / 场外话**，不是行动，**不得据此替玩家推进时间**。"
        "已驳回本次 `advance_time`。请只让 NPC 回应；若确需时间流逝，等玩家另行发出行动。"
        "（确有小额流逝才可用 `ke`，不超过 {max_ke} 刻。）"
    )

    #: 台词 / 场外 / 观察回合**禁止改动玩家状态的工具**（规则 9：台词≠行动）。
    #: `start_battle` 不在此列；`update_time`/`sleep` 单独处理。
    _SAY_MUTATE_TOOLS = {
        "modify_money", "modify_item", "add_item", "remove_item",
        "modify_hunger", "modify_hp", "modify_tp", "modify_health",
        "update_location", "update_weather",
    }

    #: 台词 / 场外回合试图改动玩家状态时的驳回语（回给 LLM）
    _SAY_ACTION_BLOCK = (
        "本轮是玩家的**台词 / 场外话**，不是行动，**不得据此改动任何玩家数值 / 状态**"
        "（金钱 / 物品 / 生命 / 精力 / 饥饿 / 位置）。已驳回本次 `{tool}`。"
        "请只让 NPC 回应；玩家若确实要做这件事，等他另行发出**行动**。"
    )

    def __init__(self, session: GameSession, send_messages, tools_map: dict):
        self.session = session
        self.send_messages = send_messages
        self.tools_map = tools_map
        #: 本轮允许调用的工具名（None = 不校验）。**按轮设置**：
        #:   游戏回合 = ALL_TOOL_NAMES；存档回合 = SAVE_TOOL_NAMES。
        #:   存档专用工具既不会下发给游戏中的模型，也无法被幻觉调用。
        self._allowed: set[str] | None = None
        self._lock = threading.RLock()  # 串行化回合（**可重入**：run_save 会嵌套调 _run_save）

    def run(self, user_input: str, mode: str = "action", from_explore: bool = False,
            force_explore: bool = False) -> list[dict]:
        """跑完一个回合，返回统一事件流。

        mode: "action"（角色行动）| "gm"（玩家对主持人的场外话）。
        from_explore: 本轮是**玩家从探索模式发起的输入**（带坐标）——
                      进入叙事时必须重新选一次背景/音乐（见 #5）。
        force_explore: 玩家点了「探索」按钮（确定性元操作）——无论 GM 调没调
                       `resume_exploration`，都保证发一份 `mode:explore`。
        形状：[...工具 UI 事件, ...LLM 叙事指令]
        每条为 {"type": "ui"|"chat"|"narration", ...}
        """
        with self._lock:
            # LLM 请求窗口：暂停连续时钟（生成/工具耗时不计入游戏时间），返回后恢复
            clock.pause("turn")
            prev, self._allowed = self._allowed, ALL_TOOL_NAMES
            try:
                return self._run(user_input, mode, from_explore, force_explore)
            finally:
                self._allowed = prev
                clock.resume("turn")

    # ---- 内部 ----
    def _run(self, user_input: str, mode: str = "action", from_explore: bool = False,
             force_explore: bool = False) -> list[dict]:
        session = self.session
        session.history.append({"role": "user", "content": user_input})

        tool_msgs: list[dict] = []
        tool_records: list[dict] = []
        ui_events: list[dict] = []

        result = self.send_messages(session.build_messages(tool_msgs))
        _rounds = 0
        while result.tool_calls and _rounds < 12:      # 轮数上限，防模型无限调工具
            _rounds += 1
            # 1) 保存 LLM 的 tool_calls 消息
            tool_msgs.append({
                "role": "assistant",
                "content": result.content,
                "tool_calls": [tc.model_dump() for tc in result.tool_calls],
            })
            # 2) 执行工具
            for tc in result.tool_calls:
                name = tc.function.name
                try:
                    arguments = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    arguments = {}
                tool_result = self._say_time_guard(mode, name, arguments)
                if tool_result is None:
                    tool_result = self._call_tool(name, arguments)
                # 2b) 取出工具产生的 UI 事件，并从给 LLM 的结果中剥离
                if isinstance(tool_result, dict) and UI_EVENTS_KEY in tool_result:
                    ui_events.extend(tool_result.get(UI_EVENTS_KEY) or [])
                    llm_result = {
                        k: v for k, v in tool_result.items() if k != UI_EVENTS_KEY
                    }
                else:
                    llm_result = tool_result
                # 3) 保存工具结果
                tool_msgs.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(llm_result, ensure_ascii=False),
                })
                tool_records.append({
                    "name": name,
                    "arguments": arguments,
                    "result": llm_result,
                })
            # 4) 工具执行完，再次请求（build_messages 会重拼最新状态）
            result = self.send_messages(session.build_messages(tool_msgs))

        # 5) 解析最终 JSON（必要时请求一次格式修正）
        raw, events = self._finalize(result, tool_msgs)
        # 5a) 人物表情（小模型）：给 chat 补 expression（唯一影响返回事件流，不改 raw）
        expression_sim.fill(events)
        # 5b) 时间权威：叙述推进了时间却没调 update_time → 记提醒，下一轮注入
        self._check_time_authority(events, tool_records)
        # 5c) UI 事件（小模型）：背景 / 音乐
        #     探索→叙事（from_explore）时 **强制重选**（绕过去重），保证一切入叙事就有 bg+音乐
        scene_ui = self._scene_ui_events(events, force=from_explore)
        # 「探索」按钮是**确定性元操作**：GM 忘了调 resume_exploration 也照样切回地图
        if force_explore and not _to_explore(ui_events):
            ui_events = [*ui_events, mode_event("explore")]
        # 叙事 → 探索（resume_exploration）：换一首**通用**背景乐，
        # 别把青楼/酒楼等场所专属曲带到大地图上（小模型从「通用曲」里挑）
        if ui_sim.ENABLED and _to_explore(ui_events):
            try:
                track = ui_sim.explore_track(self.session.last_music)
            except Exception:
                track = ui_sim.DEFAULT_TRACK
            if track and track != self.session.last_music:
                self.session.last_music = track
                scene_ui = [*scene_ui, music_event(track)]

        session.history.append({"role": "assistant", "content": normalized_assistant(raw)})
        session.append_turn({
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "time": current_game_time(),
            "mode": mode,
            "user": user_input,
            "assistant_raw": raw,
            "tool_calls": tool_records,
            "ui_events": ui_events,
            "scene_ui": scene_ui,
        })
        # 世界推演：检测跨天并入队（异步，不阻塞玩家）
        world_worker.on_turn_end()
        session.pending_notes = []  # 系统提醒只注入一次
        # 状态栈入栈本轮结束时的状态（长度上限 2，旧的自然被挤掉）
        session.state_stack.append(state_dict())
        # 统一事件流：UI 事件（小模型 + 工具）在前，LLM 的叙事指令在后
        return scene_ui + ui_events + events

    # ---- 存档蒸馏专用回合 ----
    def run_save(self, transcript: str, rules: str, hints: str = "") -> dict:
        """把本局记录蒸馏进长期记忆。

        与普通回合不同：**不写 history、不写 current.jsonl**（这不是叙事回合）。
        注入《存档流程》规则 + 本局记录，跑工具循环（LLM 调数据库工具）。
        `hints`：代码统计的附加任务（本局进过的建筑 / 两局都出现的无名人）。
        返回 {"content": 最终文本, "tool_calls": [...]}
        """
        with self._lock:
            # 存档蒸馏也是 LLM 请求：期间冻结时钟
            clock.pause("save")
            prev, self._allowed = self._allowed, SAVE_TOOL_NAMES
            try:
                return self._run_save(transcript, rules, hints)
            finally:
                self._allowed = prev
                clock.resume("save")

    def _run_save(self, transcript: str, rules: str, hints: str = "") -> dict:
        with self._lock:
            base = [{"role": "system", "content": rules}]
            if hints:
                base.append({"role": "system", "content": hints})
            base.append({"role": "user", "content":
                "《本局完整记录》\n\n" + transcript +
                "\n\n请按规则将其蒸馏进长期记忆，只调用数据库工具，不要输出叙事。"})
            tool_msgs: list[dict] = []
            tool_records: list[dict] = []
            state_msg = {"role": "system", "content": "===== 当前状态 =====\n" + snapshot_state()}

            result = self._send_save(base + [state_msg], round_no=1)
            _rounds = 0
            while result.tool_calls and _rounds < 12:   # 轮数上限，防蒸馏回合无限调工具
                _rounds += 1
                tool_msgs.append({
                    "role": "assistant",
                    "content": result.content,
                    "tool_calls": [tc.model_dump() for tc in result.tool_calls],
                })
                for tc in result.tool_calls:
                    name = tc.function.name
                    try:
                        arguments = json.loads(tc.function.arguments)
                    except (json.JSONDecodeError, TypeError):
                        arguments = {}
                    audit.log(f"调用工具 {name} 参数 {arguments}")
                    _tool_t0 = time.time()
                    tool_result = self._call_tool(name, arguments)
                    audit.log(f"  工具 {name} 返回，{time.time() - _tool_t0:.1f}s")
                    tool_msgs.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(tool_result, ensure_ascii=False),
                    })
                    tool_records.append({"name": name, "arguments": arguments,
                                         "result": tool_result})
                result = self._send_save(base + tool_msgs + [state_msg], round_no=_rounds + 1)

            audit.log(f"蒸馏完成：{_rounds} 轮工具循环，共 {len(tool_records)} 次工具调用")
            return {"content": result.content or "", "tool_calls": tool_records}

    def _say_time_guard(self, mode: str, name: str, arguments: dict):
        """台词 / 场外 / 观察回合的**行动兼底**（机械执行规则 9 / 12）。

        `mode` 为 `say` / `gm` / `observe` 时：
          - `sleep` 一律驳回；
          - 改玩家状态的工具（金钱/物品/生命/精力/饥饿/位置/天气）一律驳回；
          - `advance_time` 只允许 ≤ `SAY_MAX_KE` 刻（且必须为正），超过/非法驳回；
          - `update_time`（直接设置日期/时辰/刻）一律驳回。

        放开：`start_battle`、各种只读工具。
        正常（无需拦截）返回 `None`。
        """
        if mode not in ("say", "gm", "observe"):
            return None
        if name == "sleep":
            print(f"[say] 驳回{mode}回合的 sleep：{arguments}")
            return {"success": False, "error": self._SAY_TIME_BLOCK.format(max_ke=self.SAY_MAX_KE)}
        if name in self._SAY_MUTATE_TOOLS:
            print(f"[say] 驳回{mode}回合的状态改动：{name} {arguments}")
            return {"success": False, "error": self._SAY_ACTION_BLOCK.format(tool=name)}
        if name == "update_time":
            print(f"[say] 驳回{mode}回合的时间设置：{arguments}")
            return {"success": False, "error": self._SAY_TIME_BLOCK.format(max_ke=self.SAY_MAX_KE)}
        if name != "advance_time":
            return None
        adv_sh = arguments.get("shichen") or 0
        adv_ke = arguments.get("ke") or 0
        jump = adv_sh * 8 + adv_ke > self.SAY_MAX_KE or adv_sh * 8 + adv_ke <= 0
        if not jump:
            return None
        print(f"[say] 驳回{mode}回合的时间推进：{arguments}")
        return {"success": False, "error": self._SAY_TIME_BLOCK.format(max_ke=self.SAY_MAX_KE)}

    def _send_save(self, messages, round_no: int = 1):
        """存档蒸馏回合：带上存档专用工具（含 `update_character_archive`）。"""
        n_chars = sum(len(str(m.get("content") or "")) for m in messages)
        t0 = time.time()
        try:
            r = self.send_messages(messages, tools=SAVE_TOOLS)
            names = [tc.function.name for tc in (r.tool_calls or [])]
            audit.log(f"第 {round_no} 轮 LLM {time.time() - t0:.1f}s，prompt {n_chars} 字，工具 {names}")
            return r
        except Exception as e:
            audit.log(f"第 {round_no} 轮 LLM 失败（{time.time() - t0:.1f}s）：{type(e).__name__}: {e}")
            raise

    def _call_tool(self, name: str, arguments: dict):
        # 按轮校验：本轮未下发的工具（如游戏回合里的存档专用工具）一律拒绝
        if self._allowed is not None and name not in self._allowed:
            return {"success": False,
                    "error": f"本轮未下发该工具，已拒绝调用: {name}"}
        tool = self.tools_map.get(name)
        if tool is None:
            return {"success": False, "error": f"未知工具: {name}"}
        try:
            return tool(**arguments)
        except Exception as e:  # 工具异常不应打断整局
            return {"success": False, "error": str(e)}

    def _check_time_authority(self, events, tool_records):
        """时间权威：叙述推进了时间，却未调用 advance_time / update_time → 记提醒，下一轮注入。"""
        called = any(tc.get("name") in ("advance_time", "update_time") for tc in tool_records)
        hit = _time_advanced(events)
        if called:
            self.session.pending_time_note = ""
        elif hit:
            if not self.session.pending_time_note:
                print(f"[time] 叙述含时间流逝「{hit}」但未调用 advance_time")
            self.session.pending_time_note = self._TIME_NOTE.format(hit=hit)

    def _scene_ui_events(self, events, force: bool = False) -> list[dict]:
        """小模型判断本幕背景 / 音乐。

        - 传入当前地点 + 当前背景/音乐，供小模型判断；
        - **换曲规则**：背景变化 **或** 当前曲已不适用于本地点/在场时，才允许换曲；
          当前曲不再适用且模型没给新曲 → 发「停乐」。
        - **force=True**（探索→叙事）：绕过去重，至少发一份 bg+音乐（模型没给就兵底）。
        """
        if not ui_sim.ENABLED:
            return []
        text = "".join(
            str(it.get("content", ""))
            for it in events
            if isinstance(it, dict) and it.get("type") in ("narration", "chat")
        )
        if not text.strip():
            return []
        # 场景状态机只用「旁白」判断（NPC 台词里的“我出门了”不算玩家移动）
        narration_text = "".join(
            str(it.get("content", ""))
            for it in events
            if isinstance(it, dict) and it.get("type") == "narration"
        )
        loc = world_threads.current_location()
        # D. 只有「强制 / 首次 / 地点变化 / 叙事出现进出门·移动」才允许换背景；否则保持当前
        loc_changed = bool(loc) and loc != self.session.last_bg_location
        allow_bg = (
            force
            or self.session.last_bg is None
            or loc_changed
            or ui_sim.scene_switch_signal(narration_text)
        )
        prev_scene = (self.session.last_bg or (None, None))[0]
        # 本轮登场人物（chat 说话者）——专属曲绑定据此判定，非仅提及
        present = {
            str(it.get("speaker")).strip()
            for it in events
            if isinstance(it, dict) and it.get("type") == "chat" and it.get("speaker")
        }
        try:
            produced = ui_sim.generate(
                text,
                location=loc,
                current_scene=prev_scene,
                current_music=self.session.last_music,
                present=present,
            )
        except Exception:
            produced = []

        bg_ev = next((e for e in produced if e.get("kind") == "bg"), None)
        music_ev = next((e for e in produced if e.get("kind") == "music"), None)

        out = []
        scene_changed = False
        if bg_ev:
            data = bg_ev.get("data") or {}
            key = (data.get("position"), data.get("time"))
            # allow_bg=False 时不接受新背景（保持当前）；force 时连相同背景也重发
            if force or (key != self.session.last_bg and allow_bg):
                self.session.last_bg = key
                self.session.last_bg_location = loc
                scene_changed = True
                out.append(bg_ev)
        elif force:
            # 模型没给背景：用当前地点的第一个候选场景兵底（务必发一份）
            fb = self._fallback_bg_event(loc)
            if fb:
                d = fb.get("data") or {}
                self.session.last_bg = (d.get("position"), d.get("time"))
                self.session.last_bg_location = loc
                scene_changed = True
                out.append(fb)

        # 当前曲是否仍适用于本地点 / 在场
        try:
            allowed = set(ui_sim.narrative_tracks(loc, present))
        except Exception:
            allowed = set()
        last = self.session.last_music
        music_invalid = bool(last) and last not in allowed

        if music_ev:
            track = (music_ev.get("data") or {}).get("track")
            if force or scene_changed or music_invalid:
                if force or track != last or music_invalid:
                    self.session.last_music = track
                    out.append(music_ev)
        elif force:
            self.session.last_music = ui_sim.DEFAULT_TRACK
            out.append(music_event(ui_sim.DEFAULT_TRACK))
        elif music_invalid:
            # 当前曲已不适用，模型也没给新曲 → 停乐
            self.session.last_music = ""
            out.append(music_event(ui_sim.NONE))
        return out

    def _fallback_bg_event(self, loc: str):
        """强选背景时的兵底：当前地点允许的第一个场景 + 当前时辰。"""
        try:
            cands = ui_sim.scene_candidates(loc)
        except Exception:
            cands = []
        if not cands:
            return None
        try:
            t = str(((state.load("基本信息", {}) or {}).get("时间", {}) or {}).get("时辰", ""))
        except Exception:
            t = ""
        return bg_event(cands[0], t)

    def _finalize(self, result, tool_msgs: list[dict]):
        """返回 (最终 assistant 原文, 解析出的指令数组)。"""
        raw = result.content or ""
        events = self._parse(raw)
        if events is not None:
            return raw, events

        # 格式错误：带修正提示再请求一次（修正消息不写入 history）
        correction_msgs = tool_msgs + [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": self.FORMAT_CORRECTION},
        ]
        retry = self.send_messages(self.session.build_messages(correction_msgs))
        retry_raw = retry.content or ""
        retry_events = self._parse(retry_raw)
        if retry_events is not None:
            return retry_raw, retry_events

        # 两次都失败：不让整局崩，返回一条旁白占位
        return raw, [{
            "type": "narration",
            "content": "（系统：主持人回复格式异常，请再行动一次。）",
        }]

    @staticmethod
    def _parse(raw: str):
        """尝试解析指令数组，失败返回 None（容错见 parse_instruction_array）。"""
        return parse_instruction_array(raw)
