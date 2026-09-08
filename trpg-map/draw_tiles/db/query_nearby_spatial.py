# -*- coding: utf-8 -*-
"""
query_nearby_spatial.py
=======================
在带空间索引的库（create_spatial_db.py 生成）上做精确范围查询。

点/线/面都精确：先把半径换算成经纬度方框走 R-tree 粗筛，
再用 shapely 对完整几何计算“到该要素最近处的距离”（米）。

小范围查询用局部等距近似换算；库内坐标是 WGS84 经纬度。

用法：
    python query_nearby_spatial.py --lon 119.4175 --lat 32.41 --r 1
    python query_nearby_spatial.py --lon 119.4175 --lat 32.41 --r 1.5 \
                                   --kind 客栈 --limit 30
"""

import argparse
import json
import math
import os
import sqlite3

import shapely.geometry as sg
from shapely.ops import transform

# db/ 目录里放数据库文件
DB_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(DB_DIR, "map_spatial.db")
DEFAULT_MAP = "yangzhou"

# 局部米制换算：小范围查询足够精确
M_PER_DEG_LAT = 111132.95
M_PER_DEG_LON0 = 111320.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--r", type=float, default=1.0, help="半径（公里）")
    parser.add_argument("--kind", default=None)
    parser.add_argument("--category", default=None)
    parser.add_argument("--geometry", default=None,
                        help="Point/LineString/Polygon 等，默认全部")
    parser.add_argument("--map", default=DEFAULT_MAP)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()

    # 米 -> 度（方框略放大 5%，保证不漏）
    m_per_deg_lon = M_PER_DEG_LON0 * math.cos(math.radians(args.lat))
    dy = args.r * 1050 / M_PER_DEG_LAT
    dx = args.r * 1050 / m_per_deg_lon

    sql = """
        SELECT f.fid, f.name, f.category, f.ancient_kind, f.geometry_type,
               f.coords
        FROM features f
        JOIN features_rtree r ON f.fid = r.fid
        WHERE f.map_id = ?
          AND r.maxx >= ? AND r.minx <= ?
          AND r.maxy >= ? AND r.miny <= ?
    """
    params = [args.map, args.lon - dx, args.lon + dx,
              args.lat - dy, args.lat + dy]
    if args.kind:
        sql += " AND f.ancient_kind=?"
        params.append(args.kind)
    if args.category:
        sql += " AND f.category=?"
        params.append(args.category)
    if args.geometry:
        sql += " AND f.geometry_type=?"
        params.append(args.geometry)

    # 局部等距变换：x 乘 经度米/度，y 乘 纬度米/度
    def to_meters(x, y):
        return (x * m_per_deg_lon, y * M_PER_DEG_LAT)

    pt_m = sg.Point(args.lon * m_per_deg_lon,
                    args.lat * M_PER_DEG_LAT)

    results = []
    for fid, name, cat, kind, gtype, coords_txt in cur.execute(sql, params):
        try:
            coords = json.loads(coords_txt)
            geom = sg.shape({"type": gtype, "coordinates": coords})
        except Exception:
            continue
        if geom is None or geom.is_empty:
            continue
        geom_m = transform(to_meters, geom)
        d_m = geom_m.distance(pt_m)
        if d_m <= args.r * 1000:
            results.append((d_m / 1000.0, fid, name, cat, kind, gtype))

    results.sort(key=lambda x: x[0])
    results = results[: args.limit]
    conn.close()

    lines = [f"中心({args.lon}, {args.lat}) 半径{args.r}km "
             f"命中{len(results)}个（含线/面精确距离）"]
    lines.append("距离(km)|fid|名称|大类|类别|几何")
    for d, fid, name, cat, kind, gtype in results:
        lines.append(f"{d:.4f}|{fid}|{name or ''}|{cat}|{kind}|{gtype}")

    text = "\n".join(lines)
    if args.out:
        with open(os.path.join(DB_DIR, args.out), "w", encoding="utf-8") as f:
            f.write(text + "\n")
    else:
        print(text)


if __name__ == "__main__":
    main()
