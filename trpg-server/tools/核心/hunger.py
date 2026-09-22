# -*- coding: utf-8 -*-
"""
hunger.py
=========
饥饿度：**0~100 数值**（100 = 饱足，0 = 濒饿），随游戏时间**缓慢下降**。

五挡位由数值派生（阈值 80 / 60 / 40 / 20）：

    >=80 饱足 ｜ >=60 正常 ｜ >=40 空腹 ｜ >=20 饥饿 ｜ <20 濒饿

- `饥饿`（数值）是**真相源**；`饥饿挡位`（字符串）是投影，由 `sync()` 回写 `状态.json`。
- 随时间扣减：`time_flow.pump()` / `sleep` 里按跨过的时辰调 `drain()`。
- 进食：工具 `modify_hunger`（正数增加）。
- 每时辰扣多少：以 `trpg-server/时间影响.json` 的 `每时辰饥饿` 为准（当前为 5；改文件即时生效）。
"""

from __future__ import annotations

from tools.核心.state_manager import state

#: 阈值（从高到低）→ 挡位名
LEVELS = ((80, "饱足"), (60, "正常"), (40, "空腹"), (20, "饥饿"), (-1, "濒饿"))

#: 旧挡位字符串 → 数值（迁移用，取该挡位中值）
_ALIAS = {"饱足": 90, "正常": 70, "空腹": 50, "饥饿": 30, "濒饿": 10}

#: 配置读取失败时的容错后备值；正常运行以 `时间影响.json.每时辰饥饿` 为准。
#: 与当前配置保持一致，避免配置暂时不可读时消耗量跳变。
DEFAULT_PER_SHICHEN = 5


def clamp(v) -> float:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 50.0
    return max(0.0, min(100.0, v))


def coerce(v) -> float:
    """数字原样（夹 0~100）；旧挡位字符串 → 中值；其它 → 50。"""
    if isinstance(v, bool):
        return 50.0
    if isinstance(v, (int, float)):
        return clamp(v)
    if isinstance(v, str):
        s = v.strip()
        if s in _ALIAS:
            return float(_ALIAS[s])
        try:
            return clamp(float(s))
        except ValueError:
            return 50.0
    return 50.0


def level_of(v) -> str:
    x = clamp(v)
    for lo, name in LEVELS:
        if x >= lo:
            return name
    return LEVELS[-1][1]


def _store(v) -> float:
    """存盘用的干净数值：整数就存整数。"""
    f = clamp(v)
    return int(f) if float(f).is_integer() else round(f, 1)


def sync() -> dict:
    """把 `状态.json` 的饥饿归一化为 0~100 数值，并写回派生的 `饥饿挡位`。"""
    data = state.load("状态", {}) or {}
    val = _store(coerce(data.get("饥饿", 50)))
    level = level_of(val)
    if data.get("饥饿") != val or data.get("饥饿挡位") != level:
        data["饥饿"] = val
        data["饥饿挡位"] = level
        try:
            state.save("状态", data)
        except OSError as e:      # 文件被占用：不抛，下次再试
            print(f"[hunger] 写盘失败：{e}")
    return data


def drain(indices: list) -> float:
    """按跨过的时辰扣饥饿；数值以 `时间影响.json.每时辰饥饿` 为准。返回理论扣除量。"""
    if not indices:
        return 0.0
    try:
        from tools.核心 import time_flow
        per = float(time_flow._config().get("每时辰饥饿", DEFAULT_PER_SHICHEN))
    except Exception:
        per = float(DEFAULT_PER_SHICHEN)
    if per <= 0:
        return 0.0
    data = sync()
    cur = coerce(data.get("饥饿", 50))
    new = max(0.0, cur - per * len(indices))
    if new != cur:
        data["饥饿"] = _store(new)
        data["饥饿挡位"] = level_of(new)
        try:
            state.save("状态", data)
        except OSError as e:
            print(f"[hunger] 扣饥饿写盘失败：{e}")
            return 0.0
    return per * len(indices)
