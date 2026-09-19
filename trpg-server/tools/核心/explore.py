# -*- coding: utf-8 -*-
"""
explore.py
==========
探索（迷雾）机制：维护“玩家到过的足迹”集合。

前端打开地图时调用 /explored：
    1. 读 游戏数据/基本信息.json 里的玩家当前经纬度；
    2. 若与已有足迹距离 > 最小间距，则把当前位置追加进 足迹.json；
    3. 返回 玩家位置 + 足迹列表 + 解锁半径。

前端据此只显示「落在任一脚迹点 radius_km 半径内」的 POI，
没去过的地方不可见、不可点。
"""

import math

from tools.核心.state_manager import state

# 解锁半径（公里）：玩家到过某点后，该点周围多少公里内的 POI 可见
DEFAULT_RADIUS_KM = 0.5
# 两个足迹点至少相隔多少公里才值得单独记录（避免原地重开刷一堆重复点）
MIN_STEP_KM = 0.02

# 扬州纬度下，1 经度 ≈ 96 km、1 纬度 ≈ 111 km（足够近似）
KM_PER_DEG_LON = 96.0
KM_PER_DEG_LAT = 111.0


def _dist_km(lon1, lat1, lon2, lat2):
    dx = (lon2 - lon1) * KM_PER_DEG_LON
    dy = (lat2 - lat1) * KM_PER_DEG_LAT
    return math.hypot(dx, dy)


def read_player_position():
    """从 基本信息.json 读玩家当前坐标。"""
    data = state.load("基本信息", {})
    pos = data.get("位置", {}) or {}
    return {
        "lon": pos.get("经度"),
        "lat": pos.get("纬度"),
        "地点": pos.get("地点"),
        "区域": pos.get("区域"),
    }


def load_footprints():
    """返回 (足迹点列表, 解锁半径)。"""
    data = state.load("足迹", {})
    points = data.get("points") or []
    radius = data.get("radius_km", DEFAULT_RADIUS_KM)
    return points, radius


def record_position(lon, lat, place=None):
    """把当前位置追加进足迹（若与已有足迹过近则跳过）。返回最新足迹与半径。"""
    points, radius = load_footprints()
    if lon is None or lat is None:
        return points, radius
    for p in points:
        if _dist_km(lon, lat, p.get("lon"), p.get("lat")) < MIN_STEP_KM:
            return points, radius
    points.append({
        "lon": round(lon, 6),
        "lat": round(lat, 6),
        "地点": place or "",
    })
    state.save("足迹", {"points": points, "radius_km": radius})
    return points, radius
