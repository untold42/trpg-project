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
from shapely.ops import nearest_points, transform

# trpg-server 的上一级是 trpg-project；空间库在 trpg-map/draw_tiles/db/ 下
SERVER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_FILE = os.path.abspath(os.path.join(
    SERVER_DIR, "..", "trpg-map", "draw_tiles", "db", "map_spatial.db"))
DEFAULT_MAP = "yangzhou"
#: 该地图对应的「区域」名（写入 基本信息.位置.区域；天气分区 / 世界推演用）
DEFAULT_REGION = "扬州"

M_PER_DEG_LAT = 111132.95
M_PER_DEG_LON0 = 111320.0


def _connect():
    if not os.path.exists(DB_FILE):
        raise FileNotFoundError(f"找不到空间数据库：{DB_FILE}")
    conn = sqlite3.connect(DB_FILE)
    _ensure_place_schema(conn)
    return conn


_SCHEMA_READY = False


def _ensure_place_schema(conn):
    """确保 `features.description` 列与 `place_notes` 表存在（懒迁移，自愈）。

    - `features.description`：静态说明（建库时从数据源带，可为空）；
    - `place_notes`：**动态见闻**（某地发生过的事），独立表、建库重建时不删。
    """
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(features)")]
        if "description" not in cols:
            conn.execute("ALTER TABLE features ADD COLUMN description TEXT")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS place_notes (
                   id      INTEGER PRIMARY KEY AUTOINCREMENT,
                   map_id  TEXT,
                   name    TEXT NOT NULL,
                   note    TEXT NOT NULL,
                   time    TEXT,
                   created TEXT DEFAULT CURRENT_TIMESTAMP
               )"""
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_place_notes_name ON place_notes(name)")
        conn.commit()
        _SCHEMA_READY = True
    except sqlite3.Error:
        pass


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


def _notes_map(conn, names) -> dict:
    """取若干地名对应的动态见闻：{name: [{time, note}, ...]}。"""
    names = [n for n in set(names) if n]
    if not names:
        return {}
    ph = ",".join("?" * len(names))
    out: dict = {}
    try:
        for name, note, t in conn.execute(
            f"SELECT name, note, time FROM place_notes WHERE name IN ({ph}) ORDER BY id", names
        ):
            out.setdefault(name, []).append({"time": t or "", "note": note})
    except sqlite3.Error:
        return {}
    return out


def _attach_notes(conn, results):
    """把静态 description 与动态见闻合并进结果的 `description`（并附 `notes`）。"""
    nmap = _notes_map(conn, [r.get("name") for r in results])
    for r in results:
        base = r.pop("_base_desc", None)
        notes = nmap.get(r.get("name") or "", [])
        parts = []
        if base:
            parts.append(str(base))
        if notes:
            parts.append("；".join((f"{n['time']} " if n["time"] else "") + n["note"] for n in notes))
        r["description"] = " ｜ ".join(parts) if parts else None
        if notes:
            r["notes"] = notes


def query_nearby(lon, lat, radius_km=1.0, kind=None, category=None, limit=20):
    """查询某坐标附近的地点（点/线/面都按最近距离精确计算）。"""
    conn = _connect()
    cur = conn.cursor()

    m_per_deg_lon = M_PER_DEG_LON0 * math.cos(math.radians(lat))
    dy = radius_km * 1050 / M_PER_DEG_LAT
    dx = radius_km * 1050 / m_per_deg_lon

    sql = """
        SELECT f.name, f.ancient_kind, f.category, f.geometry_type,
               f.coords, f.name_modern, f.description
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
    for name, akind, cat, gtype, coords_txt, name_modern, desc in cur.execute(sql, params):
        geom = _shape(gtype, coords_txt)
        if geom is None:
            continue
        geom_m = transform(to_m, geom)
        d_m = geom_m.distance(pt_m)
        if d_m > radius_km * 1000:
            continue
        # 返回**几何体上离查询点最近的点**（非代表点）：
        # 线/面可能很长，代表点（中点/内部点）会离查询点很远，
        # 若把它当地标就会把玩家瞬移出去（实测差过 184 米）。
        np_m = nearest_points(geom_m, pt_m)[0]
        results.append({
            "name": name,
            "kind": akind,
            "category": cat,
            "geometry_type": gtype,
            "lon": round(np_m.x / m_per_deg_lon, 6),
            "lat": round(np_m.y / M_PER_DEG_LAT, 6),
            "distance_km": round(d_m / 1000.0, 3),
            "name_modern": name_modern,
            "_base_desc": desc,
        })
    _attach_notes(conn, results)
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
               f.coords, f.name_modern, f.description
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
    for name2, akind, cat, gtype, coords_txt, name_modern, desc in cur.execute(sql, params):
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
            "_base_desc": desc,
        })
    _attach_notes(conn, results)
    conn.close()

    return {"success": True, "count": len(results), "results": results}


def update_place_note(place: str, note: str, time: str = "") -> dict:
    """给某地点追加一条**动态见闻**（该地发生过的事）。

    存在 `place_notes` 表（重建地图不丢）；以后 `query_nearby` / `query_place`
    命中该地名时，会把见闻合并进 `description` 返回。
    """
    place = (place or "").strip()
    note = (note or "").strip()
    if not place or not note:
        return {"success": False, "error": "place 与 note 均不能为空"}
    try:
        conn = _connect()
        conn.execute(
            "INSERT INTO place_notes(map_id, name, note, time) VALUES(?,?,?,?)",
            [DEFAULT_MAP, place, note, time or ""],
        )
        conn.commit()
        n = conn.execute("SELECT COUNT(*) FROM place_notes WHERE name=?", [place]).fetchone()[0]
        conn.close()
    except sqlite3.Error as e:
        return {"success": False, "error": str(e)}
    return {"success": True, "place": place, "note": note, "total": n}


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


# ------------------------------------------------------------
# 城池内外判定（供主持人获得权威空间感，避免"不知何时出了城"）
# ------------------------------------------------------------
_wall_polygon_cache = None


def _wall_polygon():
    """把「大城城墙」（闭合 LineString）建成 Polygon，供点内外判定。"""
    global _wall_polygon_cache
    if _wall_polygon_cache is None:
        poly = False
        try:
            conn = _connect()
            row = conn.execute(
                "SELECT coords FROM features WHERE map_id=? AND ancient_kind='城墙' "
                "AND geometry_type LIKE '%LineString%' LIMIT 1",
                [DEFAULT_MAP],
            ).fetchone()
            conn.close()
            if row:
                geom = sg.shape({"type": "LineString", "coordinates": json.loads(row[0])})
                if geom.is_ring:
                    poly = sg.Polygon(geom)
        except Exception:
            poly = False
        _wall_polygon_cache = poly
    return _wall_polygon_cache or None


def city_context(lon, lat) -> dict:
    """玩家在城内/城外 + 距城墙（米）+ 最近城门。失败返回 {}。"""
    try:
        lon = float(lon)
        lat = float(lat)
    except (TypeError, ValueError):
        return {}
    out = {}
    poly = _wall_polygon()
    if poly is not None:
        pt = sg.Point(lon, lat)
        out["在城内"] = bool(poly.contains(pt))
        d_deg = poly.exterior.distance(pt)
        out["距城墙（米）"] = round(d_deg * M_PER_DEG_LON0 * math.cos(math.radians(lat)))
    try:
        gates = query_nearby(lon, lat, radius_km=3.0, kind="城门", limit=1).get("results", [])
        if gates:
            out["最近城门"] = f"{gates[0]['name']}（约{gates[0]['distance_km']}km）"
    except Exception:
        pass
    return out
