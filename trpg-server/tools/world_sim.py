# -*- coding: utf-8 -*-
"""
world_sim.py
============
单日世界推演。

设计（ARCHITECTURE.md 第七节）：
    - **小模型只做离散采样**：对每个活跃人物，输出 {地点, 事件类型}（极简、无幻觉面）；
    - **顺利度由代码加权掷骰**（不交给模型）：顺+平 ≈ 90%；
    - **具体叙事不在这里产生**——由大模型在玩家遇到该人物时按正典自行演绎。

每次推演 = 一个游戏日：
    1. 触发当天（及已逾期）的宏观定时线条目
    2. 对每个活跃人物采样（与玩家同地点者豁免）
    3. 写回 世界状态.json，游标推进到当天
"""

import json
import random
from pathlib import Path

from tools import small_model, world_state

_ROOT = Path(__file__).resolve().parent.parent.parent
SIM_DIR = _ROOT / "trpg-world" / "世界推演"
TIMELINE_FILE = SIM_DIR / "宏观时间线.json"
RULES_FILE = SIM_DIR / "推演规则.md"
CHAR_DIR = _ROOT / "trpg-world" / "角色静态档案"

KINDS = ["营生", "修行", "社交", "赶路", "生活", "公务", "寻医", "变故"]

# 顺利度权重：顺 + 平 ≈ 90%
SMOOTHNESS_WEIGHTS = [("大顺", 5), ("顺", 45), ("平", 45), ("不顺", 4), ("大挫", 1)]

FALLBACK_RULES = (
    "你是武侠世界（南宋嘉定年间）的离线推演器。只输出 JSON。字段必须极简："
    "地点只填地名（2-6 个字，如「福州」「襄阳」），事件类型只从枚举里选一个。"
    "禁止叙述、禁止解释、禁止思考。"
    "注意：人物不会日行千里，地点应与其现状相符。"
)

CHAR_SCHEMA = {
    "type": "object",
    "properties": {
        "地点": {"type": "string", "description": "地名，2-6 字"},
        "事件类型": {"type": "string", "enum": KINDS},
    },
    "required": ["地点", "事件类型"],
}


def roll_smoothness() -> str:
    """加权掷骰决定顺利度。"""
    roll = random.randint(1, 100)
    acc = 0
    for name, weight in SMOOTHNESS_WEIGHTS:
        acc += weight
        if roll <= acc:
            return name
    return "平"


def _rules() -> str:
    try:
        return RULES_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return FALLBACK_RULES


def _profile(name: str, max_chars: int = 700) -> str:
    """读人物静态档案（去 frontmatter、截断），给小模型当上下文。"""
    path = CHAR_DIR / f"{name}.md"
    if not path.is_file():
        return f"（无 {name} 的档案）"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return f"（{name} 档案读取失败）"
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            text = parts[2]
    return text.strip()[:max_chars]


def ensure_timeline():
    """把作者的 宏观时间线.json 种进 世界状态.定时线（只种一次）。

    种进 世界状态（而非直接读文件）是为了让"已触发"标记也能随开局快照回滚。
    """
    data = world_state.load()
    if data.get("定时线"):
        return
    try:
        raw = json.loads(TIMELINE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    data["定时线"] = [
        {"date": e.get("date", ""), "text": e.get("text", ""), "已触发": False}
        for e in raw if isinstance(e, dict)
    ]
    world_state.save(data)


def _trigger_macro(date: str) -> list[dict]:
    """触发当天及逾期未触发的宏观条目。"""
    data = world_state.load()
    fired = []
    for e in data.get("定时线", []):
        if not e.get("已触发") and e.get("date", "") and e["date"] <= date:
            e["已触发"] = True
            item = {"date": date, "text": e.get("text", "")}
            data.setdefault("宏观", []).append(item)
            fired.append(item)
    if fired:
        world_state.save(data)
    return fired


def simulate_character(name: str, date: str):
    """对单个活跃人物采样。成功返回 {日期,地点,类型,顺利度}，失败返回 None。"""
    th = world_state.character_thread(name)
    latest = th.get("最新", {}) or {}
    user = (
        f"人物档案（节选）：\n{_profile(name)}\n\n"
        f"现状：地点={th.get('地点', '未知')}；最近在做={latest.get('类型', '未知')}。\n"
        f"今天是 {date}。他/她这一天在哪（2-6 字地名）、主要在做什么（枚举之一）？"
    )
    r = small_model.ask_json(_rules(), user, CHAR_SCHEMA)
    if not r:
        return None
    loc = str(r.get("地点", "")).strip()[:12] or th.get("地点", "未知")
    kind = r.get("事件类型")
    if kind not in KINDS:
        kind = "生活"
    return {"日期": date, "地点": loc, "类型": kind, "顺利度": roll_smoothness()}


def fast_forward(date: str):
    """大跨度跳过：游标直接推到 date，其间到时未推演的定时线条目
    标记为已触发并记入宏观（附「未及推演」）。
    """
    data = world_state.load()
    for e in data.get("定时线", []):
        if not e.get("已触发") and e.get("date", "") and e["date"] <= date:
            e["已触发"] = True
            data.setdefault("宏观", []).append(
                {"date": date, "text": (e.get("text", "") + "（未及推演）")})
    data["模拟游标"] = date
    world_state.save(data)


def run_day(date: str, player_location: str = None) -> dict:
    """推演一个游戏日。返回 {date, macro, characters}。"""
    ensure_timeline()
    macro = _trigger_macro(date)
    results = []
    for name in world_state.active_characters():
        th = world_state.character_thread(name)
        # 在场豁免：与玩家同地点者由主持人处理，不推演
        if player_location and th.get("地点") == player_location:
            continue
        r = simulate_character(name, date)
        if r:
            world_state.update_character(name, date, r["地点"], r["类型"], r["顺利度"])
            results.append({"name": name, **r})
    world_state.set_cursor(date)
    return {"date": date, "macro": macro, "characters": results}
