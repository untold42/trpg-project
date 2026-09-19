# -*- coding: utf-8 -*-
"""
修复水域POI.py —— 把「必须依水」的 POI 吸附到最近水岸（离水太远的删除）。

背景
    `build_world.py` 的随机布点池（edge / general）里混进了水类 kind（渡口/码头/桥…），
    而随机撒点**不看水**；冻结表 `数据/<城市>_POI.json` 又是从"半成品世界"冻的 →
    城里/旱地上出现船行、画舫、码头、渡口、桥。

做法（幂等）
    读 `数据/<城市>_南宋世界.json` 的**水面多边形**（category=water）作为水岸；
    对 POI 里的水类 kind：
        - 离水 ≤ KEEP_M       → 不动
        - KEEP_M < 离水 ≤ SNAP_M → 吸附到最近水岸（并做松弛，避免挤成一堆）
        - 离水 > SNAP_M       → 删除
    同时改写冻结表 `_POI.json` 与 `_南宋世界.json`（按 name+kind 对应）。

用法
    python 修复水域POI.py --city 岳阳            # 干跑，只报告
    python 修复水域POI.py --city 岳阳 --write    # 落盘
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict

from shapely.geometry import Point, shape
from shapely.ops import nearest_points, transform, unary_union
from shapely.strtree import STRtree

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "数据")
sys.path.insert(0, BASE)
from 城市 import DEFAULT_CITY  # noqa: E402

#: 必须依水的 kind（离水太远就是放错了）
WATER_KINDS = {"画舫", "船行", "码头", "渡口", "鱼行", "浮桥", "桥"}
KEEP_M = 60.0        # ≤ 此距离：认为已在岸边，不动
SNAP_M = 2000.0      # ≤ 此距离：吸附到最近水岸；> 此距离：删除
SPACING_M = 45.0     # 吸附后的最小间距（松弛）


def _load(city):
    world_path = os.path.join(DATA, f"{city}_南宋世界.json")
    poi_path = os.path.join(DATA, f"{city}_POI.json")
    world = json.load(open(world_path, encoding="utf-8"))
    frozen = json.load(open(poi_path, encoding="utf-8"))
    return world_path, poi_path, world, frozen


def _water_km(world):
    """水面多边形 → 米制坐标（局部等距）。返回 (米制几何列表, 正投影, 反投影)。"""
    lons, lats = [], []
    for o in world["objects"]:
        if o.get("category") != "water":
            continue
        g = shape(o["geometry"])
        lons.append(g.centroid.x)
        lats.append(g.centroid.y)
    lon0 = sum(lons) / len(lons) if lons else 113.0
    lat0 = sum(lats) / len(lats) if lats else 29.0
    k_lat = 111_000.0
    k_lon = 111_320.0 * math.cos(math.radians(lat0))

    def fwd(x, y):
        return ((x - lon0) * k_lon, (y - lat0) * k_lat)

    def inv(x, y):
        return (x / k_lon + lon0, y / k_lat + lat0)

    geoms = [shape(o["geometry"]) for o in world["objects"] if o.get("category") == "water"]
    # buffer(0) 修一下自交多边形（不影响最近点计算，但避免后续报错）
    km = []
    for g in geoms:
        try:
            km.append(transform(fwd, g if g.is_valid else g.buffer(0)))
        except Exception:
            pass
    return km, fwd, inv


def _project(pt, km, tree):
    """把点拉回最近的水面边界。"""
    ids = tree.query(pt.buffer(500))
    best_d, best_p = float("inf"), None
    for gi in ids:
        npt = nearest_points(pt, km[int(gi)])[1]
        d = pt.distance(npt)
        if d < best_d:
            best_d, best_p = d, npt
    return best_p if best_p is not None else pt


def _spread_on_water(snap, km, spacing=SPACING_M):
    """把吸附点沿**水岸线**均匀铺开（线性定位），避免挤成一堆。

    `snap`: [(poi, 水域下标, 最近点)] → 返回同长度的新点列表。
    每个水域一组：按在水岸线上的里程定位，左右各扫一遍保证 ≥ spacing，再回插值。
    """
    groups = defaultdict(list)
    for idx, (_p, gi, npt) in enumerate(snap):
        groups[gi].append((idx, npt))
    result = [None] * len(snap)
    for gi, items in groups.items():
        try:
            line = km[gi].boundary
        except Exception:
            line = None
        if line is None or line.is_empty or line.length <= spacing:
            for idx, npt in items:
                result[idx] = npt
            continue
        try:
            items = sorted(items, key=lambda it: line.project(it[1]))
            ds = [line.project(npt) for _, npt in items]
        except Exception:
            for idx, npt in items:
                result[idx] = npt
            continue
        new = ds[:]
        for i in range(1, len(new)):                      # 左→右
            new[i] = max(new[i], new[i - 1] + spacing)
        for i in range(len(new) - 2, -1, -1):             # 右→左
            new[i] = min(new[i], new[i + 1] - spacing)
        # 整体夹回 [0, length]（簇在端点附近时可能有轻微压缩）
        for i in range(len(new)):
            new[i] = min(max(new[i], 0.0), line.length)
        for (idx, _), d in zip(items, new):
            try:
                result[idx] = line.interpolate(d)
            except Exception:
                result[idx] = items[0][1]
    # 保险：没算到的回退到最近点
    for i, (_p, _gi, npt) in enumerate(snap):
        if result[i] is None:
            result[i] = npt
    return result


def _key(name, kind, lon, lat):
    """唯一键：PLAIN_KINDS 的 name == kind（很多个「码头」），必须带坐标。"""
    return (name, kind, round(float(lon), 6), round(float(lat), 6))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default=DEFAULT_CITY)
    ap.add_argument("--write", action="store_true", help="落盘（默认只报告）")
    args = ap.parse_args()

    world_path, poi_path, world, frozen = _load(args.city)
    km, fwd, inv = _water_km(world)
    tree = STRtree(km)

    # 1) 分类每个水类 POI
    #    选水岸时**优先大水面**（岳阳的岸就是洞庭湖）：分数 = 岸线长 / 距离。
    #    否则一堆船会被吸到城里的几口小塘上，也放不下。
    keep, snap, drop = [], [], []
    for p in frozen["objects"]:
        if p.get("kind") not in WATER_KINDS:
            continue
        pt = transform(fwd, Point(p["lon"], p["lat"]))
        cands = []
        for gi in tree.query(pt.buffer(SNAP_M)):
            g = km[int(gi)]
            try:
                npt = nearest_points(pt, g)[1]
                d = pt.distance(npt)
                L = g.boundary.length
            except Exception:
                continue
            if d <= SNAP_M:
                cands.append((L / (d + 200.0), d, int(gi), npt))
        if not cands:
            drop.append((p, float("inf")))
            continue
        nearest_d = min(c[1] for c in cands)
        if nearest_d <= KEEP_M:
            keep.append(p)
        else:
            cands.sort(key=lambda c: c[0], reverse=True)
            _score, d, gi, npt = cands[0]
            snap.append((p, gi, npt))

    print(f"水域类 POI：岸边不动 {len(keep)} | 吸附 {len(snap)} | 删除 {len(drop)}")
    for p, d in drop:
        dd = ">2km" if d == float("inf") else f"{d/1000:.2f} km"
        print(f"  删除 {p['kind']}「{p['name']}」 离水 {dd}")

    # 2) 沿水岸线铺开
    placed = _spread_on_water(snap, km)
    mind = float("inf")
    for i in range(len(placed)):
        for j in range(i + 1, len(placed)):
            mind = min(mind, placed[i].distance(placed[j]))
    print(f"吸附后最小间距：{mind:.1f} m（目标 ≥ {SPACING_M}）")

    # 3) 生成新坐标（lon/lat），键 = (name, kind, 原坐标) —— 唯一
    new_ll = {}
    for (p, _gi, _npt), q in zip(snap, placed):
        lon, lat = transform(inv, q).x, transform(inv, q).y
        new_ll[_key(p["name"], p["kind"], p["lon"], p["lat"])] = (round(lon, 7), round(lat, 7))
    drop_keys = {_key(p["name"], p["kind"], p["lon"], p["lat"]) for p, _ in drop}

    if not args.write:
        print("\n（干跑，未落盘。加 --write 生效）")
        return

    # 4) 改写冻结表
    n_move = n_drop = 0
    out_pois = []
    for p in frozen["objects"]:
        key = _key(p["name"], p["kind"], p["lon"], p["lat"])
        if key in drop_keys:
            n_drop += 1
            continue
        if key in new_ll:
            p = dict(p, lon=new_ll[key][0], lat=new_ll[key][1])
            n_move += 1
        out_pois.append(p)
    frozen["objects"] = out_pois
    frozen["count"] = len(out_pois)
    with open(poi_path, "w", encoding="utf-8") as f:
        json.dump(frozen, f, ensure_ascii=False, separators=(",", ":"))

    # 5) 改写世界 JSON（键同上；删除的丢掉）
    out_objs = []
    w_move = w_drop = 0
    for o in world["objects"]:
        if o.get("category") == "custom" and o.get("ancient_kind") in WATER_KINDS:
            g = o.get("geometry") or {}
            c = g.get("coordinates") or [None, None]
            key = _key(o.get("name"), o.get("ancient_kind"), c[0], c[1])
            if key in drop_keys:
                w_drop += 1
                continue
            if key in new_ll:
                o = dict(o)
                o["geometry"] = {"type": "Point", "coordinates": [new_ll[key][0], new_ll[key][1]]}
                w_move += 1
        out_objs.append(o)
    world["objects"] = out_objs
    with open(world_path, "w", encoding="utf-8") as f:
        json.dump(world, f, ensure_ascii=False, separators=(",", ":"))

    print(f"\n冻结表：移动 {n_move}、删除 {n_drop} → {poi_path}")
    print(f"世界：  移动 {w_move}、删除 {w_drop} → {world_path}")


if __name__ == "__main__":
    main()
