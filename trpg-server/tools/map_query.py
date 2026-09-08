# -*- coding: utf-8 -*-
"""
map_query.py
============
南宋扬州地图空间查询工具（供 LLM function calling 调用）。

读取 trpg-map/draw_tiles/db/map_spatial.db（R-tree + 完整几何），提供：
    query_nearby(lon, lat, radius_km, kind, category, limit)  精确范围查询
    query_place(name, kind, category, limit)                   名称/类别查找
    list_map_kinds()                                            列出所有地点类别及数量

坐标均为 WGS84：经度约 118.9~119.96，纬度约 32.17~32.68。
"""

import json
import math
import os
import sqlite3

import shapely.geometry as sg
from shapely.ops import transform

# trpg-server 的上一级是 trpg-project；空间库在 trpg-map/draw_tiles/db/ 下
SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_FILE = os.path.abspath(os.path.join(
    SERVER_DIR, "..", "trpg-map", "draw_tiles", "db", "map_spatial.db"))
DEFAULT_MAP = "yangzhou"

M_PER_DEG_LAT = 111132.95
M_PER_DEG_LON0 = 111320.0


def _connect():
    if not os.path.exists(DB_FILE):
        raise FileNotFoundError(f"找不到空间数据库：{DB_FILE}")
    return sqlite3.connect(DB_FILE)


def _shape(gtype, coords_txt):
    try:
        coords = json.loads(coords_txt)
        return sg.shape({"type": gtype, "coordinates": coords})
    except Exception:
        return None


def _reppoint(geom):
    """要素的代表点（点=自身；线=中点；面=内部代表点）。"""
    if geom is None or geom.is_empty:
        return None
    if geom.geom_type == "Point":
        return (round(geom.x, 6), round(geom.y, 6))
    if geom.geom_type in ("LineString", "MultiLineString"):
        if geom.length == 0:
            return None
        p = geom.interpolate(geom.length / 2)
        return (round(p.x, 6), round(p.y, 6))
    p = geom.representative_point()
    return (round(p.x, 6), round(p.y, 6))


def query_nearby(lon, lat, radius_km=1.0, kind=None, category=None, limit=20):
    """查询某坐标附近的地点（点/线/面都按最近距离精确计算）。"""
    conn = _connect()
    cur = conn.cursor()

    m_per_deg_lon = M_PER_DEG_LON0 * math.cos(math.radians(lat))
    dy = radius_km * 1050 / M_PER_DEG_LAT
    dx = radius_km * 1050 / m_per_deg_lon

    sql = """
        SELECT f.name, f.ancient_kind, f.category, f.geometry_type,
               f.coords, f.name_modern
        FROM features f
        JOIN features_rtree r ON f.fid = r.fid
        WHERE f.map_id = ?
          AND r.maxx >= ? AND r.minx <= ?
          AND r.maxy >= ? AND r.miny <= ?
    """
    params = [DEFAULT_MAP, lon - dx, lon + dx, lat - dy, lat + dy]
    if kind:
        sql += " AND f.ancient_kind = ?"
        params.append(kind)
    else:
        # 默认排除民居（背景建筑，不具导航意义），显式 kind=民居 仍可查
        sql += " AND (f.ancient_kind IS NULL OR f.ancient_kind != '民居')"
    if category:
        sql += " AND f.category = ?"
        params.append(category)

    def to_m(x, y):
        return (x * m_per_deg_lon, y * M_PER_DEG_LAT)

    pt_m = sg.Point(lon * m_per_deg_lon, lat * M_PER_DEG_LAT)

    results = []
    for name, akind, cat, gtype, coords_txt, name_modern in cur.execute(sql, params):
        geom = _shape(gtype, coords_txt)
        if geom is None:
            continue
        d_m = transform(to_m, geom).distance(pt_m)
        if d_m > radius_km * 1000:
            continue
        rp = _reppoint(geom)
        results.append({
            "name": name,
            "kind": akind,
            "category": cat,
            "geometry_type": gtype,
            "lon": rp[0] if rp else None,
            "lat": rp[1] if rp else None,
            "distance_km": round(d_m / 1000.0, 3),
            "name_modern": name_modern,
        })
    conn.close()

    results.sort(key=lambda x: x["distance_km"])
    results = results[:limit]
    return {
        "success": True,
        "count": len(results),
        "center": {"lon": lon, "lat": lat, "radius_km": radius_km},
        "results": results,
    }


def query_place(name=None, kind=None, category=None, limit=20):
    """按名称（模糊）或类别查地点，返回其坐标与属性。"""
    conn = _connect()
    cur = conn.cursor()

    sql = """
        SELECT f.name, f.ancient_kind, f.category, f.geometry_type,
               f.coords, f.name_modern
        FROM features f
        WHERE f.map_id = ?
    """
    params = [DEFAULT_MAP]
    if name:
        sql += " AND f.name LIKE ?"
        params.append(f"%{name}%")
    if kind:
        sql += " AND f.ancient_kind = ?"
        params.append(kind)
    elif not name:
        # 默认排除民居（背景建筑，不具导航意义）
        sql += " AND (f.ancient_kind IS NULL OR f.ancient_kind != '民居')"
    if category:
        sql += " AND f.category = ?"
        params.append(category)
    sql += " LIMIT ?"
    params.append(limit)

    results = []
    for name2, akind, cat, gtype, coords_txt, name_modern in cur.execute(sql, params):
        geom = _shape(gtype, coords_txt)
        rp = _reppoint(geom)
        results.append({
            "name": name2,
            "kind": akind,
            "category": cat,
            "geometry_type": gtype,
            "lon": rp[0] if rp else None,
            "lat": rp[1] if rp else None,
            "name_modern": name_modern,
        })
    conn.close()

    return {"success": True, "count": len(results), "results": results}


def list_map_kinds(limit=200):
    """列出地图上所有地点类别（ancient_kind）及数量。"""
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT ancient_kind, COUNT(*) AS n
        FROM features
        WHERE map_id = ? AND ancient_kind IS NOT NULL AND ancient_kind != ''
        GROUP BY ancient_kind
        ORDER BY n DESC
        LIMIT ?
        """,
        [DEFAULT_MAP, limit],
    )
    rows = cur.fetchall()
    conn.close()
    return {
        "success": True,
        "count": len(rows),
        "kinds": [{"kind": k, "count": n} for k, n in rows],
    }
