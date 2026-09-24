# -*- coding: utf-8 -*-
"""
movement.py
===========
探索移动的两个数值：

    - **轻功 → 步速**：前端用 `config()` 的参数算屏幕速度（经 `GET /state` 下发）；
    - **奔跑 → 精力**：只对奔跑「**超出步行的那部分距离**」扣精力（`drain_run`），
      不双重计费（时间流逝本身已在扣精力）。

参数热改：改 `trpg-server/配置/移动.json` 免重启。
"""

from __future__ import annotations

import json
from pathlib import Path

from tools.核心.state_manager import state

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "配置" / "移动.json"
_REQUIRED = ("基础步速", "轻功每点步速", "奔跑倍率", "奔跑耗精力每米")

_cache: tuple[int, dict] | None = None


def _validate(raw) -> dict:
    """校验并提取移动配置；策划数值只允许来自 `移动.json`。"""
    if not isinstance(raw, dict):
        raise ValueError("根节点必须是对象")
    missing = [key for key in _REQUIRED if key not in raw]
    if missing:
        raise ValueError(f"缺少字段：{'、'.join(missing)}")

    cfg = {}
    for key in _REQUIRED:
        value = raw[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{key} 必须是数字")
        cfg[key] = float(value)

    if cfg["基础步速"] <= 0:
        raise ValueError("基础步速必须大于 0")
    if cfg["轻功每点步速"] < 0:
        raise ValueError("轻功每点步速不能小于 0")
    if cfg["奔跑倍率"] <= 0:
        raise ValueError("奔跑倍率必须大于 0")
    if cfg["奔跑耗精力每米"] < 0:
        raise ValueError("奔跑耗精力每米不能小于 0")
    return cfg


def config() -> dict:
    """读取并校验 `移动.json`（唯一数值源，热改免重启）。

    配置缺失或损坏时不再退回另一套硬编码数值，以免策划修改悄悄失效。
    """
    global _cache
    try:
        mtime = CONFIG_PATH.stat().st_mtime_ns
        if _cache and _cache[0] == mtime:
            return dict(_cache[1])
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cfg = _validate(raw)
    except (OSError, json.JSONDecodeError, ValueError) as e:
        raise RuntimeError(f"移动配置无效：{CONFIG_PATH}：{e}") from e
    _cache = (mtime, cfg)
    return dict(cfg)


def run_cost(extra_meters: float) -> int:
    """奔跑「超出步行」的 extra_meters 米 → 应扣精力（四舍五入，≥0）。"""
    try:
        rate = float(config()["奔跑耗精力每米"])
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
