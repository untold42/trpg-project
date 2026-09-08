# -*- coding: utf-8 -*-
"""
location.py
===========
玩家位置更新工具 update_location（供 LLM function calling 调用）。

移动玩家：可用地名（后端查空间库解析坐标）或直接给经纬度。
    1. 解析目标坐标（地名 → map_spatial.db 查询）
    2. 范围校验（防飞出扬州地图）
    3. 写 游戏数据/基本信息.json 的“位置”字段
    4. 调用 explore.record_position 记足迹（自动解锁附近 POI）
    5. 查“附近有什么”返回给 LLM，辅助叙事
"""

from tools.explore import record_position
from tools.map_query import query_place, query_nearby
from tools.state_manager import state

# 扬州地图有效范围（WGS84，略大于瓦片覆盖范围留缓冲）
LON_MIN, LON_MAX = 118.88, 119.96
LAT_MIN, LAT_MAX = 32.17, 32.69


def update_location(place_name=None, lon=None, lat=None, move_mode=None):
    """移动玩家位置。place_name 与 (lon, lat) 至少给其一。"""
    target_lon = None
    target_lat = None
    resolved_name = None

    # 1. 解析目标坐标
    if lon is not None and lat is not None:
        try:
            target_lon = float(lon)
            target_lat = float(lat)
        except (TypeError, ValueError):
            return {
                "success": False,
                "error": f"经纬度格式错误：lon={lon}, lat={lat}",
            }
        resolved_name = place_name or f"({target_lon:.4f}, {target_lat:.4f})"
    elif place_name:
        res = query_place(name=place_name, limit=1)
        results = res.get("results", []) if isinstance(res, dict) else []
        if not results:
            return {
                "success": False,
                "error": f"地图上找不到「{place_name}」，请换个地名，或直接给 lon/lat 坐标",
            }
        r = results[0]
        target_lon = r.get("lon")
        target_lat = r.get("lat")
        resolved_name = r.get("name") or place_name
        if target_lon is None or target_lat is None:
            return {
                "success": False,
                "error": f"「{place_name}」无法定位到坐标",
            }
    else:
        return {
            "success": False,
            "error": "必须提供 place_name（地名）或 lon+lat（经纬度）",
        }

    # 2. 范围校验
    if not (LON_MIN <= target_lon <= LON_MAX and LAT_MIN <= target_lat <= LAT_MAX):
        return {
            "success": False,
            "error": f"目标坐标({target_lon:.4f}, {target_lat:.4f})超出扬州地图范围",
        }

    # 3. 写 基本信息.json 的“位置”字段（Python 读改写，不靠 LLM 手写 JSON）
    data = state.load("基本信息", {})
    pos = data.setdefault("位置", {})
    pos["经度"] = round(target_lon, 6)
    pos["纬度"] = round(target_lat, 6)
    pos["地点"] = resolved_name
    state.save("基本信息", data)

    # 4. 记足迹：玩家一到新地方，附近 POI 立即解锁（探索迷雾联动）
    record_position(target_lon, target_lat, resolved_name)

    # 5. 附近有什么，辅助 LLM 叙事
    nearby = query_nearby(target_lon, target_lat, radius_km=0.5, limit=8)
    nearby_names = []
    for x in nearby.get("results", []):
        name = x.get("name")
        if not name:
            continue
        kind = x.get("kind") or x.get("category") or ""
        nearby_names.append(f"{name}({kind})" if kind else name)

    return {
        "success": True,
        "位置": {
            "地点": resolved_name,
            "经度": round(target_lon, 6),
            "纬度": round(target_lat, 6),
            "移动方式": move_mode or "",
        },
        "附近": nearby_names,
    }
