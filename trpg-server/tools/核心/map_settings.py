# -*- coding: utf-8 -*-
"""
map_settings.py
===============
当前**地图**（城市）设置，存 `游戏数据/地图设置.json`。

**为什么需要它**
地图资产已按城市分目录（`public/tiles/<map_id>/`、`public/data/<map_id>/`、
`db/map_spatial_<map_id>.db`）。后端查地图（`tools/map_query.py`）必须知道当前是哪张图，
否则会去查另一座城的库。

**谁改它**
前端主菜单「环境设定 → 地图」调 `POST /map` 写这里；`TRPG_MAP` 环境变量只当**首次默认值**。

**顺带好处**
它在 `游戏数据/` 下，会被 `engine.snapshot_state()` 的「状态现拼」自动纳入每轮 LLM 调用 ——
主持人由此知道「当前在扬州还是岳阳」。
"""

import os

from tools.核心.state_manager import state

#: 环境变量只作首次默认（没有 地图设置.json 时）
_ENV_DEFAULT = os.environ.get("TRPG_MAP", "yangzhou")

#: 读不到 trpg-map/城市.py 时的兜底
_FALLBACK = {"yangzhou": "扬州", "yueyang": "岳阳"}

_CACHE = None


def _project_dir() -> str:
    """trpg-project/（本文件在 trpg-server/tools/ 下）。"""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _cities() -> dict:
    """map_id -> 城市中文名（真相源：trpg-map/城市.py）。"""
    import sys
    p = os.path.join(_project_dir(), "trpg-map")
    if p not in sys.path:
        sys.path.insert(0, p)
    try:
        from 城市 import CITIES, map_id as _mid  # noqa: E402
        return {_mid(cn): cn for cn in CITIES}
    except Exception:
        return dict(_FALLBACK)


def available_maps() -> list:
    """可用地图：`trpg-map/数据/<城市>_南宋世界.json` 存在的才算（结果缓存）。

    每项：{id, name, frame}；frame = [min_lon, min_lat, max_lon, max_lat]，
    前端用它做 maxBounds（与 PBF 裁剪 / 瓦片取景同一份定义）。
    """
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    cities = _cities()
    data_dir = os.path.join(_project_dir(), "trpg-map", "数据")
    maps = []
    for mid, cn in cities.items():
        if not os.path.isfile(os.path.join(data_dir, f"{cn}_南宋世界.json")):
            continue
        fr = _frame_of(mid)
        maps.append({"id": mid, "name": cn,
                     "frame": list(fr) if fr else None})
    if not maps:
        maps = [{"id": "yangzhou", "name": "扬州", "frame": None}]
    maps.sort(key=lambda m: (m["id"] != "yangzhou", m["id"]))
    _CACHE = maps
    return maps


def _frame_of(map_id: str):
    """该地图的画框 (min_lon, min_lat, max_lon, max_lat)；取不到返回 None。"""
    import sys
    p = os.path.join(_project_dir(), "trpg-map")
    if p not in sys.path:
        sys.path.insert(0, p)
    try:
        from 城市 import CITIES, frame_bbox, map_id as _mid  # noqa: E402
        for cn in CITIES:
            if _mid(cn) == map_id:
                return frame_bbox(cn)
    except Exception:
        pass
    return None


def _player_lonlat():
    """玩家当前经纬度 (lon, lat)；没位置返回 None。"""
    try:
        pos = (state.load("基本信息", {}) or {}).get("位置") or {}
        lon, lat = pos.get("经度"), pos.get("纬度")
        if isinstance(lon, (int, float)) and isinstance(lat, (int, float)):
            return float(lon), float(lat)
    except Exception:
        pass
    return None


def map_at(lon: float, lat: float):
    """坐标落在哪张图的画框里；都不在返回 None。"""
    for m in available_maps():
        fr = _frame_of(m["id"])
        if fr and fr[0] <= lon <= fr[2] and fr[1] <= lat <= fr[3]:
            return m["id"]
    return None


def get_map() -> str:
    """当前**游戏**地图（也就是玩家所在的城市）。

    **地图跟着人走**：先看玩家坐标落在哪张图的画框里——看别的地图的瓦片
    （纯前端行为）不会改变这个值。玩家不在任何图内时才用下面两项兑底：
        地图设置.json（上次选择） > TRPG_MAP 环境变量 > 第一张可用图
    """
    ids = [m["id"] for m in available_maps()]
    p = _player_lonlat()
    if p:
        here = map_at(p[0], p[1])
        if here:
            return here
    data = state.load("地图设置", {})
    cur = data.get("地图") if isinstance(data, dict) else None
    if cur in ids:
        return cur
    return _ENV_DEFAULT if _ENV_DEFAULT in ids else ids[0]


def get_settings() -> dict:
    maps = available_maps()
    cur = get_map()
    return {
        "current": cur,
        "当前": next((m["name"] for m in maps if m["id"] == cur), cur),
        "maps": maps,
    }


def set_map(map_id: str) -> dict:
    """记住「上次看/玩的图」（写 游戏数据/地图设置.json）。

    注意：这**只是兑底**——只要玩家坐标落在某张图的画框里，`get_map()` 就听坐标的。
    所以这个接口**不会移动玩家、不会清足迹**，看哪张地图都是零副作用。
    """
    ids = {m["id"] for m in available_maps()}
    map_id = (map_id or "").strip()
    if map_id not in ids:
        return {"success": False,
                "error": f"未知地图「{map_id}」；可选：{'、'.join(sorted(ids))}"}
    data = state.load("地图设置", {})
    if not isinstance(data, dict):
        data = {}
    data["地图"] = map_id
    data["说明"] = ("上次查看/选择的地图（仅兑底：玩家坐标在哪张图内就以哪张为准）。"
                    "地图资产（瓦片/点击层/碰撞层/空间库）按城市分目录存放。")
    state.save("地图设置", data)
    return {"success": True, **get_settings()}
