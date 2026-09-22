# -*- coding: utf-8 -*-
"""
time_weather.py
===============
游戏时间与天气，供 LLM function calling 调用。

    advance_time:    推进游戏时间（N 刻 / N 时辰）——**转发给连续时钟**（tools/game_clock.py）
    update_time:     **直接设置**游戏时间（日期 / 时辰 / 刻）
    update_weather:  设置天气（状况/温度/风力/描述）

时间规则（遵循 世界.md）：
    - 日期格式 YYYY-MM-DD，如 1220-01-15
    - 时辰必须是十二时辰：子丑寅卯辰巳午未申酉戌亥
    - 1 时辰 = 8 刻（1 刻 ≈ 15 分钟）

⚠️ 时间由 `tools/game_clock.clock` 统一裁决（连续流动 + 叙事跳时）。本模块不再自己
   维护时间字段，只把 LLM 的调用转成对时钟的推进 / 设置；派生出的日期/时辰/刻 由时钟
   写回 `基本信息.json` 的「时间」字段。

职责分离（工具单一职责）：
    - **要推进** → `advance_time(ke=… / shichen=…)`
    - **要设到某时刻** → `update_time(date=… / shichen=… / ke=…)`
"""

from tools.核心 import weather_system
from tools.核心.state_manager import state
# 常量从这里再导出，保持既有 `from tools.核心.time_weather import SHICHEN/KE_CN` 可用
from tools.核心.game_clock import (
    clock, SHICHEN, KE_PER_SHICHEN, KE_CN, SECONDS_PER_KE, _parse_date,  # noqa: F401
)

#: 本轮 LLM 是否已自行调用过时间工具（advance_time / update_time）。
#: 供 use_facility 判重：LLM 已推过 → 后端不再按「耗时刻」重复推进。
_TIME_TOOL_USED = False


def reset_turn() -> None:
    """每轮 /action 开始时由后端调用。"""
    global _TIME_TOOL_USED
    _TIME_TOOL_USED = False


def time_tool_used() -> bool:
    """本轮 LLM 是否已调用过时间工具。"""
    return _TIME_TOOL_USED


def _mark_time_tool_used() -> None:
    global _TIME_TOOL_USED
    _TIME_TOOL_USED = True


def advance_time(ke=None, shichen=None):
    """推进游戏时间：`ke` 刻 + `shichen` 时辰（可只给其一，或二者叠加）。

    - 8 刻 = 1 时辰，12 时辰 = 1 天（跨子时进新一天）；
    - 推进量必须为正（至少 1 刻）；
    - 只做「推进」；要直接设到某时刻请用 `update_time`。
    """
    if isinstance(ke, bool) or isinstance(shichen, bool):
        return {"success": False, "error": "ke / shichen 必须是整数"}
    try:
        n_ke = int(shichen or 0) * KE_PER_SHICHEN + int(ke or 0)
    except (TypeError, ValueError):
        return {"success": False, "error": "ke / shichen 必须是整数"}
    if n_ke <= 0:
        return {"success": False,
                "error": "推进量必须为正（ke 刻 / shichen 时辰，至少 1 刻）"}
    c = clock.advance(n_ke * SECONDS_PER_KE)
    _mark_time_tool_used()
    return {"success": True, "推进": {"刻": n_ke}, "时间": c}


def update_time(date=None, shichen=None, ke=None):
    """**直接设置**游戏时间（日期 / 时辰 / 刻）。要推进时间请用 `advance_time`。

    - `date`：YYYY-MM-DD；`shichen`：十二时辰之一；`ke`：0-7；
    - 不传的字段保持原样。
    """
    if date is None and shichen is None and ke is None:
        return {
            "success": False,
            "error": "必须提供 date、shichen、ke 中的至少一项（要推进时间请用 advance_time）",
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
    _mark_time_tool_used()
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

    weather_system.sync_effect(w)
    state.save("基本信息", data)
    return {"success": True, "天气": w}
