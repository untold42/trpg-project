# -*- coding: utf-8 -*-
"""
engine.py
=========
游戏引擎：回合运行 + 会话状态 + 过程日志。

职责边界（见 ARCHITECTURE.md 第五节）：
    - GameSession  : 持有 history（纯叙事）与 turns.jsonl（过程真相），负责落盘/恢复
    - TurnRunner   : 一次玩家动作的完整回合（LLM 工具循环），产出给前端的
                    统一事件流（叙事指令 + 工具 UI 事件）
    - 状态注入      : 每次调用 LLM 都从 state_manager 现拼「当前状态」，只出现一次

main.py 只负责 bootstrap（建 session/runner）与路由，不再持有 history、不再写工具循环。

关键设计（为什么这么做）：
    - history 只存 user / assistant 正文，工具中间消息不进 history（原先靠
      collapse_tool_messages 事后清理，现在从源头就不落进去）。
    - 状态不进 history，而是每次 build_messages 时现拼、放在 messages 末尾。
      这样上下文里的状态永远唯一且最新，落实「数据先于叙述」。
    - turns.jsonl 每轮追加：唯一的「边玩边写」。一次磁盘 append 成本可忽略，
      换来崩溃安全与后续「存档誊写」的原始素材。
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from tools.folder_to_prompt import folder_to_prompt  # noqa: F401  (供 main 使用)
from tools.state_manager import state
from tools.ui_events import UI_EVENTS_KEY
from tools import world_state
from tools import world_worker

# ------------------------------------------------------------
# 路径
# ------------------------------------------------------------
SERVER_DIR = Path(__file__).resolve().parent
SESSIONS_DIR = SERVER_DIR / "sessions"
CURRENT_LOG = SESSIONS_DIR / "current.jsonl"
GAME_DATA_DIR = SERVER_DIR / "tools" / "游戏数据"
SAVE_TRANSCRIPT = GAME_DATA_DIR / "游戏存档.md"


# ------------------------------------------------------------
# 上下文素材
# ------------------------------------------------------------
def snapshot_state() -> str:
    """现拼当前机械状态（游戏数据/*.json）为一段文本。不含 游戏存档.md。"""
    snapshot = state.snapshot()
    if not snapshot:
        return "（暂无状态数据）"
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
    """当前游戏内时间（日期 + 时辰），形如 '1220-01-15 酉时'。"""
    t = (state.load("基本信息", {}) or {}).get("时间", {}) or {}
    return f"{t.get('日期', '')} {t.get('时辰', '')}".strip()


# ------------------------------------------------------------
# 过程日志的读取与渲染（单一真相源：turns.jsonl）
# ------------------------------------------------------------
_IC_PREFIX = "梁峰："
_GM_PREFIX = "玩家的对主持人说的话："


def read_turns(log_path) -> list[dict]:
    """读取 turns.jsonl（跳过写了一半的坏行）。"""
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
        if turn.get("mode") == "gm" or s.startswith(_GM_PREFIX):
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
    - turns.jsonl  : 过程真相，每轮一行，重启可恢复
    """

    def __init__(self, rules_prompt: str, log_path: Path = CURRENT_LOG):
        self.rules_prompt = rules_prompt
        self.log_path = Path(log_path)
        self.history: list[dict] = []
        self.previous_story = load_previous_story()
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
        """从 turns.jsonl 重建 history（崩溃/重启后继续同一局）。"""
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
        """追加一轮到 turns.jsonl（原子性由单行写入保证）。"""
        with self._lock:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(turn, ensure_ascii=False) + "\n")

    def reset(self):
        """结束本局：清空 history 与 turns.jsonl。玩家状态保留（故事连续）。

        重置后重新读取刚写好的 游戏存档.md 作为下一局的前情提要，
        并记录新本局的开局状态快照。
        """
        with self._lock:
            self.history = []
            if self.log_path.exists():
                self.log_path.unlink()
            self.previous_story = load_previous_story()
            self._take_snapshot()
            world_worker.clear()  # 底层状态已变，清空待推演任务

    def abandon(self) -> bool:
        """放弃本轮：玩家状态**回滚到本局开始**，丢弃本局日志，开始新本局。

        与 reset 的区别：reset 保留现状（存档用），abandon 先回滚快照（放弃用）。
        返回是否成功回滚。
        """
        with self._lock:
            restored = self._restore_snapshot()
            self.history = []
            if self.log_path.exists():
                self.log_path.unlink()
            self.previous_story = load_previous_story()
            self._take_snapshot()  # 新本局从回滚后的状态开始
            world_worker.clear()
            return restored

    # ---- 历史视图（供前端 GET /history）----
    def history_view(self) -> dict:
        """当前本局的历史：面板文本行 + 最后一轮的指令（用于续玩）。"""
        turns = read_turns(self.log_path)
        tail = parse_instructions(turns[-1].get("assistant_raw")) if turns else []
        return {"active": bool(turns), "lines": history_lines(turns), "tail": tail}

    # ---- 上下文组装 ----
    def _system_messages(self) -> list[dict]:
        msgs = [{"role": "system", "content": self.rules_prompt}]
        if self.previous_story:
            msgs.append({
                "role": "system",
                "content": "===== 前情提要（上一轮存档）=====\n" + self.previous_story,
            })
        return msgs

    def build_messages(self, tool_msgs: list[dict] | None = None) -> list[dict]:
        """组装本次发往 LLM 的 messages。

        结构：[规则, 前情?, ...history, ...本轮工具消息, 当前状态]
        状态放末尾（稳定前缀利于上下文缓存），且每次现拼、只出现一份。
        """
        return (
            self._system_messages()
            + self.history
            + list(tool_msgs or [])
            + [{
                "role": "system",
                "content": "===== 当前状态 =====\n" + snapshot_state(),
            }]
        )


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

        session.history.append({"role": "assistant", "content": raw})
        session.append_turn({
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "time": current_game_time(),
            "mode": mode,
            "user": user_input,
            "assistant_raw": raw,
            "tool_calls": tool_records,
            "ui_events": ui_events,
        })
        # 世界推演：检测跨天并入队（异步，不阻塞玩家）
        world_worker.on_turn_end()
        # 统一事件流：工具产生的 UI 事件在前，LLM 的叙事指令在后
        return ui_events + events

    # ---- 存档蒸馏专用回合 ----
    def run_save(self, transcript: str, rules: str) -> dict:
        """把本局记录蒸馏进长期记忆。

        与普通回合不同：**不写 history、不写 turns.jsonl**（这不是叙事回合）。
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

            result = self.send_messages(base + [state_msg])
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
                result = self.send_messages(base + tool_msgs + [state_msg])

            return {"content": result.content or "", "tool_calls": tool_records}

    def _call_tool(self, name: str, arguments: dict):
        tool = self.tools_map.get(name)
        if tool is None:
            return {"success": False, "error": f"未知工具: {name}"}
        try:
            return tool(**arguments)
        except Exception as e:  # 工具异常不应打断整局
            return {"success": False, "error": str(e)}

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
