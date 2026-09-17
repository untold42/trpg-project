# -*- coding: utf-8 -*-
"""
location.py
===========
玩家位置更新工具 update_location（供 LLM function calling 调用）。

移动玩家：可用地名（后端查空间库解析坐标）或直接给经纬度。
    1. 解析目标坐标（地名 → map_spatial_<map_id>.db 查询）
    2. 范围校验（防飞出当前地图）
    3. 写 游戏数据/基本信息.json 的“位置”字段
    4. 调用 explore.record_position 记足迹（自动解锁附近 POI）
    5. 查“附近有什么”返回给 LLM，辅助叙事
"""

import math

from tools.explore import record_position
from tools.map_query import (bearing_name, city_context, current_frame,
                             current_region, map_at, region_of, query_nearby,
                             query_place)
from tools.state_manager import state


def _map_ctx():
    """当前地图的 (画框, 区域名)——每次移动现取，支持运行时切图。"""
    try:
        return current_frame(), current_region()
    except Exception:
        return None, "扬州"


def current_region_of(map_id: str) -> str:
    """指定地图的中文区域名（拿不到就回退到 map_id）。"""
    try:
        return region_of(map_id)
    except Exception:
        return map_id


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

    # 2. 范围校验：**任一**已生成地图的画框内都放行。
    #    跨城移动 = 坐标移到另一张图里 → 游戏城市自动跟着走（地图跟着人走）。
    frame, region = _map_ctx()
    in_cur = (bool(frame) and frame[0] <= target_lon <= frame[2]
              and frame[1] <= target_lat <= frame[3])
    crossed_map = None
    if not in_cur:
        tgt = map_at(target_lon, target_lat)
        if tgt is None:
            return {
                "success": False,
                "error": (f"目标坐标({target_lon:.4f}, {target_lat:.4f})"
                          f"不在任何已生成的地图范围内（当前：{region}）"),
            }
        # 步行/探索**不可能**跨城。前端光标异常时（如地图相机被夹到另一座城的边界）
        # 会把坐标弹到几百公里外，不加这道闸玩家就会被凭空搬走。
        if (move_mode or "").strip() in ("探索", "步行", "走", "行走"):
            return {
                "success": False,
                "error": (f"步行无法跨城：目标({target_lon:.4f}, {target_lat:.4f})在{current_region_of(tgt)}，"
                          f"当前在{region}。跨城请用交通工具/叙事（move_mode 传「渡船」「骑马」等）"),
            }
        crossed_map = tgt
        region = current_region_of(tgt)

    # 3. 写 基本信息.json 的“位置”字段（Python 读改写，不靠 LLM 手写 JSON）
    data = state.load("基本信息", {})
    pos = data.setdefault("位置", {})
    old_lon, old_lat = pos.get("经度"), pos.get("纬度")
    old_inside = pos.get("在城内")
    pos["经度"] = round(target_lon, 6)
    pos["纬度"] = round(target_lat, 6)
    pos["地点"] = resolved_name
    pos["区域"] = region  # 所在城市/区域（之前从不写入，导致恒为旧值）
    # **先落盘**：下面 city_context() 内部按当前坐标选库，不落盘会拿到旧城的库
    state.save("基本信息", data)
    ctx = city_context(target_lon, target_lat)  # 城内/城外 + 距城墙 + 最近城门
    # 城池判定字段是**整组**更新的：ctx 没给的键要清掉，
    # 否则「最近城门」会一直留着上一座城的残值（实测出现过）。
    for k in ("在城内", "距城墙（米）", "最近城门", "城区方位"):
        pos.pop(k, None)
    if ctx:
        pos.update(ctx)
        state.save("基本信息", data)
    crossed_wall = (old_inside is not None and ctx.get("在城内") is not None
                    and old_inside != ctx["在城内"])
    if crossed_map:
        crossed_wall = False  # 整座城都换了，不再谈“穿城墙”

    # 移动距离（供主持人判断时间推进是否相称）+ 移动方位（硬事实）
    moved_m = None
    move_bearing = ""
    if isinstance(old_lon, (int, float)) and isinstance(old_lat, (int, float)):
        moved_m = round(_distance_m(old_lat, old_lon, target_lat, target_lon))
        move_bearing = bearing_name(old_lon, old_lat, target_lon, target_lat)

    # 4. 记足迹：玩家一到新地方，附近 POI 立即解锁（探索迷雾联动）
    #    跨地图移动是"另一座城"，旧城足迹在新图上毫无意义且会污染迷雾 → 先清空。
    if crossed_map:
        try:
            state.save("足迹", {"points": []})
        except Exception:
            pass
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
        "地图切换": (f"已离开原地图，进入{region}" if crossed_map else ""),
        "提示": "（本次移动穿过了城墙：玩家已进出城，叙述请写明经过城门/城墙）" if crossed_wall else "",
        "附近": nearby_names,
    }
