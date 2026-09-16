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

用法：
    python export_walkable.py [--tol 0.00005] [--out 路径]
    # 默认 tol=0.00005（约 5.5m），输出到 trpg-client/public/data/walkable.geojson
"""

import argparse
import json
import os
import sqlite3

import shapely.geometry as sg
from shapely.geometry import mapping

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "db", "map_spatial.db")
FRONTEND_PUBLIC = os.path.abspath(os.path.join(
    os.path.dirname(os.path.dirname(BASE_DIR)), "trpg-client", "public"))
DEFAULT_OUT = os.path.join(FRONTEND_PUBLIC, "data", "walkable.geojson")


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
            name=name, kind=akind)

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
