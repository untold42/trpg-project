# -*- coding: utf-8 -*-
"""
place_hours.py
==============
地点**营业时间**（开门 / 打烊）——单一真相源：`trpg-world/营业时间.json`。

给「城市知识库」用：
    - NPC 可以据此说「药铺早打烊了」「客栈通宵」；
    - 前端按当前时辰判断图标是否「亮灯」（打烊的不发光）。

时段格式：时辰名闭区间，如 `"卯-酉"`（跨夜用 `"午-子"`）；`"全天"` = 不打烊。
"""

import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent  # trpg-project/
_JSON = _ROOT / "trpg-world" / "营业时间.json"

SHICHEN = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]

_cache = None  # (mapping, default)


def _load():
    global _cache
    if _cache is None:
        default = "全天"
        mapping = {}
        try:
            data = json.loads(_JSON.read_text(encoding="utf-8"))
            default = data.get("默认") or "全天"
            for hours, kinds in (data.get("时段") or {}).items():
                for k in kinds or []:
                    mapping[k] = hours
        except Exception:
            pass
        _cache = (mapping, default)
    return _cache


def hours_for(kind):
    """某地点的营业时间字符串（未列出 → 默认）。"""
    mapping, default = _load()
    if not kind:
        return default
    return mapping.get(str(kind), default)


def shichen_index(name):
    """时辰名 → 索引（子=0…亥=11）；失败 -1。"""
    try:
        return SHICHEN.index(str(name).strip())
    except (ValueError, TypeError):
        return -1


def parse_hours(hours):
    """'卯-酉' → (3, 9)；'全天'/异常 → None（表示始终开）。"""
    if not hours or hours == "全天":
        return None
    for sep in ("-", "~", "－", "—"):
        if sep in hours:
            a, _, b = hours.partition(sep)
            s, e = shichen_index(a), shichen_index(b)
            if s >= 0 and e >= 0:
                return (s, e)
    return None


def is_open(hours, shichen_i):
    """在 shichen_i 时辰该地点是否营业（hours 无法解析 / 时辰未知 → True）。"""
    rng = parse_hours(hours)
    if rng is None or shichen_i < 0:
        return True
    s, e = rng
    if s <= e:
        return s <= shichen_i <= e
    return shichen_i >= s or shichen_i <= e  # 跨夜（如 午-子）


def now_shichen_index():
    """当前游戏时辰索引（读 基本信息.时间.时辰）。"""
    try:
        from tools.state_manager import state
        t = (state.load("基本信息", {}) or {}).get("时间", {}) or {}
        return shichen_index(t.get("时辰", ""))
    except Exception:
        return -1
