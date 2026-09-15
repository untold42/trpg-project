# -*- coding: utf-8 -*-
"""
time_weather.py
===============
游戏时间与天气，供 LLM function calling 调用。

    update_time:     推进 / 设置游戏时间——**转发给连续时钟**（tools/game_clock.py）
    update_weather:  设置天气（状况/温度/风力/描述）

时间规则（遵循 世界.md）：
    - 日期格式 YYYY-MM-DD，如 1220-01-15
    - 时辰必须是十二时辰：子丑寅卯辰巳午未申酉戌亥
    - 1 时辰 = 8 刻（1 刻 ≈ 15 分钟）

⚠️ 时间由 `tools/game_clock.clock` 统一裁决（连续流动 + 叙事跳时）。本模块不再自己
   维护时间字段，只把 LLM 的 `update_time` 调用转成对时钟的推进 / 设置；派生出的
   日期/时辰/刻 由时钟写回 `基本信息.json` 的「时间」字段。
"""

from tools.state_manager import state
# 常量从这里再导出，保持既有 `from tools.time_weather import SHICHEN/KE_CN` 可用
from tools.game_clock import (
    clock, SHICHEN, KE_PER_SHICHEN, KE_CN, SECONDS_PER_KE, _parse_date,  # noqa: F401
)


def update_time(date=None, shichen=None, ke=None, advance_shichen=None, advance_ke=None):
    """推进 / 设置游戏时间（转发给连续时钟）。

    - `advance_shichen` / `advance_ke`：从当前时间往前推进若干**时辰 / 刻**
      （8 刻 = 1 时辰，12 时辰 = 1 天，跨过子时进入新一天）；
    - `date` / `shichen` / `ke`：直接设置日期 / 时辰 / 刻（刻 0-7）。
    """
    if advance_shichen is not None or advance_ke is not None:
        n_ke = (advance_shichen or 0) * KE_PER_SHICHEN + (advance_ke or 0)
        if n_ke < 0:
            return {"success": False, "error": "推进量不能为负数"}
        c = clock.advance(n_ke * SECONDS_PER_KE)
        return {"success": True, "时间": c}

    if date is None and shichen is None and ke is None:
        return {
            "success": False,
            "error": "必须提供 date、shichen、ke 或 advance_shichen/advance_ke 中的至少一项",
        }
    if date is not None and _parse_date(date) is None:
        return {"success": False, "error": f"日期格式应为 YYYY-MM-DD，收到 {date}"}
    if shichen is not None and shichen not in SHICHEN:
        return {"success": False, "error": f"时辰必须是十二时辰之一，收到 {shichen}"}
    if ke is not None and (not isinstance(ke, int) or isinstance(ke, bool) or not (0 <= ke < KE_PER_SHICHEN)):
        return {"success": False, "error": f"刻必须是 0-{KE_PER_SHICHEN - 1} 的整数"}
    c = clock.set_civil(date=date, shichen=shichen, ke=ke)
    if c is None:
        return {"success": False, "error": "时间参数非法"}
    return {"success": True, "时间": c}


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
