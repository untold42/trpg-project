# -*- coding: utf-8 -*-
"""
export_clickable.py
===================
从 trpg-map/数据/扬州_南宋世界.json（南宋世界）导出“可点击对象”的严格 GeoJSON，
供前端 react-leaflet <GeoJSON> 使用。

过滤规则：
    - 只含有名字的对象；
    - 去掉整块的行政边界（boundary，多边形巨大又没弹窗意义）；
    - 去掉坐标点过多的巨型要素（防卡）。

用法：
    python export_clickable.py [--input 数据/扬州_南宋世界.json]
                               [--out 输出.geojson]
    # 默认输出到 trpg-client/public/data/clickable.geojson（存在时），
    # 否则输出到当前目录 clickable.geojson。
"""

import argparse
import json
import os

OUTPUT_FILE = "clickable.geojson"

# 数据目录：trpg-map/数据/
DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "数据"
)

INPUT_FILE = os.path.join(DATA_DIR, "扬州_南宋世界.json")

# 前端项目 public 目录（可点击数据放这里）
# 目录布局：<root>/trpg-project/{trpg-map, trpg-client, trpg-server}
# 故 draw_tiles 的上一级(trpg-map)的上一级(trpg-project)下找 trpg-client
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_PUBLIC = os.path.abspath(
    os.path.join(
        os.path.dirname(os.path.dirname(BASE_DIR)),  # -> trpg-project/
        "trpg-client", "public"
    )
)

MAX_POINTS = 50000          # 超过这个坐标数的要素跳过
SKIP_CATEGORIES = {"boundary"}  # 行政边界不参与点击
SKIP_KINDS = {"民居"}          # 民居不进入前端可点层（瓦片上仍显示建筑）

# 输出到 properties 里保留的 tags 子集（避免把整包 tag 全带上）
KEEP_TAG_KEYS = (
    "amenity", "shop", "tourism", "leisure", "historic",
    "place", "highway", "waterway", "building", "natural",
    "landuse", "man_made", "railway",
)

# ============================================================
# kind -> 图标键（对应 public/mapicons/<键>/{day,night}.png，美术自备）
# ============================================================

ICON_BY_KIND = {
    # 行旅
    "客栈": "inn", "邸店": "inn", "驿站": "post", "递铺": "post",
    "渡口": "ferry", "码头": "ferry",
    # 饮食
    "酒楼": "tavern", "酒肆": "tavern", "酒坊": "wine",
    "食铺": "food", "甜食铺": "food",
    "茶肆": "tea", "茶铺": "tea", "饮品铺": "drink",
    # 文教
    "书院": "academy", "蒙馆": "academy", "学舍": "academy",
    "书楼": "library", "藏馆": "museum",
    # 医药
    "医馆": "med", "药铺": "med", "兽医铺": "vet",
    # 商贸
    "钱铺": "money", "市集": "market", "市": "market",
    "杂货铺": "shop", "大市铺": "shop", "百货铺": "shop", "店铺": "shop",
    "衣铺": "shop", "鞋铺": "shop", "书肆": "shop", "文房肆": "shop",
    "菜铺": "shop", "肉铺": "shop", "饼铺": "shop", "首饰铺": "shop",
    "花铺": "shop", "梳洗铺": "shop", "眼镜铺": "shop", "家具铺": "shop",
    "问讯处": "info",
    # 礼制 / 游乐
    "寺观": "temple", "胜迹": "sight", "碑刻": "monument",
    "碑": "monument", "碑坊": "monument", "遗址": "ruin",
    "园苑": "garden", "园": "garden", "旷场": "park",
    "校场": "arena", "瓦舍": "theater", "文会所": "meeting",
    # 官署 / 基建
    "巡检司": "office", "衙门": "office", "府衙": "office",
    "狱": "office", "潜火铺": "fire", "桥": "bridge",
    # 聚落
    "州城": "city", "镇": "town", "村": "village", "坊": "ward",
    "洲": "islet",
    # 山水 / 地类（面要素）
    "水": "water", "江": "river", "河": "river", "溪": "stream",
    "泽": "marsh", "山": "mountain", "林": "forest", "莽": "scrub",
    "草地": "grass", "田": "field", "宅": "house", "民居": "house", "墓地": "grave",
}

ICON_MIN_ZOOM = 15

# 合并南宋词表里的图标映射（新布点：青楼/教坊/画舫/赌坊/当铺等）
from song_kinds import KINDS as SONG_KINDS  # noqa: E402
for _kind, _info in SONG_KINDS.items():
    _icon = _info.get("icon")
    if _icon:
        ICON_BY_KIND.setdefault(_kind, _icon)

# ============================================================
# kind -> 大类 group（弹窗第 2 个徽章用）
#
# 种子来自 song_kinds 的 group（酒楼→饮食、书院→文教…）；
# 词表没覆盖的（茶肆/学舍/官道/镇村…）用下面兜底表补齐。
# ============================================================

GROUP_BY_KIND = {
    _kind: _info.get("group")
    for _kind, _info in SONG_KINDS.items()
    if _info.get("group")
}

GROUP_FALLBACK = {
    # 饮食
    "茶肆": "饮食", "茶铺": "饮食", "饮品铺": "饮食", "甜食铺": "饮食",
    "菜铺": "饮食", "肉铺": "饮食", "饼铺": "饮食",
    # 商市
    "杂货铺": "商市", "大市铺": "商市", "百货铺": "商市", "店铺": "商市",
    "衣铺": "商市", "鞋铺": "商市", "首饰铺": "商市", "花铺": "商市",
    "梳洗铺": "商市", "眼镜铺": "商市", "家具铺": "商市",
    "书肆": "商市", "文房肆": "商市",
    # 文教 / 医 / 官 / 信仰
    "学舍": "文教", "藏馆": "文教", "书楼": "文教",
    "寺观": "信仰", "衙门": "官署", "问讯处": "官署", "校场": "军武",
    # 游乐 / 地标
    "胜迹": "游乐", "遗址": "地标", "碑坊": "地标", "碑刻": "地标",
    "旷场": "游乐", "游乐地": "游乐", "游处": "游乐", "亭": "游乐",
    # 聚落 / 道路 / 地类 / 山水
    "州城": "聚落", "镇": "聚落", "村": "聚落", "坊": "聚落", "市": "聚落",
    "官道": "道路", "县道": "道路", "乡道": "道路", "坊巷": "道路",
    "市巷": "道路", "小径": "道路",
    "水": "地类", "江": "地类", "河": "地类", "溪": "地类",
    "宅": "地类", "地": "地类", "莽": "山水", "山野": "山水",
    "墓地": "礼用", "浴堂": "行旅",
}
for _kind, _group in GROUP_FALLBACK.items():
    GROUP_BY_KIND.setdefault(_kind, _group)


def count_numbers(coords):
    n = 0
    def walk(v):
        nonlocal n
        if isinstance(v, list):
            if v and isinstance(v[0], (int, float)):
                n += 2
            else:
                for x in v:
                    walk(x)
    walk(coords)
    return n


def representative_point(geom):
    """给面要素算一个位于内部的代表点（lon, lat），供前端放图标。
    用 shapely 的 representative_point，保证在面内。
    """
    import shapely.geometry as sg
    shape = sg.shape(geom)
    if shape.is_empty:
        return None
    p = shape.representative_point()
    return (p.x, p.y)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=INPUT_FILE)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    base = os.path.dirname(os.path.abspath(__file__))
    input_path = os.path.join(base, args.input)

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    features = []
    skipped_no_name = 0
    skipped_heavy = 0
    skipped_category = 0
    skipped_kind = 0

    for o in data.get("objects", []):
        name = o.get("name")
        if not name:
            skipped_no_name += 1
            continue

        cat = o.get("category") or ""
        if cat in SKIP_CATEGORIES:
            skipped_category += 1
            continue

        if (o.get("ancient_kind") or "") in SKIP_KINDS:
            skipped_kind += 1
            continue

        geom = o.get("geometry") or {}
        coords = geom.get("coordinates")
        if not coords:
            skipped_no_name += 1
            continue

        if count_numbers(coords) > MAX_POINTS:
            skipped_heavy += 1
            continue

        props = {
            "id": o.get("id"),
            "name": name,
            "kind": o.get("ancient_kind") or "",
            "category": cat,
        }
        _group = GROUP_BY_KIND.get(o.get("ancient_kind"))
        if _group:
            props["group"] = _group
        if o.get("name_modern"):
            props["name_modern"] = o["name_modern"]
        tags = {k: v for k, v in (o.get("tags") or {}).items()
                if k in KEEP_TAG_KEYS}
        if tags:
            props["tags"] = tags

        # 图标键 + 面的代表点（供 zoom>=15 时在地图上放图标）
        icon = ICON_BY_KIND.get(o.get("ancient_kind"))
        gtype = geom.get("type")
        if icon:
            props["icon"] = icon
            if gtype in ("Polygon", "MultiPolygon"):
                rp = representative_point(geom)
                if rp is not None:
                    props["icon_lon"], props["icon_lat"] = rp

        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": props,
        })

    fc = {
        "type": "FeatureCollection",
        "features": features,
    }

    # 决定输出位置
    out_path = args.out
    if out_path is None:
        if os.path.isdir(FRONTEND_PUBLIC):
            out_dir = os.path.join(FRONTEND_PUBLIC, "data")
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, OUTPUT_FILE)
        else:
            out_path = os.path.join(base, OUTPUT_FILE)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=False)

    # ---- 生成“需要绘制的图标清单” ----
    from collections import Counter
    icon_counter = Counter(
        f["properties"].get("icon") for f in features if f["properties"].get("icon")
    )
    manifest_lines = [
        "每栋建筑一个文件夹：public/mapicons/<键>/  里面放 day.png 与 night.png（128x128 透明底）",
        "由 trpg-map/draw_tiles/icongen/make_icons.py 自动生成；缺图会在图上退化成棕色圆点。",
        "",
    ]
    for key, n in icon_counter.most_common():
        manifest_lines.append(f"{key}/day.png + {key}/night.png   (x{n})")

    if os.path.isdir(FRONTEND_PUBLIC):
        icon_dir = os.path.join(FRONTEND_PUBLIC, "mapicons")
        os.makedirs(icon_dir, exist_ok=True)
        mpath = os.path.join(icon_dir, "manifest.txt")
        with open(mpath, "w", encoding="utf-8") as f:
            f.write("\n".join(manifest_lines))
        print("icon manifest:", mpath)
    else:
        with open(os.path.join(base, "mapicons_manifest.txt"), "w",
                  encoding="utf-8") as f:
            f.write("\n".join(manifest_lines))
        print("icon manifest: ./mapicons_manifest.txt")

    print("out:", out_path)
    print("features:", len(features),
          "| 无名跳过:", skipped_no_name,
          "| 超巨型跳过:", skipped_heavy,
          "| boundary跳过:", skipped_category,
          "| 民居跳过:", skipped_kind)
    print("size: %.2f MB" % (os.path.getsize(out_path) / 1048576))
    print("icon keys:", len(icon_counter))


if __name__ == "__main__":
    main()
