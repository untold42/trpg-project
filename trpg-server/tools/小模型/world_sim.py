# -*- coding: utf-8 -*-
"""
world_sim.py
============
单日世界推演。

设计（README.md §5.6）：
    - **小模型只做离散采样**：对每个活跃人物，输出 {地点, 事件类型}（极简、无幻觉面）；
    - **顺利度由代码加权掷骰**（不交给模型）：顺+平 ≈ 90%；
    - **具体叙事不在这里产生**——由大模型在玩家遇到该人物时按正典自行演绎。

每次推演 = 一个游戏日：对**每个活跃人物**采样（是否进大模型上下文由小模型的
「纳入上下文」决定），写回 `游戏数据/世界线程.json`，游标推进到当天。
宏观事件**不在此处理**——由 `tools/macro_timeline.py` 按当前日期现切（只读剧本）。
"""

import random
from pathlib import Path

from tools.小模型 import small_model
from tools.核心 import world_threads

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SIM_DIR = _ROOT / "trpg-world" / "世界推演"
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
        "纳入上下文": {
            "type": "boolean",
            "description": "此事是否应立刻进入主持人上下文（依据离玩家远近）",
        },
    },
    "required": ["地点", "事件类型", "纳入上下文"],
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
    """读人物档案（去 frontmatter、截断），给小模型当上下文。

    优先静态档案；无静态档案时退回动态近记忆（安全网）。
    """
    path = CHAR_DIR / f"{name}.md"
    if not path.is_file():
        for d in (world_threads.ACTIVE_DIR, world_threads.INACTIVE_DIR):
            p = d / f"{name}.md"
            if p.is_file():
                path = p
                break
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


#: 宏观事件现由 `tools/macro_timeline.py` 按日期窗口现切（只读剧本，不拷贝、不记标记）。


def simulate_character(name: str, date: str, player_region: str = None,
                       player_location: str = None):
    """对单个活跃人物采样。成功返回 {日期,地点,类型,顺利度,纳入上下文}，失败返回 None。

    `纳入上下文`：小模型按「离玩家远近」判断此事是否该进大模型视野（只影响注入裁剪）。
    """
    th = world_threads.character_thread(name)
    latest = th.get("最新", {}) or {}
    where = "玩家此刻所在不详。"
    if player_region:
        where = f"玩家此刻在：{player_region}"
        if player_location and player_location != player_region:
            where += f"（{player_location}）"
    user = (
        f"人物档案（节选）：\n{_profile(name)}\n\n"
        f"现状：地点={th.get('地点', '未知')}；最近在做={latest.get('类型', '未知')}。\n"
        f"{where}\n"
        f"今天是 {date}。他/她这一天在哪（2-6 字地名）、主要在做什么（枚举之一）？\n"
        f"并判断：这件事离玩家够近、值得让主持人立刻知道吗（纳入上下文）？"
        f"远在天边、与玩家当前处境无关的填 false。"
    )
    r = small_model.ask_json(_rules(), user, CHAR_SCHEMA)
    if not r:
        return None
    loc = str(r.get("地点", "")).strip()[:12] or th.get("地点", "未知")
    kind = r.get("事件类型")
    if kind not in KINDS:
        kind = "生活"
    include = r.get("纳入上下文")
    if not isinstance(include, bool):
        include = True  # 缺省纳入（安全兜底）
    return {"日期": date, "地点": loc, "类型": kind,
            "顺利度": roll_smoothness(), "纳入上下文": include}


def fast_forward(date: str):
    """大跨度跳过：游标直接推到 date（不逐日模拟 NPC）。

    宏观事件已改为「只读剧本 + 按日期切窗口」（`tools/macro_timeline.py`），
    因此这里**只需推进游标**——不记任何「已触发」标记、不往档里拷贝事件。
    """
    world_threads.set_cursor(date)


def run_day(date: str, player_location: str = None, player_region: str = None) -> dict:
    """推演一个游戏日：对每个活跃人物采样、写回 世界线程、推进游标。

    （宏观事件不在此处理——由 `macro_timeline.view()` 按当前日期现切。）
    """
    results = []
    for name in world_threads.active_characters():
        r = simulate_character(name, date, player_region, player_location)
        if r:
            world_threads.update_character(name, date, r["地点"], r["类型"],
                                           r["顺利度"], include=r["纳入上下文"])
            results.append({"name": name, **r})
    world_threads.set_cursor(date)
    return {"date": date, "characters": results}
