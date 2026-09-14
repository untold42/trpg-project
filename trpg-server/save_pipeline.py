# -*- coding: utf-8 -*-
"""
save_pipeline.py
================
存档收尾管线（存档 = 结束本局）。

流程：
    1. 代码：从 current.jsonl 誊写本局逐字叙事（transcript）
    2. LLM ：按《存档流程.md》蒸馏 transcript → gm_memory（客观）+ char_memory（主观）
    3. 代码：transcript 写入 游戏数据/游戏存档.md（供下一局读作前情）
    4. 代码：归档一份到 归档存档/
    5. 代码：重置会话（history + current.jsonl）；玩家状态保留（故事连续）

分工：代码负责机械部分（誊写 / 归档 / 重置），LLM 只负责语义蒸馏。
不再让 LLM 用文件工具写 游戏数据/（会撞上写保护）。
"""

from __future__ import annotations

import json
from pathlib import Path

from engine import parse_instructions, read_turns
from tools import world_state
from tools import character_archive
from tools.get_character import CHARACTER_DIR

SERVER_DIR = Path(__file__).resolve().parent
GAME_DATA_DIR = SERVER_DIR / "游戏数据"
SAVE_TRANSCRIPT = GAME_DATA_DIR / "游戏存档.md"
ARCHIVE_DIR = SERVER_DIR / "归档存档"
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

# 接触名单过滤：玩家本人、旁白/系统等非人物发言者
_PLAYER = "梁峰"
_NON_CHARACTERS = {"旁白", "系统", "主持人", "你", ""}


def _render_user(turn: dict) -> str:
    """按 mode 渲染玩家输入，**只改前缀**为「梁峰」开头（内容不动）。

    - 行动 / 台词 → `梁峰：…` / `梁峰说：「…」`
    - 场外（OOC）→ `梁峰（场外）：…`（标了「场外」的行**不参与记忆蒸馏**）
    """
    s = (turn.get("user") or "").strip()
    if turn.get("mode") == "continue":
        return "梁峰：（静观其变，时间流逝）"
    if turn.get("mode") == "say":
        body = s.removeprefix("梁峰开口说：「")
        if body.endswith("」"):
            body = body[:-1]
        return "梁峰说：「" + body + "」"
    if turn.get("mode") == "gm" or s.startswith(_GM_PREFIX):
        return "梁峰（场外）：" + s.removeprefix(_GM_PREFIX)
    return "梁峰：" + s.removeprefix(_IC_PREFIX)


def _render_instruction(item) -> list[str]:
    """把一条叙事指令渲染成存档文本行，**只改前缀**：旁白→`GM：`，NPC 台词→`GM（人名）：`。"""
    if not isinstance(item, dict):
        return []
    t = item.get("type")
    if t == "chat":
        return [f"GM（{item.get('speaker', '?')}）：「{item.get('content', '')}」"]
    if t == "narration":
        return [f"GM：{item.get('content', '')}"]
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
        lines.append(f"GM（系统）：{res}")
    return lines


# 可用于识别“本局登场人物”的档案查询工具（get_character 已替代旧名）
_CHARACTER_TOOLS = {"get_character", "find_specific_character"}


def distilled_char_memory(result: dict) -> dict:
    """从蒸馏回合取 `char_memory` 记录，按 owner 分组。

    返回 `{owner: [{"time", "kind", "content"}, ...]}`。
    """
    out: dict[str, list] = {}
    for tc in (result or {}).get("tool_calls", []):
        if tc.get("name") != "DB_add_and_update_tool":
            continue
        args = tc.get("arguments") or {}
        if args.get("collection") != "char_memory":
            continue
        owner = str(args.get("owner") or "").strip()
        content = str(args.get("content") or "").strip()
        if not owner or not content:
            continue
        out.setdefault(owner, []).append({
            "time": str(args.get("time") or "").strip(),
            "kind": str(args.get("kind") or "").strip(),
            "content": content,
        })
    return out


def distilled_owners(result: dict) -> tuple:
    """从蒸馏回合取 `char_memory` 的 owner（角色名）。"""
    return tuple(distilled_char_memory(result).keys())


def archived_characters(result: dict) -> set:
    """从存档蒸馏回合里取 `update_character_archive` 的人物名（本局建档的 NPC）。"""
    names: set[str] = set()
    for tc in (result or {}).get("tool_calls", []):
        if tc.get("name") != "update_character_archive":
            continue
        n = (tc.get("arguments") or {}).get("name")
        if n:
            names.add(str(n).strip())
    return names


def contacted_characters(turns: list[dict], char_memory: dict | None = None,
                         archived: set | None = None) -> list[str]:
    """本局**有实质互动、需要建档**的人物。

    四个确定性来源（不依赖 LLM 判断）：
      1. 叙事里开口的 `chat` 发言人；
      2. 主持人查过档案的 `get_character`（取其解析出的规范名）；
      3. 本局蒸馏进 `char_memory` 的 owner（兼容旧流程）；
      4. 本局 `update_character_archive` 建过档的人物。

    保留规则：**有静态档案** **或** 在上述来源里出现过（即视为有实质互动）。
    """
    owners = set((char_memory or {}).keys())
    archived = set(archived or ())
    found: set[str] = set(owners) | archived
    for turn in turns:
        for it in parse_instructions(turn.get("assistant_raw")):
            if isinstance(it, dict) and it.get("type") == "chat":
                sp = str(it.get("speaker") or "").strip()
                if sp:
                    found.add(sp)
        for tc in turn.get("tool_calls") or []:
            if tc.get("name") not in _CHARACTER_TOOLS:
                continue
            res = tc.get("result")
            if isinstance(res, dict) and res.get("success") and res.get("name"):
                found.add(str(res["name"]).strip())
            else:
                arg = (tc.get("arguments") or {}).get("name")
                if arg:
                    found.add(str(arg).strip())
    names = [
        n for n in found
        if n and n not in _NON_CHARACTERS and n != _PLAYER
        and ((CHARACTER_DIR / f"{n}.md").is_file() or n in owners or n in archived)
    ]
    return sorted(set(names))


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
    """归档到 归档存档/<起>~<止> 存档.md（重名自动加序号）。"""
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

    # 3b) 活跃名单：把本局接触过的人物写进 角色动态档案/活跃/
    #     （世界推演只扫这个目录；不写 → 推演空转）
    char_mem = distilled_char_memory(result)
    archived = archived_characters(result)
    promoted = []
    try:
        for name in contacted_characters(turns, char_mem, archived):
            character_archive.ensure_static(name)  # 兼底：确保人人有静态档案
            if world_state.promote_active(name, start, "玩家接触", char_mem.get(name)):
                promoted.append(name)
    except Exception:  # 活跃名单失败不应拖垮存档
        promoted = []

    # 4) 重置会话（玩家状态保留）
    session.reset()

    return {
        "success": True,
        "turns": len(turns),
        "distilled": distilled,
        "promoted": promoted,
        "archive": archive.name,
        "transcript": str(SAVE_TRANSCRIPT),
    }
