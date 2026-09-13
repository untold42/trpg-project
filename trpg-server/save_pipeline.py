# -*- coding: utf-8 -*-
"""
save_pipeline.py
================
存档收尾管线（存档 = 结束本局）。

流程：
    1. 代码：从 turns.jsonl 誊写本局逐字叙事（transcript）
    2. LLM ：按《存档流程.md》蒸馏 transcript → gm_memory（客观）+ char_memory（主观）
    3. 代码：transcript 写入 游戏数据/游戏存档.md（供下一局读作前情）
    4. 代码：归档一份到 tools/归档存档/
    5. 代码：重置会话（history + turns.jsonl）；玩家状态保留（故事连续）

分工：代码负责机械部分（誊写 / 归档 / 重置），LLM 只负责语义蒸馏。
不再让 LLM 用文件工具写 游戏数据/（会撞上写保护）。
"""

from __future__ import annotations

import json
from pathlib import Path

from engine import read_turns

SERVER_DIR = Path(__file__).resolve().parent
GAME_DATA_DIR = SERVER_DIR / "tools" / "游戏数据"
SAVE_TRANSCRIPT = GAME_DATA_DIR / "游戏存档.md"
ARCHIVE_DIR = SERVER_DIR / "tools" / "归档存档"
SAVE_FLOW_DOC = SERVER_DIR.parent / "trpg-world" / "存档流程.md"

# 会改变玩家状态的工具（其效果誊写进存档；查询类不誊写）
_MUTATING = {
    "modify_money", "modify_item", "add_item", "remove_item",
    "modify_hunger", "modify_health", "modify_injury", "modify_hp", "modify_tp",
    "update_location", "update_time", "update_weather",
}

# 前端/后端加在玩家输入前的角色/主持人前缀
_IC_PREFIX = "梁峰："
_GM_PREFIX = "玩家的对主持人说的话："


def _render_user(turn: dict) -> str:
    """按 mode 区分「角色行动」（IC）与「玩家对主持人的场外话」（OOC）。

    OOC 渲染为【场外】，且**不参与记忆蒸馏**（见 存档流程.md 铁律）。
    """
    s = (turn.get("user") or "").strip()
    if turn.get("mode") == "gm" or s.startswith(_GM_PREFIX):
        return "【场外】" + s.removeprefix(_GM_PREFIX)
    return "你说：" + s.removeprefix(_IC_PREFIX)


def _render_instruction(item) -> list[str]:
    """把一条叙事指令渲染成存档文本行。"""
    if not isinstance(item, dict):
        return []
    t = item.get("type")
    if t == "chat":
        return [f"{item.get('speaker', '?')}：「{item.get('content', '')}」"]
    if t == "narration":
        return [item.get("content", "")]
    return []  # bg / ui 等不誊写


def _render_tools(tool_calls) -> list[str]:
    """只誊写会改变状态的工具效果。"""
    lines = []
    for tc in tool_calls or []:
        if tc.get("name") not in _MUTATING:
            continue
        res = tc.get("result")
        if isinstance(res, dict):
            res = res.get("message") or res.get("error") or json.dumps(res, ensure_ascii=False)
        lines.append(f"（系统：{res}）")
    return lines


def build_transcript(turns: list[dict]) -> str:
    """把回合日志渲染成逐字叙事存档（按游戏内时间分段）。"""
    if not turns:
        return "# 存档\n\n（本局无记录）\n"
    out = []
    cur_time = None
    for turn in turns:
        gtime = turn.get("time") or ""
        if gtime and gtime != cur_time:
            out.append(f"\n## {gtime}")
            cur_time = gtime
        out.append(_render_user(turn))
        try:
            items = json.loads(turn.get("assistant_raw") or "[]")
        except json.JSONDecodeError:
            items = []
        for it in items if isinstance(items, list) else []:
            out.extend(_render_instruction(it))
        out.extend(_render_tools(turn.get("tool_calls")))
    return "# 存档 · 本局记录\n" + "\n".join(out).strip() + "\n"


def _date_range(turns: list[dict]):
    dates = [t.split(" ")[0] for t in (x.get("time", "") for x in turns) if t]
    if not dates:
        return "未知日期", "未知日期"
    return dates[0], dates[-1]


def write_current_transcript(transcript: str) -> Path:
    """覆盖写 游戏数据/游戏存档.md（下一局读作前情）。"""
    SAVE_TRANSCRIPT.write_text(transcript, encoding="utf-8")
    return SAVE_TRANSCRIPT


def archive_transcript(transcript: str, start: str, end: str) -> Path:
    """归档到 tools/归档存档/<起>~<止> 存档.md（重名自动加序号）。"""
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    span = start if start == end else f"{start}~{end}"
    path = ARCHIVE_DIR / f"{span} 存档.md"
    i = 2
    while path.exists():
        path = ARCHIVE_DIR / f"{span} 存档_{i}.md"
        i += 1
    path.write_text(transcript, encoding="utf-8")
    return path


def load_save_rules() -> str:
    try:
        return SAVE_FLOW_DOC.read_text(encoding="utf-8")
    except OSError:
        return "（未找到 存档流程.md）"


def run_save(session, runner) -> dict:
    """执行完整存档管线。返回结果摘要。"""
    turns = read_turns(session.log_path)
    if not turns:
        return {"success": False, "error": "本局没有可存档的记录"}

    # 1) 誊写
    transcript = build_transcript(turns)

    # 2) LLM 蒸馏（写长期记忆）
    result = runner.run_save(transcript, load_save_rules())
    distilled = [c["name"] for c in result.get("tool_calls", [])]

    # 3) 写前情 + 归档
    write_current_transcript(transcript)
    start, end = _date_range(turns)
    archive = archive_transcript(transcript, start, end)

    # 4) 重置会话（玩家状态保留）
    session.reset()

    return {
        "success": True,
        "turns": len(turns),
        "distilled": distilled,
        "archive": archive.name,
        "transcript": str(SAVE_TRANSCRIPT),
    }
