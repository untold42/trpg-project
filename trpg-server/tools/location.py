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

import math

from tools.explore import record_position
from tools.map_query import (DEFAULT_REGION, bearing_name, city_context,
                             query_nearby, query_place)
from tools.state_manager import state

# 扬州地图有效范围（WGS84，略大于瓦片覆盖范围留缓冲）
LON_MIN, LON_MAX = 118.88, 119.96
LAT_MIN, LAT_MAX = 32.17, 32.69


def _distance_m(lat1, lon1, lat2, lon2):
    """两点近似距离（米，等距圆柱投影，与 map_query 一致）。"""
    mlat = 111132.95
    mlon = 111320.0 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot((lon2 - lon1) * mlon, (lat2 - lat1) * mlat)


def _time_hint(moved_m):
    """根据移动距离给出耗时提示（时辰粒度很粗，短距离不应推进时辰）。"""
    if moved_m is None:
        return ""
    if moved_m < 300:
        return "片刻——同一时辰内，无需 update_time"
    if moved_m < 1500:
        return "约一刻钟——同一时辰内，通常无需 update_time"
    if moved_m < 4000:
        return "半个时辰上下"
    return "一个时辰以上（较远，考虑拆分多步）"


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
    old_lon, old_lat = pos.get("经度"), pos.get("纬度")
    old_inside = pos.get("在城内")
    if (old_inside is None and isinstance(old_lon, (int, float))
            and isinstance(old_lat, (int, float))):
        old_inside = city_context(old_lon, old_lat).get("在城内")
    pos["经度"] = round(target_lon, 6)
    pos["纬度"] = round(target_lat, 6)
    pos["地点"] = resolved_name
    pos["区域"] = DEFAULT_REGION  # 所在城市/区域（之前从不写入，导致恒为旧值）
    ctx = city_context(target_lon, target_lat)  # 城内/城外 + 距城墙 + 最近城门
    if ctx:
        pos.update(ctx)
    state.save("基本信息", data)
    crossed_wall = (old_inside is not None and ctx.get("在城内") is not None
                    and old_inside != ctx["在城内"])

    # 移动距离（供主持人判断时间推进是否相称）+ 移动方位（硬事实）
    moved_m = None
    move_bearing = ""
    if isinstance(old_lon, (int, float)) and isinstance(old_lat, (int, float)):
        moved_m = round(_distance_m(old_lat, old_lon, target_lat, target_lon))
        move_bearing = bearing_name(old_lon, old_lat, target_lon, target_lat)

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

    # 名字回填：坐标移动时，用最近的有名地点作为「地点」（否则会存成坐标字符串，
    # 导致地图类型查不到、背景/音乐约束失效）。
    if not place_name:
        near1 = query_nearby(target_lon, target_lat, radius_km=0.15, limit=5)
        for x in near1.get("results", []):
            if x.get("name"):
                better = x["name"]
                if better != resolved_name:
                    data = state.load("基本信息", {})
                    data.setdefault("位置", {})["地点"] = better
                    state.save("基本信息", data)
                    resolved_name = better
                break

    return {
        "success": True,
        "位置": {
            "地点": resolved_name,
            "经度": round(target_lon, 6),
            "纬度": round(target_lat, 6),
            "移动方式": move_mode or "",
            "在城内": ctx.get("在城内"),
            "距城墙（米）": ctx.get("距城墙（米）"),
            "最近城门": ctx.get("最近城门"),
            "城区方位": ctx.get("城区方位"),
        },
        "移动距离（米）": moved_m,
        "移动方位": move_bearing,
        "耗时提示": _time_hint(moved_m),
        "城墙穿越": crossed_wall,
        "提示": "（本次移动穿过了城墙：玩家已进出城，叙述请写明经过城门/城墙）" if crossed_wall else "",
        "附近": nearby_names,
    }
