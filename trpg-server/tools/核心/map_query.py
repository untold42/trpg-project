# -*- coding: utf-8 -*-
"""
map_query.py
============
地图空间查询工具（供 LLM function calling 调用）。**多城市**：当前地图由 游戏数据/地图设置.json
决定（前端主菜单「环境设定 → 地图」切换）。

读取 trpg-map/draw_tiles/db/map_spatial_<map_id>.db（R-tree + 完整几何），提供：
    query_nearby(lon, lat, radius_km, kind, category, limit)  精确范围查询
    query_place(name, kind, category, limit)                   名称/类别查找
    list_map_kinds()                                            列出所有地点类别及数量

坐标均为 WGS84。
"""

import json
import math
import os
import sqlite3
import sys

import shapely.geometry as sg
from shapely.ops import nearest_points, transform

from tools.核心.place_hours import hours_for, is_open, now_shichen_index

# trpg-server 的上一级是 trpg-project；空间库在 trpg-map/draw_tiles/db/ 下
SERVER_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_MAP_REGIONS = {"yangzhou": "扬州", "yueyang": "岳阳"}


# 当前地图是**动态**的：前端「环境设定 → 地图」可切，存 游戏数据/地图设置.json。
# 故不能做成模块常量——要在每次查询时现取（见 tools/map_settings.py）。
# 地图库路径：db/map_spatial_<map_id>.db（一城市一个，互不覆盖）
def current_map() -> str:
    try:
        from tools.核心.map_settings import get_map
        return get_map()
    except Exception:
        return os.environ.get("TRPG_MAP", "yangzhou")


def current_region() -> str:
    """该地图对应的「区域」名（写入 基本信息.位置.区域；天气分区 / 世界推演用）"""
    return os.environ.get("TRPG_REGION") or _MAP_REGIONS.get(current_map(), "扬州")


def db_file_for(map_id: str) -> str:
    """指定地图的空间库路径（跨城查询 / 搜索用）。"""
    return os.path.abspath(os.path.join(
        SERVER_DIR, "..", "trpg-map", "draw_tiles", "db",
        f"map_spatial_{map_id}.db"))


def db_file() -> str:
    return db_file_for(current_map())


def current_city() -> str:
    """当前地图的中文城市名（如 岳阳）。"""
    return region_of(current_map())


def region_of(map_id: str) -> str:
    """map_id -> 中文区域名。"""
    p = os.path.join(SERVER_DIR, "..", "trpg-map")
    if p not in sys.path:
        sys.path.insert(0, p)
    try:
        from 城市 import CITIES, map_id as _mid  # noqa: E402
        for cn in CITIES:
            if _mid(cn) == map_id:
                return cn
    except Exception:
        pass
    return _MAP_REGIONS.get(map_id, map_id)


def map_at(lon: float, lat: float):
    """坐标落在哪张图的画框里；都不在返回 None（跨城移动用）。"""
    try:
        from tools.核心.map_settings import map_at as _ma
        return _ma(lon, lat)
    except Exception:
        return None


def current_frame():
    """当前地图的画框 (min_lon, min_lat, max_lon, max_lat)；取不到返回 None。

    与 PBF 裁剪 / 瓦片取景共用同一份定义（trpg-map/城市.py）。
    """
    p = os.path.join(SERVER_DIR, "..", "trpg-map")
    if p not in sys.path:
        sys.path.insert(0, p)
    try:
        from 城市 import CITIES, frame_bbox, map_id as _mid  # noqa: E402
        cur = current_map()
        for cn in CITIES:
            if _mid(cn) == cur:
                return frame_bbox(cn)
    except Exception:
        pass
    return None


# 兼容旧引用（模块级常量已废弃，请改用上面的函数）
DEFAULT_MAP = current_map()
DEFAULT_REGION = current_region()

M_PER_DEG_LAT = 111132.95
M_PER_DEG_LON0 = 111320.0


def _connect():
    path = db_file()
    if not os.path.exists(path):
        raise FileNotFoundError(f"找不到空间数据库：{path}")
    conn = sqlite3.connect(path)
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
        if "hours" not in cols:
            # 懒迁移：新增「营业时间」列并按 ancient_kind 回填（单一真相源：trpg-world/营业时间.json）
            conn.execute("ALTER TABLE features ADD COLUMN hours TEXT")
            rows = conn.execute("SELECT fid, ancient_kind FROM features").fetchall()
            conn.executemany(
                "UPDATE features SET hours=? WHERE fid=?",
                [(hours_for(k), fid) for fid, k in rows],
            )
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
        # 建筑**内部结构**（存档时由主持人确定一次，之后一直有效）
        conn.execute(
            """CREATE TABLE IF NOT EXISTS place_structures (
                   name      TEXT PRIMARY KEY,
                   map_id    TEXT,
                   structure TEXT NOT NULL,
                   time      TEXT,
                   updated   TEXT DEFAULT CURRENT_TIMESTAMP
               )"""
        )
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


# ------------------------------------------------------------
# 方位 / 距离（硬事实：供主持人表述东南西北，不得臆断）
# ------------------------------------------------------------
_DIRS = ["北", "东北", "东", "东南", "南", "西南", "西", "西北"]


def bearing_name(lon1, lat1, lon2, lat2) -> str:
    """从点 1 到点 2 的**八方位**（北/东北/东/…）。失败返回 ''。"""
    try:
        dlon = math.radians(float(lon2) - float(lon1))
        la1, la2 = math.radians(float(lat1)), math.radians(float(lat2))
    except (TypeError, ValueError):
        return ""
    y = math.sin(dlon) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(dlon)
    brg = (math.degrees(math.atan2(y, x)) + 360) % 360
    return _DIRS[int((brg + 22.5) // 45) % 8]


def distance_m(lon1, lat1, lon2, lat2) -> float:
    """两点近似距离（米，等距圆柱投影，与 location._distance_m 一致）。"""
    try:
        mlat = 111132.95
        mlon = 111320.0 * math.cos(math.radians((float(lat1) + float(lat2)) / 2))
        return math.hypot((float(lon2) - float(lon1)) * mlon,
                          (float(lat2) - float(lat1)) * mlat)
    except (TypeError, ValueError):
        return 0.0


def player_position():
    """玩家当前坐标（读 基本信息.位置），拿不到返回 (None, None)。"""
    try:
        from tools.核心.state_manager import state
        p = (state.load("基本信息", {}) or {}).get("位置", {}) or {}
        lon, lat = p.get("经度"), p.get("纬度")
        if isinstance(lon, (int, float)) and isinstance(lat, (int, float)):
            return lon, lat
    except Exception:
        pass
    return None, None


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


def notes_for(name: str) -> list:
    """某地名的动态见闻（place_notes），按写入顺序。"""
    if not name:
        return []
    conn = _connect()
    try:
        return _notes_map(conn, [name]).get(name, [])
    except Exception:
        return []
    finally:
        conn.close()


def _attach_structure(conn, results):
    """把建筑**内部结构**合并进结果（`结构` 字段）。"""
    names = [r.get("name") for r in results if r.get("name")]
    if not names:
        return
    uniq = list(set(names))
    ph = ",".join("?" * len(uniq))
    try:
        m = dict(conn.execute(
            f"SELECT name, structure FROM place_structures WHERE name IN ({ph})", uniq
        ).fetchall())
    except sqlite3.Error:
        return
    for r in results:
        s = m.get(r.get("name") or "")
        if s:
            r["结构"] = s


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
    _attach_structure(conn, results)


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
    params = [current_map(), lon - dx, lon + dx, lat - dy, lat + dy]
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
    now_i = now_shichen_index()

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
        _b = geom_m.bounds
        results.append({
            "name": name,
            "kind": akind,
            "category": cat,
            "geometry_type": gtype,
            "lon": round(np_m.x / m_per_deg_lon, 6),
            "lat": round(np_m.y / M_PER_DEG_LAT, 6),
            "distance_km": round(d_m / 1000.0, 3),
            "size_m": round(math.hypot(_b[2] - _b[0], _b[3] - _b[1])),
            "name_modern": name_modern,
            "营业时间": hours_for(akind),
            "现在": ("营业" if is_open(hours_for(akind), now_i) else "打烊"),
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


def nearby_places_brief(lon, lat, radius_km=0.6, limit=12):
    """供 LLM 的「附近实名地点」摘要：只取**有名字**的要素，带方位 + 距离（米）。

    用于「地名必须真实」——每轮注入，让主持人有真实地名可用、不生造。
    """
    try:
        res = query_nearby(lon, lat, radius_km=radius_km, limit=80)
    except Exception:
        return []
    out = []
    now_i = now_shichen_index()
    for r in res.get("results", []):
        name = r.get("name")
        if not name:
            continue
        item = {"name": name, "kind": r.get("kind") or ""}
        rlon, rlat = r.get("lon"), r.get("lat")
        if isinstance(rlon, (int, float)) and isinstance(rlat, (int, float)):
            item["方位"] = bearing_name(lon, lat, rlon, rlat)
            item["距玩家（米）"] = round(distance_m(lon, lat, rlon, rlat))
        hours = hours_for(r.get("kind"))
        item["营业时间"] = hours
        item["现在"] = "营业" if is_open(hours, now_i) else "打烊"
        out.append(item)
        if len(out) >= limit:
            break
    return out


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
    params = [current_map()]
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
    params.append(max(limit * 20, 200))   # 先多取，再按「同名优先 + 距玩家」排序后切片

    now_i = now_shichen_index()
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
            "营业时间": hours_for(akind),
            "现在": ("营业" if is_open(hours_for(akind), now_i) else "打烊"),
            "_base_desc": desc,
        })
    _attach_notes(conn, results)
    conn.close()

    # 每个结果的方位 / 距玩家（硬事实：防主持人把「东北」说成「西」）
    plon, plat = player_position()
    if plon is not None:
        for r in results:
            if isinstance(r.get("lon"), (int, float)) and isinstance(r.get("lat"), (int, float)):
                r["方位"] = bearing_name(plon, plat, r["lon"], r["lat"])
                r["距玩家（米）"] = round(distance_m(plon, plat, r["lon"], r["lat"]))
        # 同名地点（如「玄冥庙」城内 / 君山各一所）必须按**离玩家远近**排，近的在前；
        # 否则 limit=1 会取到数据库里先出现的那一个，把玩家瞬移到几公里外。
        if name:
            results.sort(key=lambda r: (0 if r.get("name") == name else 1,
                                        r.get("距玩家（米）", float("inf"))))
        else:
            results.sort(key=lambda r: r.get("距玩家（米）", float("inf")))

    results = results[:limit]
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
            [current_map(), place, note, time or ""],
        )
        conn.commit()
        n = conn.execute("SELECT COUNT(*) FROM place_notes WHERE name=?", [place]).fetchone()[0]
        conn.close()
    except sqlite3.Error as e:
        return {"success": False, "error": str(e)}
    return {"success": True, "place": place, "note": note, "total": n}


def update_place_structure(place: str, structure: str, time: str = "") -> dict:
    """写入/覆盖某建筑的**内部结构**（几层、哪间是谁的、后院有什么…）。

    存在 `place_structures` 表（重建地图不丢）；以后 `query_nearby` / `query_place`
    命中该地名时，会把 `结构` 一并返回——主持人不必再现编。
    """
    place = (place or "").strip()
    structure = (structure or "").strip()
    if not place or not structure:
        return {"success": False, "error": "place 与 structure 均不能为空"}
    try:
        conn = _connect()
        conn.execute(
            """INSERT INTO place_structures(map_id, name, structure, time, updated)
               VALUES(?,?,?,?,CURRENT_TIMESTAMP)
               ON CONFLICT(name) DO UPDATE SET structure=excluded.structure,
                                               time=excluded.time,
                                               updated=CURRENT_TIMESTAMP""",
            [current_map(), place, structure, time or ""],
        )
        conn.commit()
        conn.close()
    except sqlite3.Error as e:
        return {"success": False, "error": str(e)}
    return {"success": True, "place": place, "structure": structure}


def structure_for(name: str) -> str:
    """某建筑的内部结构（无则返回空串）。"""
    if not name:
        return ""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT structure FROM place_structures WHERE name=?", [name]
        ).fetchone()
        return (row[0] if row else "") or ""
    except Exception:
        return ""
    finally:
        conn.close()


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
        [current_map(), limit],
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
_wall_polygon_cache = {}   # map_id -> Polygon | None


def _wall_polygon():
    """把「大城城墙」（闭合 LineString）建成 Polygon，供点内外判定。

    ⚠️ **按地图缓存**——全局单缓存的话，切城后会拿旧城的城墙去量新城的点
    （实测出现过「距城墙 604 公里」）。
    """
    mid = current_map()
    if mid in _wall_polygon_cache:
        return _wall_polygon_cache[mid]
    poly = None
    try:
        conn = _connect()
        row = conn.execute(
            "SELECT coords FROM features WHERE map_id=? AND ancient_kind='城墙' "
            "AND geometry_type LIKE '%LineString%' LIMIT 1",
            [mid],
        ).fetchone()
        conn.close()
        if row:
            geom = sg.shape({"type": "LineString", "coordinates": json.loads(row[0])})
            if geom.is_ring:
                poly = sg.Polygon(geom)
    except Exception:
        poly = None
    _wall_polygon_cache[mid] = poly
    return poly


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
        inside = bool(poly.covers(pt))  # covers 含边界（城门就在墙线上）
        out["在城内"] = inside
        # 距城墙（米）：先求最近点，再换算成局部米制（经纬分开缩放）
        try:
            ring = poly.exterior
            near = ring.interpolate(ring.project(pt))
            d_m = math.hypot((near.x - lon) * M_PER_DEG_LON0 * math.cos(math.radians(lat)),
                             (near.y - lat) * M_PER_DEG_LAT)
            out["距城墙（米）"] = round(d_m)
        except Exception:
            pass
        # 城区方位（相对城墙中心）：如「城内东北」「城外西南」
        cx, cy = poly.centroid.x, poly.centroid.y
        ns = "北" if lat > cy else "南"
        ew = "东" if lon > cx else "西"
        out["城区方位"] = ("城内" if inside else "城外") + ew + ns
    try:
        gates = query_nearby(lon, lat, radius_km=3.0, kind="城门", limit=1).get("results", [])
        if gates:
            out["最近城门"] = f"{gates[0]['name']}（约{gates[0]['distance_km']}km）"
    except Exception:
        pass
    return out


def _wall_distance_m(lon, lat, poly):
    """点到城墙（米）；无城墙返回 None。"""
    if poly is None:
        return None
    try:
        ring = poly.exterior
        pt = sg.Point(lon, lat)
        near = ring.interpolate(ring.project(pt))
        return math.hypot((near.x - lon) * M_PER_DEG_LON0 * math.cos(math.radians(lat)),
                          (near.y - lat) * M_PER_DEG_LAT)
    except Exception:
        return None


def nearest_walkable_point(lon, lat, radius_km: float = 2.0):
    """「脱离卡死」：找一个附近**可走**的落脚点。

    几何上取**最近的道路**（前端把路当可走廊道）；但避开前端会挡的点：
    落在城墙 ±12m 内、且不在城门 25m 内的路点会被墙挡住 → 跳过试下一条。
    半径由近及远逐步放宽，避免一上来就瞬移几百米。
    返回 `{lon, lat, 地点, 距离_m}` 或 None。数值与前端 `walkable.ts` 对齐。
    """
    try:
        lon, lat = float(lon), float(lat)
    except (TypeError, ValueError):
        return None
    roads = []
    for rk in (0.6, 1.5, radius_km):
        res = query_nearby(lon, lat, radius_km=rk, category="road", limit=10)
        roads = [r for r in res.get("results", [])
                 if r.get("lon") is not None and r.get("kind") != "城墙"]
        if roads:
            break
    if not roads:
        return None
    poly = _wall_polygon()
    gates = query_nearby(lon, lat, radius_km=radius_km, kind="城门", limit=10).get("results", [])
    for r in roads:
        rlon, rlat = r["lon"], r["lat"]
        d_wall = _wall_distance_m(rlon, rlat, poly)
        if d_wall is not None and d_wall <= 12:      # 会被城墙挡
            near_gate = any(
                math.hypot((rlon - g["lon"]) * M_PER_DEG_LON0 * math.cos(math.radians(rlat)),
                           (rlat - g["lat"]) * M_PER_DEG_LAT) <= 25
                for g in gates if g.get("lon") is not None
            )
            if not near_gate:
                continue
        return {
            "lon": rlon,
            "lat": rlat,
            "地点": r.get("name") or "",
            "距离_m": round(distance_m(lon, lat, rlon, rlat)),
        }
    return None


def _shichen_index(s: str) -> int:
    SH = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]
    s = (s or "").strip().replace("时", "")
    return SH.index(s) if s in SH else -1


def _hours_open(hours: str, now: str) -> bool:
    """营业时间（如「卯-申」「全天」）在 now 时辰是否开放。"""
    h = (hours or "").strip().replace("时", "")
    if not h or h == "全天" or "-" not in h:
        return True
    a, b = h.split("-", 1)
    ia, ib, ino = _shichen_index(a), _shichen_index(b), _shichen_index(now)
    if ia < 0 or ib < 0 or ino < 0:
        return True
    return ia <= ino <= ib if ia <= ib else (ino >= ia or ino <= ib)


def gate_crossing(lon, lat) -> dict:
    """玩家要过城门：找最近城门，算**城墙另一侧**的落脚点（沿「玩家→城门」方向再外推）。

    返回：{城门, 原在城内, 方向(出城|入城), 落脚点:{lon,lat}, 落脚在城内, 可通行}；失败 {}。
    设计：城门是硬事实（由城墙算），移动仍由大模型调 update_location 落库。
    """
    try:
        lon, lat = float(lon), float(lat)
    except (TypeError, ValueError):
        return {}
    try:
        gates = query_nearby(lon, lat, radius_km=8.0, kind="城门", limit=1).get("results", [])
    except Exception:
        gates = []
    if not gates:
        return {}
    g = gates[0]
    glon, glat = g.get("lon"), g.get("lat")
    if glon is None or glat is None:
        return {}
    ctx = city_context(lon, lat)
    inside = ctx.get("在城内")
    # 方向：玩家 → 城门 → 再往外推（过墙）
    mlon = M_PER_DEG_LON0 * math.cos(math.radians(lat))
    dx, dy = (glon - lon) * mlon, (glat - lat) * M_PER_DEG_LAT
    n = math.hypot(dx, dy) or 1.0
    ux, uy = dx / n, dy / n
    landing, land_inside = None, None
    for step in (45.0, 65.0, 85.0, 30.0):
        clon = glon + (ux * step) / (M_PER_DEG_LON0 * math.cos(math.radians(glat)))
        clat = glat + (uy * step) / M_PER_DEG_LAT
        c2 = city_context(clon, clat)
        land_inside = c2.get("在城内")
        if inside is None or land_inside != inside:
            landing = {"lon": round(clon, 6), "lat": round(clat, 6)}
            break
    if landing is None:
        return {}
    return {
        "城门": g.get("name") or "城门",
        "原在城内": inside,
        "方向": "出城" if inside else "入城",
        "落脚点": landing,
        "落脚在城内": land_inside,
        "可通行": _hours_open(g.get("营业时间", ""), g.get("现在", "")),
    }


# ------------------------------------------------------------
# 跨地图搜索（前端地图里的「搜索」框：搜城市 / 搜地点，命中即跳）
# ------------------------------------------------------------

def search_all_maps(q: str, limit: int = 20) -> list:
    """在所有已生成的地图里按名字搜地点，返回带城市坐标的列表。

    每项：{map_id, 地图, 名称, 类型, lon, lat}。城市名本身也会命中（lon/lat=None）。
    """
    from tools.核心.map_settings import available_maps

    q = (q or "").strip()
    if not q:
        return []
    out = []
    seen = set()          # (map_id, 名称) 去重：同名的路/坊有很多段
    for m in available_maps():
        mid, city = m["id"], m["name"]
        if q in city or q in mid:
            out.append({"map_id": mid, "地图": city, "名称": city, "类型": "城市",
                        "lon": None, "lat": None})
            seen.add((mid, city))
        path = db_file_for(mid)
        if not os.path.exists(path):
            continue
        try:
            conn = sqlite3.connect(path)
            rows = conn.execute(
                "SELECT name, ancient_kind, geometry_type, coords FROM features "
                "WHERE map_id = ? AND name LIKE ? "
                "ORDER BY CASE WHEN name = ? THEN 0 "
                "              WHEN name LIKE ? THEN 1 ELSE 2 END, LENGTH(name) "
                "LIMIT ?",
                (mid, f"%{q}%", q, f"{q}%", limit)).fetchall()
            conn.close()
        except Exception:
            continue
        for name, kind, gt, ct in rows:
            if (mid, name) in seen:
                continue
            seen.add((mid, name))
            pt = None
            try:
                pt = _reppoint(sg.shape({"type": gt, "coordinates": json.loads(ct)}))
            except Exception:
                pass
            out.append({"map_id": mid, "地图": city, "名称": name,
                        "类型": kind or "", "lon": pt[0] if pt else None,
                        "lat": pt[1] if pt else None})
    return out[:limit]
