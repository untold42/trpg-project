# -*- coding: utf-8 -*-
"""
export_walkable.py
==================
从空间库 db/map_spatial.db 导出「碰撞/可走」数据，供前端实时判定。

碰撞规则（用户 2026-09-16 规定）：
    - 除**水域**和**城墙**外，其余一律可走；
    - 路 ∩ 城墙：默认不可走，只有**城门 25m 半径**是通道；
    - 路 ∩ 水域：默认路可走（路廊道内可通行）；
    - 有**桥**：桥 100m 半径内可走。

导出内容（FeatureCollection，properties.t 标注类型）：
    water   水域（category='water' 的多边形，经 shapely 简化）
    wall    城墙（闭合 LineString）
    gate    城门（Point）
    bridge  桥 / 浮桥（Point）
    road    道路（category='road'，含坊巷/官道，不含城墙）
    terrain 地形步速区（林地/山岩/滩涂/农田…；properties.mult = 步速倍率）

步速倍率（terrain.mult）：
    平地无地形面 = 1.0（基准）；road.mult 见下
    官道 1.15 / 坊巷 1.00（有路走就不算钻林子）
    农田 0.90 · 草地 0.85 · 草甸 0.80 · 墓地 0.90
    林地 0.60 · 灌木 0.65 · 树列 0.85
    滩涂 0.45 · 山岩/山地 0.35   ← “山路慢很多”

用法：
    python export_walkable.py [--tol 0.00005] [--out 路径]
    # 默认 tol=0.00005（约 5.5m），输出到 trpg-client/public/data/walkable.geojson
"""

import argparse
import json
import os
import sqlite3
import sys

import shapely.geometry as sg
from shapely.geometry import mapping

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 城市（可用 TRPG_CITY 覆盖）：决定读哪个空间库、写到哪个前端目录
sys.path.insert(0, os.path.dirname(BASE_DIR))          # trpg-map/
from 城市 import map_id as _map_id  # noqa: E402

CITY = os.environ.get("TRPG_CITY", "扬州")
MAP_ID = _map_id(CITY)

DB_FILE = os.path.join(BASE_DIR, "db", f"map_spatial_{MAP_ID}.db")
FRONTEND_PUBLIC = os.path.abspath(os.path.join(
    os.path.dirname(os.path.dirname(BASE_DIR)), "trpg-client", "public"))
# 一城市一个目录：public/data/<map_id>/walkable.geojson
DEFAULT_OUT = os.path.join(FRONTEND_PUBLIC, "data", MAP_ID, "walkable.geojson")


# ------------------------------------------------------------
# 地形 -> 步速倍率
#   key = (category, tags 里的值)；"山" 是 ancient_kind（命名山体）
#   倍率是相对“平地 1.0”的乘数，直接乘到前端基础步速上。
# ------------------------------------------------------------
TERRAIN_RULES = {
    ("natural", "wood"):               ("林地", 0.60),
    ("natural", "scrub"):              ("灌木", 0.65),
    ("natural", "wetland"):            ("滩涂", 0.45),
    ("natural", "bare_rock"):          ("山岩", 0.35),
    ("natural", "grassland"):          ("草地", 0.85),
    ("natural", "tree_row"):           ("树列", 0.85),
    ("landuse", "forest"):             ("林地", 0.60),
    ("landuse", "orchard"):            ("果园", 0.75),
    ("landuse", "vineyard"):           ("果园", 0.75),
    ("landuse", "farmland"):           ("农田", 0.90),
    ("landuse", "grass"):              ("草地", 0.85),
    ("landuse", "meadow"):             ("草甸", 0.80),
    ("landuse", "cemetery"):           ("墓地", 0.90),
    ("landuse", "recreation_ground"):  ("园地", 0.95),
    ("landuse", "village_green"):      ("绿地", 0.90),
}
MOUNTAIN_RULE = ("山地", 0.35)          # ancient_kind == '山'
ROAD_MULT = {"官道": 1.15, "坊巷": 1.0}
DEFAULT_ROAD_MULT = 1.0


def terrain_of(cat, tags, akind):
    """(category, tags, ancient_kind) -> (名称, 倍率) 或 None。"""
    if akind == "山":
        return MOUNTAIN_RULE
    if cat == "natural":
        return TERRAIN_RULES.get(("natural", tags.get("natural")))
    if cat == "landuse":
        return TERRAIN_RULES.get(("landuse", tags.get("landuse")))
    return None


def round_coords(x, nd=5):
    """递归四舍五入到 5 位小数（约 1m），显著减小体积。"""
    if isinstance(x, (list, tuple)):
        if x and isinstance(x[0], (int, float)):
            return [round(float(v), nd) for v in x]
        return [round_coords(v, nd) for v in x]
    return x


def n_vertices(coords):
    n = 0

    def walk(y):
        nonlocal n
        if isinstance(y, (list, tuple)) and y and isinstance(y[0], (int, float)):
            n += 1
            return
        if isinstance(y, (list, tuple)):
            for z in y:
                walk(z)

    walk(coords)
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tol", type=float, default=0.00005,
                    help="水域简化容差（度），0.00005 ≈ 5.5m")
    ap.add_argument("--out", default=DEFAULT_OUT)
    args = ap.parse_args()

    conn = sqlite3.connect(DB_FILE)
    feats = []

    def add(t, geometry, **props):
        if geometry is None:
            return
        p = {"t": t}
        p.update({k: v for k, v in props.items() if v not in (None, "")})
        feats.append({"type": "Feature", "properties": p, "geometry": geometry})

    # ---- 水域（简化）----
    raw_v = simp_v = 0
    for name, gt, ct in conn.execute(
            "SELECT name, geometry_type, coords FROM features "
            "WHERE category='water' AND geometry_type IN ('Polygon','MultiPolygon')"):
        g = sg.shape({"type": gt, "coordinates": json.loads(ct)})
        if g.is_empty:
            continue
        raw_v += n_vertices(json.loads(ct))
        s = g.simplify(args.tol, preserve_topology=True)
        if s.is_empty:
            s = g
        m = mapping(s)
        if m["type"] not in ("Polygon", "MultiPolygon"):
            continue
        simp_v += n_vertices(m["coordinates"])
        add("water", {"type": m["type"], "coordinates": round_coords(m["coordinates"])},
            name=name)

    # ---- 城墙 ----
    for gt, ct in conn.execute(
            "SELECT geometry_type, coords FROM features WHERE ancient_kind='城墙'"):
        add("wall", {"type": gt, "coordinates": round_coords(json.loads(ct))})

    # ---- 城门（按坐标去重：custom/historic 各存了一份）----
    _cols = [r[1] for r in conn.execute("PRAGMA table_info(features)")]
    _hours = "hours" if "hours" in _cols else "NULL"
    seen = set()
    for name, gt, ct, hours in conn.execute(
            f"SELECT name, geometry_type, coords, {_hours} "
            "FROM features WHERE ancient_kind='城门'"):
        co = json.loads(ct)
        key = (name, round(co[0], 5), round(co[1], 5))
        if key in seen:
            continue
        seen.add(key)
        add("gate", {"type": gt, "coordinates": round_coords(co)},
            name=name, hours=(hours or ""))

    # ---- 桥 / 浮桥 ----
    for name, gt, ct in conn.execute(
            "SELECT name, geometry_type, coords FROM features "
            "WHERE ancient_kind IN ('桥','浮桥')"):
        add("bridge", {"type": gt, "coordinates": round_coords(json.loads(ct))},
            name=name, kind=None)

    # ---- 道路（不含城墙）----
    for name, gt, ct, akind in conn.execute(
            "SELECT name, geometry_type, coords, ancient_kind FROM features "
            "WHERE category='road' AND (ancient_kind IS NULL OR ancient_kind<>'城墙')"):
        add("road", {"type": gt, "coordinates": round_coords(json.loads(ct))},
            name=name, kind=akind,
            mult=ROAD_MULT.get(akind, DEFAULT_ROAD_MULT))

    # ---- 地形步速区（可选：老库无 tags 列则跳过）----
    if "tags" in _cols:
        raw_t = simp_t = 0
        n_terrain = 0
        for name, cat, akind, gt, ct, tags_json in conn.execute(
                "SELECT name, category, ancient_kind, geometry_type, coords, tags "
                "FROM features WHERE category IN ('natural','landuse') "
                "AND geometry_type IN ('Polygon','MultiPolygon')"):
            try:
                tags = json.loads(tags_json) if tags_json else {}
            except Exception:
                tags = {}
            rule = terrain_of(cat, tags, akind)
            if not rule:
                continue
            label, mult = rule
            g = sg.shape({"type": gt, "coordinates": json.loads(ct)})
            if g.is_empty:
                continue
            raw_t += n_vertices(json.loads(ct))
            s = g.simplify(args.tol, preserve_topology=True)
            if s.is_empty:
                s = g
            m = mapping(s)
            if m["type"] not in ("Polygon", "MultiPolygon"):
                continue
            simp_t += n_vertices(m["coordinates"])
            add("terrain", {"type": m["type"], "coordinates": round_coords(m["coordinates"])},
                name=name, kind=label, mult=mult)
            n_terrain += 1
        print(f"  地形区 {n_terrain} 个（顶点 {raw_t} → {simp_t}）")
    else:
        print("  !! features 无 tags 列，跳过地形层（请先重跑 create_spatial_db.py）")

    out = {"type": "FeatureCollection", "features": feats}
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))

    size = os.path.getsize(args.out)
    from collections import Counter
    cnt = Counter(f["properties"]["t"] for f in feats)
    print(f"输出 {args.out}")
    print(f"  要素 {cnt}")
    print(f"  水域顶点 {raw_v} → {simp_v}（tol={args.tol}）")
    print(f"  文件大小 {size/1024/1024:.2f} MB")


if __name__ == "__main__":
    main()
