# -*- coding: utf-8 -*-
"""
time_weather.py
===============
修改 游戏数据/基本信息.json 里的「时间」与「天气」字段，供 LLM function calling 调用。

    update_time:     设置或推进游戏时间（日期 + 十二时辰）
    update_weather:  设置天气（状况/温度/风力/描述）

时间规则（遵循 世界.md）：
    - 日期格式 YYYY-MM-DD，如 1220-01-15
    - 时辰必须是十二时辰：子丑寅卯辰巳午未申酉戌亥
"""

import datetime

from tools.state_manager import state

# 十二时辰（顺序固定；跨过「子时」算进入新一天。12 个时辰 = 1 天）
SHICHEN = ["子时", "丑时", "寅时", "卯时", "辰时", "巳时",
           "午时", "未时", "申时", "酉时", "戌时", "亥时"]

# 每时辰 8 刻（1 刻 ≈ 15 分钟）；96 刻 = 1 天
KE_PER_SHICHEN = 8
KE_CN = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七"}


def _parse_date(s):
    """'1220-01-15' -> datetime.date，失败返回 None。"""
    try:
        y, m, d = (int(x) for x in str(s).split("-"))
        return datetime.date(y, m, d)
    except (ValueError, TypeError):
        return None


def update_time(date=None, shichen=None, ke=None, advance_shichen=None, advance_ke=None):
    """设置或推进游戏时间（十二时辰，每时辰八刻；1 刻 ≈ 15 分钟）。

    - `date` / `shichen` / `ke`：直接设置日期 / 时辰 / 刻（刻 0-7）；
    - `advance_shichen` / `advance_ke`：从当前时间往前推进若干**时辰 / 刻**
      （8 刻 = 1 时辰，12 时辰 = 1 天，跨过子时进入新一天）。
    """
    data = state.load("基本信息", {})
    t = data.setdefault("时间", {})

    if advance_shichen is not None or advance_ke is not None:
        n_ke = (advance_shichen or 0) * KE_PER_SHICHEN + (advance_ke or 0)
        if n_ke < 0:
            return {"success": False, "error": "推进量不能为负数"}

        cur = t.get("时辰")
        cur_date = _parse_date(t.get("日期"))
        cur_ke = t.get("刻", 0)
        if cur not in SHICHEN:
            return {"success": False, "error": f"当前时辰「{cur}」不是十二时辰之一，无法推进"}
        if cur_date is None:
            return {"success": False, "error": f"当前日期「{t.get('日期')}」格式错误，无法推进"}
        if not isinstance(cur_ke, int) or not (0 <= cur_ke < KE_PER_SHICHEN):
            cur_ke = 0

        total = SHICHEN.index(cur) * KE_PER_SHICHEN + cur_ke + n_ke
        t["日期"] = (cur_date + datetime.timedelta(days=total // (12 * KE_PER_SHICHEN))).strftime("%Y-%m-%d")
        t["时辰"] = SHICHEN[(total // KE_PER_SHICHEN) % 12]
        t["刻"] = total % KE_PER_SHICHEN
    else:
        if date is None and shichen is None and ke is None:
            return {
                "success": False,
                "error": "必须提供 date、shichen、ke 或 advance_shichen/advance_ke 中的至少一项",
            }
        if date is not None:
            d = _parse_date(date)
            if d is None:
                return {"success": False, "error": f"日期格式应为 YYYY-MM-DD，收到 {date}"}
            t["日期"] = d.strftime("%Y-%m-%d")
        if shichen is not None:
            if shichen not in SHICHEN:
                return {"success": False, "error": f"时辰必须是十二时辰之一，收到 {shichen}"}
            t["时辰"] = shichen
        if ke is not None:
            if not isinstance(ke, int) or not (0 <= ke < KE_PER_SHICHEN):
                return {"success": False, "error": f"刻必须是 0-{KE_PER_SHICHEN - 1} 的整数"}
            t["刻"] = ke

    state.save("基本信息", data)
    return {"success": True, "时间": {"日期": t.get("日期"), "时辰": t.get("时辰"), "刻": t.get("刻", 0)}}


def update_weather(condition=None, temperature=None, wind=None, description=None):
    """修改天气。只传需要修改的字段即可（不传的保持原样）。"""
    if condition is None and temperature is None and wind is None and description is None:
        return {"success": False, "error": "至少提供一个要修改的天气字段"}

    data = state.load("基本信息", {})
    w = data.setdefault("天气", {})

    if condition is not None:
        w["状况"] = condition
    if temperature is not None:
        w["温度"] = temperature
    if wind is not None:
        w["风力"] = wind
    if description is not None:
        w["描述"] = description

    state.save("基本信息", data)
    return {"success": True, "天气": w}
