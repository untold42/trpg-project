# -*- coding: utf-8 -*-
"""
create_spatial_db.py
====================
把转译后的 JSON 建成“带完整几何 + 空间索引”的 SQLite 库（免外部扩展）。

设计（面向将来多张地图扩展）：
    maps(map_id, name)               -- 一张地图一行
    features(fid, map_id, oid, name, name_modern,
              category, ancient_kind, geometry_type, coords)
        -- coords 是完整几何坐标（JSON 文本），可随时还原成 shapely / GeoJSON
    features_rtree(fid, minx, maxx, miny, maxy)
        -- SQLite 原生 R-tree 空间索引（按包围盒粗筛）

用法：
    python create_spatial_db.py [--input map_ancient_song.json]
                                [--db map_spatial.db] [--map yangzhou]
"""

import argparse
import json
import math
import os
import sqlite3

# ---- 目录约定（v2：已按功能分文件夹）----
# 本项目根目录：db/ 的上一级
PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
# 数据库文件放在 db/ 目录里
DB_DIR = os.path.dirname(os.path.abspath(__file__))

INPUT_FILE = os.path.join(PROJECT_ROOT, "map_ancient_song.json")
DB_FILE = os.path.join(DB_DIR, "map_spatial.db")
MAP_ID = "yangzhou"
MAP_NAME = "南宋扬州"


def resolve(path, default_dir):
    """绝对路径直接用；相对路径相对给定目录。"""
    return path if os.path.isabs(path) else os.path.join(default_dir, path)

# geometry type -> (shapely 构造函数所需层级)。这里只需要坐标（形状），
# 我们不生成 geometry，只展开所有坐标算 MBR。


def flatten_points(coords):
    """递归展开任意 GeoJSON 坐标嵌套 -> [(lon, lat), ...]"""
    pts = []
    def walk(v):
        if (isinstance(v, (list, tuple))
                and len(v) >= 2
                and all(isinstance(x, (int, float)) for x in v[:2])):
            pts.append((v[0], v[1]))
            return
        if isinstance(v, (list, tuple)):
            for item in v:
                walk(item)
    walk(coords)
    return pts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=INPUT_FILE)
    parser.add_argument("--db", default=DB_FILE)
    parser.add_argument("--map", default=MAP_ID)
    parser.add_argument("--map-name", default=MAP_NAME)
    args = parser.parse_args()

    input_path = resolve(args.input, PROJECT_ROOT)
    db_path = resolve(args.db, DB_DIR)

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS maps (
            map_id TEXT PRIMARY KEY,
            name   TEXT
        );
        DROP TABLE IF EXISTS features;
        CREATE TABLE features (
            fid           INTEGER PRIMARY KEY AUTOINCREMENT,
            map_id        TEXT NOT NULL,
            oid           INTEGER,
            name          TEXT,
            name_modern   TEXT,
            category      TEXT,
            ancient_kind  TEXT,
            geometry_type TEXT,
            coords        TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_features_map ON features(map_id);
        CREATE INDEX IF NOT EXISTS idx_features_kind ON features(ancient_kind);
        CREATE INDEX IF NOT EXISTS idx_features_cat  ON features(category);
        CREATE INDEX IF NOT EXISTS idx_features_name ON features(name);
        DROP TABLE IF EXISTS features_rtree;
        CREATE VIRTUAL TABLE features_rtree USING rtree(
            fid, minx, maxx, miny, maxy
        );
    """)

    cur.execute(
        "INSERT OR REPLACE INTO maps(map_id, name) VALUES(?,?)",
        (args.map, args.map_name),
    )

    batch_feat = []
    batch_rt = []
    skipped = 0

    for o in data.get("objects", []):
        geom = o.get("geometry") or {}
        gtype = geom.get("type")
        coords = geom.get("coordinates")
        if not coords:
            skipped += 1
            continue

        pts = flatten_points(coords)
        if not pts:
            skipped += 1
            continue

        minx = min(p[0] for p in pts)
        maxx = max(p[0] for p in pts)
        miny = min(p[1] for p in pts)
        maxy = max(p[1] for p in pts)

        batch_feat.append((
            args.map,
            o.get("id"),
            o.get("name"),
            o.get("name_modern"),
            o.get("category"),
            o.get("ancient_kind"),
            gtype,
            json.dumps(coords),
        ))
        # 先用临时占位 fid，插入后再回填 rtree
        batch_rt.append((0, minx, maxx, miny, maxy))

    cur.executemany(
        """INSERT INTO features(map_id, oid, name, name_modern, category,
                                ancient_kind, geometry_type, coords)
           VALUES(?,?,?,?,?,?,?,?)""",
        batch_feat,
    )

    # 回填 R-tree（fid 从 1 开始，与自增列一致）
    rt_rows = []
    for i, (_, minx, maxx, miny, maxy) in enumerate(batch_rt):
        rt_rows.append((i + 1, minx, maxx, miny, maxy))
    cur.executemany(
        "INSERT INTO features_rtree VALUES(?,?,?,?,?)", rt_rows
    )

    conn.commit()
    print("db:", db_path)
    print("map_id:", args.map)
    print("features:", len(batch_feat), "skipped:", skipped)

    conn.close()


if __name__ == "__main__":
    main()
