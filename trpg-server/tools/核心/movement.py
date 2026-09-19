# -*- coding: utf-8 -*-
"""
movement.py
===========
探索移动的两个数值：

    - **轻功 → 步速**：前端用 `config()` 的参数算屏幕速度（经 `GET /state` 下发）；
    - **奔跑 → 精力**：只对奔跑「**超出步行的那部分距离**」扣精力（`drain_run`），
      不双重计费（时间流逝本身已在扣精力）。

参数热改：改 `trpg-server/移动.json` 免重启。
"""

from __future__ import annotations

import json
from pathlib import Path

from tools.核心.state_manager import state

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "移动.json"

_DEFAULTS = {
    "基础步速": 2.2,          # 米 / 游戏秒（轻功 0 时）
    "轻功每点步速": 0.005,     # 每 1 点轻功增加的基础步速比例
    "奔跑倍率": 2.6,          # 按住 Shift
    "奔跑耗精力每米": 0.006,   # 「超出步行」的每米扣精力
}

_cache: tuple[float, dict] | None = None


def config() -> dict:
    """读 `移动.json`（热改免重启）；失败用默认值。"""
    global _cache
    try:
        mtime = CONFIG_PATH.stat().st_mtime
    except OSError:
        return dict(_DEFAULTS)
    if _cache and _cache[0] == mtime:
        return _cache[1]
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(_DEFAULTS)
    if not isinstance(raw, dict):
        return dict(_DEFAULTS)
    cfg = {k: raw.get(k, v) for k, v in _DEFAULTS.items()}
    _cache = (mtime, cfg)
    return cfg


def run_cost(extra_meters: float) -> int:
    """奔跑「超出步行」的 extra_meters 米 → 应扣精力（四舍五入，≥0）。"""
    try:
        rate = float(config().get("奔跑耗精力每米", _DEFAULTS["奔跑耗精力每米"]))
        meters = float(extra_meters or 0)
    except (TypeError, ValueError):
        return 0
    if meters <= 0 or rate <= 0:
        return 0
    return int(round(meters * rate))


def drain_run(extra_meters: float) -> dict:
    """按奔跑额外距离扣精力（扣到 0 为止，不负债）。返回扣除量与当前精力。"""
    cost = run_cost(extra_meters)
    data = state.load("状态", {}) or {}
    cur = int(data.get("精力值", 0) or 0)
    if cost <= 0:
        return {"success": True, "扣精力": 0, "精力值": cur, "精力上限": data.get("精力上限")}
    new = max(0, cur - cost)
    data["精力值"] = new
    try:
        state.save("状态", data)
    except OSError as e:
        return {"success": False, "error": str(e), "扣精力": 0, "精力值": cur}
    return {"success": True, "扣精力": cur - new, "精力值": new, "精力上限": data.get("精力上限")}
