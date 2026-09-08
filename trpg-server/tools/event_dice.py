# -*- coding: utf-8 -*-
"""
event_dice.py
=============
日常骰子事件 + 旅途骰子事件（供 LLM function calling 调用）。

规则见 trpg-world/主持人/日常骰子事件.md 与 旅途骰子事件.md。

混乱值从 游戏数据/混乱度.json 读取（可选参数覆盖）。
"""

import random

from tools.state_manager import state


def _get_chaos():
    data = state.load("混乱度", {})
    try:
        return int(data.get("混乱值", 0))
    except (TypeError, ValueError):
        return 0


def daily_event_dice(chaos=None):
    """日常骰子事件：一级骰定类型 + 二级骰定烈度（含混乱修正）。"""
    c = float(_get_chaos() if chaos is None else chaos)
    r1 = random.randint(0, 100)

    if r1 <= 20:
        etype = "场景热闹"
    elif r1 <= 64:
        etype = "城市风味"
    elif r1 <= 89:
        etype = "有人搭话"
    else:
        etype = "麻烦与危险"

    r2 = random.randint(0, 99)
    final = r2 + c * 0.25

    if final <= 30:
        level = "偏顺"
    elif final <= 70:
        level = "中性"
    elif final <= 99:
        level = "带刺"
    else:
        level = "危险"

    return {
        "success": True,
        "混乱值": c,
        "一级骰": r1,
        "事件类型": etype,
        "二级骰": r2,
        "混乱修正": round(c * 0.25, 1),
        "最终烈度": round(final, 1),
        "档位": level,
    }


def travel_event_dice(chaos=None):
    """旅途骰子事件：单骰 + 混乱修正，低顺高不顺。"""
    c = float(_get_chaos() if chaos is None else chaos)
    r = random.randint(0, 99)
    final = r + c * 0.25

    if final < 15:
        level, direction = "顺风顺水", "大顺"
    elif final < 35:
        level, direction = "偶遇友善", "小顺"
    elif final < 70:
        level, direction = "平淡无事", "平"
    elif final < 80:
        level, direction = "天气变化", "小不顺"
    elif final < 87:
        level, direction = "小波折", "中不顺"
    elif final < 93:
        level, direction = "旅途异象", "异象"
    elif final < 97:
        level, direction = "麻烦上门", "麻烦"
    else:
        level, direction = "危险", "危险"

    return {
        "success": True,
        "混乱值": c,
        "骰值": r,
        "混乱修正": round(c * 0.25, 1),
        "最终骰值": round(final, 1),
        "等级": level,
        "方向": direction,
    }
