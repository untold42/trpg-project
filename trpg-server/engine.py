# -*- coding: utf-8 -*-
"""
engine.py
=========
游戏引擎：回合运行 + 会话状态 + 过程日志。

职责边界（见 ARCHITECTURE.md 第五节）：
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
from pathlib import Path

from tools.folder_to_prompt import folder_to_prompt  # noqa: F401  (供 main 使用)
from tools.state_manager import state
from tools.time_weather import KE_CN
from tools.ui_events import UI_EVENTS_KEY, music_event
from tools import world_state
from tools import world_worker
from tools import ui_sim
from tools.registry import SAVE_TOOLS

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
def snapshot_state() -> str:
    """现拼当前机械状态（游戏数据/*.json）为一段文本。不含 游戏存档.md。

    特殊处理：
      - **世界状态**：按「纳入上下文」裁剪人物线程（只裁**注入**，不裁存储）；
      - **不进 LLM 上下文的文件**（`足迹`）：从前端 `/state` 仍可读到，
        但**不发给大模型**，避免探索足迹白占上下文。
    """
    snapshot = state.snapshot()
    if not snapshot:
        return "（暂无状态数据）"
    if "世界状态" in snapshot:
        snapshot["世界状态"] = world_state.context_view()
    for _skip in ("足迹",):
        snapshot.pop(_skip, None)
    blocks = []
    for name in sorted(snapshot):
        body = json.dumps(snapshot[name], ensure_ascii=False, indent=2)
        blocks.append(f"===== {name}.json =====\n{body}")
    return "\n\n".join(blocks)


def load_previous_story() -> str:
    """读取上一轮游戏的叙事存档（前情提要）。开局时注入一次。"""
    try:
        return SAVE_TRANSCRIPT.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def current_game_time() -> str:
    """当前游戏内时间（日期 + 时辰 + 刻），形如 '1220-01-15 酉时二刻'。"""
    t = (state.load("基本信息", {}) or {}).get("时间", {}) or {}
    ke = t.get("刻", 0)
    ke_txt = ""
    if isinstance(ke, int) and ke > 0:
        ke_txt = KE_CN.get(ke, str(ke)) + "刻"
    return f"{t.get('日期', '')} {t.get('时辰', '')}{ke_txt}".strip()


# 「时间权威」检测：叙述里出现明确的时间推进标记（用于提醒 LLM 补 update_time）
_TIME_ADVANCE_RE = re.compile(
    r"翌日|次日|第二天|隔日|隔天|隔夜|转天|翌晨|次晨|"
    r"过了一夜|一夜过去|一夜无话|一宿|"
    r"数日|数天|几日|几天|半月|数月|"
    r"(?:[一二两三四五六七八九十百千半\d]+)\s*(?:天|日|个月|月)\s*(?:之?后|过去|已过)|"
    r"赶了[^。，；\n]{0,6}[天日]|走了[^。，；\n]{0,6}[天日]"
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
        f"时间确有流逝时请调用 update_time（advance_ke={ke}）推进时间。）"
    )


CONTINUE_CUE = continue_cue(2)  # 默认（兼容）


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
    """解析 assistant_raw 里的指令数组。"""
    try:
        data = json.loads(raw or "[]")
    except (json.JSONDecodeError, TypeError):
        return []
    return data if isinstance(data, list) else []


def history_lines(turns: list[dict]) -> list[str]:
    """把回合渲染成历史面板的文本行（供 GET /history）。"""
    lines = []
    for turn in turns:
        s = (turn.get("user") or "").strip()
        if turn.get("mode") == "continue":
            lines.append("（静观其变，时间流逝）")
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
        self.pending_time_note = ""  # 「时间权威」提醒：下一轮注入，补上 update_time 后清除
        self.pending_notes: list[str] = []  # 其他系统提醒（下一轮注入一次）
        self.last_bg = None       # 上次发给前端的背景 (position, time)，用于去重
        self.last_music = None    # 上次发给前端的音乐 track
        self._lock = threading.RLock()
        self._restore()
        # 本局尚未开始且没有快照 → 记录「本局开局状态」（放弃本轮时回滚用）
        if not self.history and not self._snapshot_path().exists():
            self._take_snapshot()

    # ---- 本局开局快照（放弃本轮时回滚）----
    def _snapshot_path(self) -> Path:
        return self.log_path.parent / "run_start_state.json"

    def _take_snapshot(self):
        """把当前玩家状态记为本局开局状态。

        世界状态也纳入快照（它存在 游戏数据/ 下）：首次尚不存在时补一份空白的，
        保证「放弃本轮」也能把世界推演一起回滚。
        """
        with self._lock:
            snap = state.snapshot()
            snap.setdefault("世界状态", world_state.default())
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
                    {"role": "assistant", "content": turn["assistant_raw"]}
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
            self.last_bg = None
            self.last_music = None
            if self.log_path.exists():
                self.log_path.unlink()
            self.previous_story = load_previous_story()
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
            self.last_bg = None
            self.last_music = None
            if self.log_path.exists():
                self.log_path.unlink()
            self.previous_story = load_previous_story()
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

        结构：[规则, 前情?, ...history, ...本轮工具消息, 时间提醒?, 当前状态]
        状态放末尾（稳定前缀利于上下文缓存），且每次现拼、只出现一份。
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
        msgs.append({
            "role": "system",
            "content": "===== 当前状态 =====\n" + snapshot_state(),
        })
        return msgs


# ------------------------------------------------------------
# 回合运行
# ------------------------------------------------------------
class TurnRunner:
    """执行一次玩家动作：LLM → 工具循环 → 最终指令数组。"""

    #: 格式修正提示（最终回复不是合法 JSON 时追加一次）
    FORMAT_CORRECTION = (
        "后端发现你的最终回复格式有误，请严格按照系统规定输出合法JSON数组，"
        "不要输出任何额外内容。"
    )

    #: 时间权威提醒（叙述推进了时间却未调用 update_time）
    _TIME_NOTE = (
        "上一轮叙述里出现了时间流逝（「{hit}」），但你**没有调用 `update_time`**。"
        "世界日期未推进 —— 世界推演不会触发，天气 / 饥饿 / 精力也不会更新。"
        "请在本轮先用 `update_time` 把时间补到正确值"
        "（短时间用 `advance_ke` 推进几刻，较久用 `advance_shichen` 推进时辰；12 时辰＝1 天），再继续叙述。"
    )

    #: 「台词 / 场外」回合允许的最大时间推进（刻）。说话不该让时间跳时辰、过夜。
    SAY_MAX_KE = 2

    #: 台词回合试图推进时间时的驳回语（回给 LLM）——规则 12 的机械兼底
    _SAY_TIME_BLOCK = (
        "本轮是玩家的**台词 / 场外话**，不是行动，**不得据此替玩家推进时间**。"
        "已驳回本次 `update_time`。请只让 NPC 回应；若确需时间流逝，等玩家另行发出行动。"
        "（确有小额流逝才可用 `advance_ke`，不超过 {max_ke} 刻。）"
    )

    def __init__(self, session: GameSession, send_messages, tools_map: dict):
        self.session = session
        self.send_messages = send_messages
        self.tools_map = tools_map
        self._lock = threading.Lock()  # 串行化回合，避免并发请求交错

    def run(self, user_input: str, mode: str = "action") -> list[dict]:
        """跑完一个回合，返回统一事件流。

        mode: "action"（角色行动）| "gm"（玩家对主持人的场外话）。
        形状：[...工具 UI 事件, ...LLM 叙事指令]
        每条为 {"type": "ui"|"chat"|"narration", ...}
        """
        with self._lock:
            return self._run(user_input, mode)

    # ---- 内部 ----
    def _run(self, user_input: str, mode: str = "action") -> list[dict]:
        session = self.session
        session.history.append({"role": "user", "content": user_input})

        tool_msgs: list[dict] = []
        tool_records: list[dict] = []
        ui_events: list[dict] = []

        result = self.send_messages(session.build_messages(tool_msgs))
        while result.tool_calls:
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
        # 5b) 时间权威：叙述推进了时间却没调 update_time → 记提醒，下一轮注入
        self._check_time_authority(events, tool_records)
        # 5c) UI 事件（小模型）：背景 / 音乐
        scene_ui = self._scene_ui_events(events)

        session.history.append({"role": "assistant", "content": raw})
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
        # 统一事件流：UI 事件（小模型 + 工具）在前，LLM 的叙事指令在后
        return scene_ui + ui_events + events

    # ---- 存档蒸馏专用回合 ----
    def run_save(self, transcript: str, rules: str) -> dict:
        """把本局记录蒸馏进长期记忆。

        与普通回合不同：**不写 history、不写 current.jsonl**（这不是叙事回合）。
        注入《存档流程》规则 + 本局记录，跑工具循环（LLM 调数据库工具）。
        返回 {"content": 最终文本, "tool_calls": [...]}
        """
        with self._lock:
            base = [
                {"role": "system", "content": rules},
                {"role": "user", "content":
                    "《本局完整记录》\n\n" + transcript +
                    "\n\n请按规则将其蒸馏进长期记忆，只调用数据库工具，不要输出叙事。"},
            ]
            tool_msgs: list[dict] = []
            tool_records: list[dict] = []
            state_msg = {"role": "system", "content": "===== 当前状态 =====\n" + snapshot_state()}

            result = self._send_save(base + [state_msg])
            while result.tool_calls:
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
                    tool_result = self._call_tool(name, arguments)
                    tool_msgs.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(tool_result, ensure_ascii=False),
                    })
                    tool_records.append({"name": name, "arguments": arguments,
                                         "result": tool_result})
                result = self._send_save(base + tool_msgs + [state_msg])

            return {"content": result.content or "", "tool_calls": tool_records}

    def _say_time_guard(self, mode: str, name: str, arguments: dict):
        """台词 / 场外回合的时间护栏（机械执行规则 12）。

        `mode` 为 `say`（对 NPC 的台词）或 `gm`（场外话）时，只允许 ≤ `SAY_MAX_KE` 刻的
        `advance_ke`；任何「设置日期 / 时辰 / 刻」或更大的推进都驳回（返回错误结果）。
        正常（无需拦截）返回 `None`。
        """
        if mode not in ("say", "gm") or name != "update_time":
            return None
        adv_sh = arguments.get("advance_shichen") or 0
        adv_ke = arguments.get("advance_ke") or 0
        jump = (
            arguments.get("date") is not None
            or arguments.get("shichen") is not None
            or arguments.get("ke") is not None
            or adv_sh * 8 + adv_ke > self.SAY_MAX_KE
        )
        if not jump:
            return None
        print(f"[say] 驳回{mode}回合的时间推进：{arguments}")
        return {"success": False, "error": self._SAY_TIME_BLOCK.format(max_ke=self.SAY_MAX_KE)}

    def _send_save(self, messages):
        """存档蒸馏回合：带上存档专用工具（含 `update_character_archive`）。"""
        try:
            return self.send_messages(messages, tools=SAVE_TOOLS)
        except TypeError:  # 兼容不接受 tools 参数的 send_messages
            return self.send_messages(messages)

    def _call_tool(self, name: str, arguments: dict):
        tool = self.tools_map.get(name)
        if tool is None:
            return {"success": False, "error": f"未知工具: {name}"}
        try:
            return tool(**arguments)
        except Exception as e:  # 工具异常不应打断整局
            return {"success": False, "error": str(e)}

    def _check_time_authority(self, events, tool_records):
        """时间权威：叙述推进了时间，却未调用 update_time → 记提醒，下一轮注入。"""
        called = any(tc.get("name") == "update_time" for tc in tool_records)
        hit = _time_advanced(events)
        if called:
            self.session.pending_time_note = ""
        elif hit:
            if not self.session.pending_time_note:
                print(f"[time] 叙述含时间流逝「{hit}」但未调用 update_time")
            self.session.pending_time_note = self._TIME_NOTE.format(hit=hit)

    def _scene_ui_events(self, events) -> list[dict]:
        """小模型判断本幕背景 / 音乐。

        - 传入当前地点 + 当前背景/音乐，供小模型判断；
        - **换曲规则**：背景变化 **或** 当前曲已不适用于本地点/在场时，才允许换曲；
          当前曲不再适用且模型没给新曲 → 发「停乐」。
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
        loc = world_state.current_location()
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
            return []

        bg_ev = next((e for e in produced if e.get("kind") == "bg"), None)
        music_ev = next((e for e in produced if e.get("kind") == "music"), None)

        out = []
        scene_changed = False
        if bg_ev:
            data = bg_ev.get("data") or {}
            key = (data.get("position"), data.get("time"))
            if key != self.session.last_bg:
                self.session.last_bg = key
                scene_changed = True
                out.append(bg_ev)

        # 当前曲是否仍适用于本地点 / 在场
        try:
            allowed = set(ui_sim.narrative_tracks(loc, present))
        except Exception:
            allowed = set()
        last = self.session.last_music
        music_invalid = bool(last) and last not in allowed

        if music_ev and (scene_changed or music_invalid):
            track = (music_ev.get("data") or {}).get("track")
            if track != last or music_invalid:
                self.session.last_music = track
                out.append(music_ev)
        elif music_invalid and not music_ev:
            # 当前曲已不适用，模型也没给新曲 → 停乐
            self.session.last_music = ""
            out.append(music_event(ui_sim.NONE))
        return out

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
        """尝试解析指令数组，失败返回 None。"""
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
        return data if isinstance(data, list) else None
