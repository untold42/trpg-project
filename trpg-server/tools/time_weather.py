# -*- coding: utf-8 -*-
"""
time_weather.py
===============
修改 游戏数据/基本信息.json 里的「时间」与「天气」字段，供 LLM function calling 调用。

    update_time:     设置或推进游戏时间（日期 + 十二时辰）
    update_weather:  设置天气（状况/温度/风力/描述）

时间规则（遵循 世界.md / 可用场景.md）：
    - 日期格式 YYYY-MM-DD，如 1220-01-15
    - 时辰必须是十二时辰：子丑寅卯辰巳午未申酉戌亥
"""

import datetime

from tools.state_manager import state

# 十二时辰（顺序固定，每时辰合现代 2 小时，跨过子时算进入新一天）
HOURS = ["子时", "丑时", "寅时", "卯时", "辰时", "巳时",
         "午时", "未时", "申时", "酉时", "戌时", "亥时"]


def _parse_date(s):
    """'1220-01-15' -> datetime.date，失败返回 None。"""
    try:
        y, m, d = (int(x) for x in str(s).split("-"))
        return datetime.date(y, m, d)
    except (ValueError, TypeError):
        return None


def update_time(date=None, hour=None, advance_hours=None):
    """设置或推进游戏时间。date / hour 可直接设置；advance_hours 按时辰推进。"""
    data = state.load("基本信息", {})
    t = data.setdefault("时间", {})

    if advance_hours is not None:
        # 推进模式：从当前日期 + 时辰往前推
        try:
            n = int(advance_hours)
        except (TypeError, ValueError):
            return {"success": False, "error": f"advance_hours 必须为整数，收到 {advance_hours}"}
        if n < 0:
            return {"success": False, "error": "advance_hours 不能为负数"}

        cur_hour = t.get("时辰")
        cur_date = _parse_date(t.get("日期"))
        if cur_hour not in HOURS:
            return {"success": False, "error": f"当前时辰「{cur_hour}」不是十二时辰之一，无法推进"}
        if cur_date is None:
            return {"success": False, "error": f"当前日期「{t.get('日期')}」格式错误，无法推进"}

        total = HOURS.index(cur_hour) + n
        new_idx = total % 12
        days = total // 12
        new_date = cur_date + datetime.timedelta(days=days)
        t["日期"] = new_date.strftime("%Y-%m-%d")
        t["时辰"] = HOURS[new_idx]
    else:
        if date is None and hour is None:
            return {
                "success": False,
                "error": "必须提供 date、hour 或 advance_hours 中的至少一项",
            }
        if date is not None:
            d = _parse_date(date)
            if d is None:
                return {"success": False, "error": f"日期格式应为 YYYY-MM-DD，收到 {date}"}
            t["日期"] = d.strftime("%Y-%m-%d")
        if hour is not None:
            if hour not in HOURS:
                return {"success": False, "error": f"时辰必须是十二时辰之一，收到 {hour}"}
            t["时辰"] = hour

    state.save("基本信息", data)
    return {"success": True, "时间": {"日期": t.get("日期"), "时辰": t.get("时辰")}}


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
