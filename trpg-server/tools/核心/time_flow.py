# -*- coding: utf-8 -*-
"""
time_flow.py
============
「时间流逝 → 世界与数值」的落实层（时钟只管"时间"，这里管"后果"）。

- `pump()`（在 `/clock`、`/state`、`/action` 时调用）：
    - 跨**时辰** → 精力随昼夜流逝（**熬夜的夜时辰扣得更狠**）；
    - 跨**日**   → 切当天天气 + 触发世界推演 worker。
- `rest(时辰)`（工具 `sleep`）：
    - 先 `pump()` 结算清醒时段 → 推进时钟 → 把睡眠时段按**恢复**而非消耗结算。

调参：`trpg-server/时间影响.json`（缺失/损坏用代码默认；改文件即时生效）。
"""

from __future__ import annotations

import json
from pathlib import Path

from tools.核心.game_clock import clock, SHICHEN, SECONDS_PER_SHICHEN
from tools.核心.state_manager import state
from tools.核心 import derived, hunger

CONFIG_FILE = Path(__file__).resolve().parent.parent.parent / "时间影响.json"

DEFAULTS = {
    "每时辰精力": {"昼": 3, "夜": 9},
    #: 每睡 1 时辰恢复「精力上限 ÷ 睡眠回满时辰」——随养成提高的上限**自动变强**
    "睡眠回满时辰": 4,
    "夜时辰": ["子时", "丑时", "寅时"],
}

_config_cache: dict = {}


def _config() -> dict:
    """读 时间影响.json（按 mtime 缓存；缺失/损坏用默认）。"""
    try:
        m = CONFIG_FILE.stat().st_mtime
    except OSError:
        return DEFAULTS
    if _config_cache.get("m") == m:
        return _config_cache["v"]
    cfg = dict(DEFAULTS)
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            cfg.update(raw)
    except (OSError, json.JSONDecodeError):
        pass
    _config_cache["m"], _config_cache["v"] = m, cfg
    return cfg


def _tp_bounds(data: dict):
    cur = int(data.get("精力值", 0) or 0)
    cap = int(data.get("精力上限", cur) or cur)
    if cap <= 0:
        cap = cur
    return cur, cap


def _drain_tp(indices: list) -> int:
    """按跨过的时辰扣精力（夜时辰更狠）。返回扣除总量。"""
    if not indices:
        return 0
    cfg = _config()
    night = set(cfg.get("夜时辰") or [])
    per = cfg.get("每时辰精力") or {}
    p_day = int(per.get("昼", DEFAULTS["每时辰精力"]["昼"]))
    p_night = int(per.get("夜", DEFAULTS["每时辰精力"]["夜"]))
    cost = sum(p_night if SHICHEN[g % 12] in night else p_day for g in indices)
    if cost <= 0:
        return 0
    data = state.load("状态", {}) or {}
    cur, _cap = _tp_bounds(data)
    new = max(0, cur - cost)
    if new != cur:
        data["精力值"] = new
        try:
            state.save("状态", data)
        except OSError as e:      # 文件被占用：下次 pump 再试
            print(f"[time_flow] 扣精力写盘失败：{e}")
    return cost


def _sleep_per_shichen(cap: int) -> float:
    """每睡 1 时辰恢复的精力 = **精力上限 ÷ 睡眠回满时辰**。

    这样养成把上限提高后，睡眠恢复量同步变强（不会相对变弱）。
    兼容旧的绝对值配置 `睡眠每时辰恢复`（若存在则优先）。
    """
    cfg = _config()
    abs_v = cfg.get("睡眠每时辰恢复")
    if abs_v is not None:
        try:
            return max(0.0, float(abs_v))
        except (TypeError, ValueError):
            pass
    try:
        full = float(cfg.get("睡眠回满时辰", DEFAULTS["睡眠回满时辰"]))
    except (TypeError, ValueError):
        full = float(DEFAULTS["睡眠回满时辰"])
    if full <= 0:
        full = float(DEFAULTS["睡眠回满时辰"])
    return max(0.0, cap) / full


def _recover_tp(n: int) -> int:
    """睡眠恢复精力（按精力上限的比例）。返回回复量。"""
    if n <= 0:
        return 0
    data = state.load("状态", {}) or {}
    cur, cap = _tp_bounds(data)
    per = _sleep_per_shichen(cap)
    if per <= 0:
        return 0
    new = max(0, min(cap, int(round(cur + per * n))))   # 夹在 [0, 上限]
    if new != cur:
        data["精力值"] = new
        try:
            state.save("状态", data)
        except OSError as e:
            print(f"[time_flow] 睡眠回精力写盘失败：{e}")
            return 0
    return new - cur


def _on_new_day(date: str):
    """跨日联动：切当天天气 + 触发世界推演。失败不影响玩（off-screen）。"""
    try:
        from tools.核心 import weather_system
        weather_system.get_weather(date=date)
    except Exception as e:
        print(f"[time_flow] 天气更新失败：{e}")
    try:
        from tools.小模型 import world_worker
        world_worker.on_turn_end()
    except Exception as e:
        print(f"[time_flow] 世界推演入队失败：{e}")


def pump() -> dict:
    """把时钟自上次以来跨过的时辰 / 日，落实为数值与联动。

    返回时钟给出的事件（`{days, shichen, shichen_indices, date}`）。
    """
    clock.sync_state()          # 先把派生时刻写回 基本信息（天气/推演要读日期）
    derived.sync()              # 上限对齐属性：体力→生命上限、內力→精力上限
    ev = clock.take_crossings()
    if ev["shichen_indices"]:
        _drain_tp(ev["shichen_indices"])
        hunger.drain(ev["shichen_indices"])   # 饥饿随时间缓慢下降
    if ev["days"] > 0:
        _on_new_day(ev["date"])
    return ev


def rest(shichen: int = 4) -> dict:
    """睡觉：先结算清醒时段 → 推进 N 时辰 → 睡眠时段按**恢复**结算。"""
    try:
        n = int(shichen)
    except (TypeError, ValueError):
        n = 4
    n = max(1, min(n, 12))
    pump()                                   # 先结算清醒时段（含熬夜扣精力）
    clock.advance(n * SECONDS_PER_SHICHEN)   # 睡过去
    ev = clock.take_crossings()              # 睡过的时辰不再按清醒扣
    hunger.drain(ev["shichen_indices"])      # 但饥饿照掉（睡觉也会饿）
    gain = _recover_tp(ev["shichen"] or n)
    if ev["days"] > 0:
        _on_new_day(ev["date"])
    data = state.load("状态", {}) or {}
    return {
        "success": True,
        "睡了": f"{n} 时辰（约 {n * 2} 小时）",
        "时间": clock.civil(),
        "精力": data.get("精力值"),
        "恢复": gain,
    }
