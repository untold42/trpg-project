# -*- coding: utf-8 -*-
"""
derived.py
==========
派生上限：由 `属性.json` 的基础属性推出 `状态.json` 的**上限**。

    体力 = 生命值上限      属性.基础属性.体力  →  状态.生命上限
    内力 = 精力值上限      属性.基础属性.内力  →  状态.精力上限

`属性.json` 是**真相源**（养成改它，见其 `_备注`）；`状态.json` 的上限是它的**投影**。
`sync()` 在两者漂移时以属性为准回写，并把超出的当前值夹到上限。

承总纲第 5 条：上限是硬事实，由代码从属性推出，不让两处各写各的。
"""

from __future__ import annotations

from tools.核心.state_manager import state

#: (状态.上限字段, 状态.当前字段, 属性.基础字段)
_MAP = (
    ("生命上限", "生命值", "体力"),
    ("精力上限", "精力值", "内力"),
)


def _attr_int(key: str):
    """读 属性.基础属性.{key}，返回正整数；缺失/非法返回 None。"""
    attr = state.load("属性", {}) or {}
    base = attr.get("基础属性")
    if not isinstance(base, dict):
        return None
    v = base.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    v = int(v)
    return v if v > 0 else None


def max_hp():
    """生命值上限（= 体力）。"""
    return _attr_int("体力")


def max_tp():
    """精力值上限（= 内力）。"""
    return _attr_int("内力")


def sync() -> dict:
    """把 状态.json 的上限对齐到 属性.json（体力→生命上限，内力→精力上限）。

    - 属性缺失/非法 → 跳过该字段（不回退、不清零）；
    - 上限变小 → 当前值一并夹到上限；
    - 仅在确实变化时落盘。
    """
    data = state.load("状态", {}) or {}
    changed = False
    for cap_key, cur_key, attr_key in _MAP:
        v = _attr_int(attr_key)
        if v is None:
            continue
        if data.get(cap_key) != v:
            data[cap_key] = v
            changed = True
        cur = data.get(cur_key)
        if isinstance(cur, (int, float)) and not isinstance(cur, bool) and cur > v:
            data[cur_key] = v
            changed = True
    if changed:
        try:
            state.save("状态", data)
        except OSError as e:      # 文件被占用：不抛，下次再试
            print(f"[derived] 写回 状态 上限失败，稍后重试：{e}")
    return data
