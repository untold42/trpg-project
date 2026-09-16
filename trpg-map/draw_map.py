# -*- coding: utf-8 -*-
"""
draw_map.py —— 从 JSON（如 数据/岳阳_OSM全量.json）绘制一幅总览地图 PNG。

用法：
    python draw_map.py 数据/岳阳_OSM全量.json -o 岳阳地图.png
    python draw_map.py 数据/岳阳_OSM全量.json -o 岳阳地图.png --width 2400 --labels all
    python draw_map.py 数据/岳阳_OSM全量.json -o 岳阳地图.png --title "岳阳市全域图"
    python draw_map.py 数据/岳阳_OSM全量.json -o 岳阳地图.png --full          # 用完整范围
    python draw_map.py 数据/岳阳_OSM全量.json -o out.png --bbox 112.4,28.4,114.0,29.8

特点：
  - Web Mercator 投影，自动取景（默认裁掉极少数远处的“尾巴”对象）；
  - 宣纸古风配色，与 draw_tiles/tilegen 一致；
  - 图层顺序：土地 → 水 → 水系线 → 行政边界 → 道路 → 建筑 → 地名；
  - 支持中文地名（用系统 msyh 字体），带描边保证可读。
"""

import argparse
import json
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFont


# ============================================================
# 配色（与 draw_tiles/tilegen/config.py 对齐）
# ============================================================
BACKGROUND = (238, 231, 207)      # 宣纸底
WATER = (168, 194, 201)           # 水面
WATER_LINE = (88, 118, 128)       # 水岸线
RIVER = (88, 118, 128)            # 河道
FOREST = (188, 196, 162)          # 林地
GRASS = (216, 211, 178)           # 草地
FARMLAND = (226, 214, 178)        # 农田
CEMETERY = (203, 199, 180)        # 墓地
BUILDING = (203, 186, 158)        # 建筑
BUILDING_OUT = (150, 130, 102)    # 建筑轮廓
BOUNDARY = (176, 146, 110)        # 行政边界
ROAD_PRIMARY = (150, 88, 56)      # 主干道
ROAD_SECONDARY = (172, 118, 80)   # 次干道
ROAD_TERTIARY = (194, 156, 116)   # 支路
ROAD_MINOR = (208, 184, 150)      # 更小的路
INK = (66, 54, 40)                # 墨色
INK_SOFT = (120, 104, 82)         # 淡墨
LABEL_CITY = (52, 40, 28)
LABEL_DIST = (86, 70, 52)
LABEL_TOWN = (118, 100, 78)
HIGHLIGHT = (176, 42, 42)       # 标注高亮（朱砂红）
REGION_COLOR = (120, 48, 120)   # 应有范围虚线框（紫）


def el(tags, key):
    return tags.get(key)


# ============================================================
# 投影：Web Mercator，返回 [0,1] 归一化坐标
# ============================================================
def project(lon, lat):
    lat = max(min(lat, 85.05112878), -85.05112878)
    x = (lon + 180.0) / 360.0
    y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0
    return x, y


# ============================================================
# 几何迭代
# ============================================================
def iter_polygons(geom):
    """yield 每个多边形 = [外环, 内环...]，坐标为 [lon,lat] 列表。"""
    t = geom.get("type")
    if t == "Polygon":
        yield geom["coordinates"]
    elif t == "MultiPolygon":
        for poly in geom["coordinates"]:
            yield poly


def iter_lines(geom):
    t = geom.get("type")
    if t == "LineString":
        yield geom["coordinates"]
    elif t == "MultiLineString":
        yield geom["coordinates"]
    elif t == "Polygon":
        for ring in geom["coordinates"]:
            yield ring
    elif t == "MultiPolygon":
        for poly in geom["coordinates"]:
            for ring in poly:
                yield ring


def collect_points(geom):
    """遍历几何所有 [lon,lat]。"""
    t = geom.get("type")
    if t == "Point":
        yield geom["coordinates"]
    elif t == "LineString":
        for p in geom["coordinates"]:
            yield p
    elif t == "MultiLineString":
        for line in geom["coordinates"]:
            for p in line:
                yield p
    elif t == "Polygon":
        for ring in geom["coordinates"]:
            for p in ring:
                yield p
    elif t == "MultiPolygon":
        for poly in geom["coordinates"]:
            for ring in poly:
                for p in ring:
                    yield p


def percentile(sorted_list, p):
    if not sorted_list:
        return 0.0
    return sorted_list[int(p * (len(sorted_list) - 1))]


# ============================================================
# 字体 & 文字
# ============================================================
_FONT_CACHE = {}


def load_font(size):
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]
    font = None
    for path in (r"C:\Windows\Fonts\msyh.ttc",
                 r"C:\Windows\Fonts\simhei.ttf",
                 r"C:\Windows\Fonts\simsun.ttc",
                 "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
                 "/System/Library/Fonts/PingFang.ttc"):
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, size)
                break
            except Exception:
                pass
    if font is None:
        font = ImageFont.load_default()
    _FONT_CACHE[size] = font
    return font


def draw_text(draw, xy, text, font, fill, halo=BACKGROUND, width=2):
    """带描边的文字。"""
    x, y = xy
    for dx in range(-width, width + 1):
        for dy in range(-width, width + 1):
            if dx == 0 and dy == 0:
                continue
            draw.text((x + dx, y + dy), text, font=font, fill=halo)
    draw.text((x, y), text, font=font, fill=fill)


def draw_dashed_rect(draw, x0, y0, x1, y1, color, width=3, dash=16, gap=10):
    """画虚线矩形。"""
    def hline(y):
        p = x0
        while p < x1:
            q = min(p + dash, x1)
            draw.line([(p, y), (q, y)], fill=color, width=width)
            p += dash + gap

    def vline(x):
        p = y0
        while p < y1:
            q = min(p + dash, y1)
            draw.line([(x, p), (x, q)], fill=color, width=width)
            p += dash + gap

    hline(y0)
    hline(y1)
    vline(x0)
    vline(x1)


# ============================================================
# 土地配色
# ============================================================
def land_color(tags):
    landuse = el(tags, "landuse")
    natural = el(tags, "natural")
    leisure = el(tags, "leisure")
    if landuse in ("forest",) or natural == "wood":
        return FOREST
    if landuse in ("farmland", "farmyard", "plant_nursery", "orchard", "vineyard"):
        return FARMLAND
    if landuse == "cemetery":
        return CEMETERY
    if landuse in ("grass", "meadow", "recreation_ground", "village_green",
                   "flowerbed") or leisure in ("park", "garden", "common",
                                               "pitch", "nature_reserve"):
        return GRASS
    if natural in ("scrub", "wetland", "grassland", "heath"):
        return FOREST
    return GRASS


# ============================================================
# 主绘制
# ============================================================
def build_map(data, out_path, width=2400, margin_frac=0.04, title=None,
              labels="major", bbox=None, full=False, trim=(0.01, 0.99),
              min_area_px=1.0, annotate=None, regions=None):
    objects = data.get("objects", [])

    # ---- 1. 遍历一次：收集顶点 bbox + 每个对象中心 ----
    min_lon = min_lat = float("inf")
    max_lon = max_lat = float("-inf")
    centers = []
    for o in objects:
        geom = o.get("geometry") or {}
        if not geom.get("type"):
            continue
        o_minx = o_miny = float("inf")
        o_maxx = o_maxy = float("-inf")
        for lon, lat in collect_points(geom):
            if lon < min_lon: min_lon = lon
            if lon > max_lon: max_lon = lon
            if lat < min_lat: min_lat = lat
            if lat > max_lat: max_lat = lat
            if lon < o_minx: o_minx = lon
            if lon > o_maxx: o_maxx = lon
            if lat < o_miny: o_miny = lat
            if lat > o_maxy: o_maxy = lat
        if o_minx != float("inf"):
            centers.append(((o_minx + o_maxx) / 2, (o_miny + o_maxy) / 2))

    if bbox is not None:
        view = list(bbox)
    elif full:
        view = [min_lon, min_lat, max_lon, max_lat]
    else:
        # 用对象中心的百分位 bbox，裁掉极少数远处尾巴
        lons = sorted(c[0] for c in centers)
        lats = sorted(c[1] for c in centers)
        view = [percentile(lons, trim[0]), percentile(lats, trim[0]),
                percentile(lons, trim[1]), percentile(lats, trim[1])]

    # ---- 2. 归一化投影 + 留白 ----
    x1, y1 = project(view[0], view[3])   # 左上
    x2, y2 = project(view[2], view[1])   # 右下
    span_x = (x2 - x1) * (1 + 2 * margin_frac)
    span_y = (y2 - y1) * (1 + 2 * margin_frac)
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    x1, x2 = cx - span_x / 2, cx + span_x / 2
    y1, y2 = cy - span_y / 2, cy + span_y / 2

    scale = width / span_x
    height = int(round(span_y * scale))
    header = 74 if title else 0
    canvas_h = height + header + 56

    def to_px(lon, lat):
        px, py = project(lon, lat)
        return ((px - x1) * scale, (py - y1) * scale + header)

    img = Image.new("RGB", (width, canvas_h), BACKGROUND)
    draw = ImageDraw.Draw(img, "RGBA")

    # ---- 3. 分类图层 ----
    water_polys, land_polys = [], []
    water_lines, roads = [], []
    boundaries, buildings = [], []
    label_pts = []

    for o in objects:
        tags = o.get("tags") or {}
        geom = o.get("geometry") or {}
        cat = o.get("category")
        if not geom.get("type"):
            continue
        gt = geom["type"]
        is_water_tag = (el(tags, "natural") == "water" or bool(el(tags, "water")))

        if (cat == "water" or is_water_tag) and gt in ("Polygon", "MultiPolygon"):
            water_polys.append(geom)
        elif cat == "waterway" or el(tags, "waterway") or (is_water_tag and gt in ("LineString", "MultiLineString")):
            water_lines.append(geom)
        elif cat == "boundary" or el(tags, "boundary") == "administrative":
            boundaries.append(geom)
        elif cat == "road" or el(tags, "highway"):
            roads.append((geom, el(tags, "highway")))
        elif cat == "building" or el(tags, "building"):
            buildings.append((geom, tags))
        elif cat in ("landuse", "natural", "leisure", "poi_area", "area",
                     "tourism", "historic"):
            land_polys.append((geom, tags))
        elif cat == "place" or el(tags, "place"):
            if o.get("name") and geom.get("type") == "Point":
                place = el(tags, "place")
                rank = {"city": 0, "county": 1, "district": 1,
                        "suburb": 2, "town": 2, "village": 3}.get(place, 4)
                label_pts.append((geom["coordinates"], o["name"], rank))

    def draw_poly(geom, fill, outline=None, outline_w=1, min_area=min_area_px,
                  outline_min_px=0):
        for poly in iter_polygons(geom):
            if not poly:
                continue
            outer = [to_px(lon, lat) for lon, lat in poly[0]]
            if len(outer) < 3:
                continue
            xs = [p[0] for p in outer]; ys = [p[1] for p in outer]
            wid = max(xs) - min(xs)
            hei = max(ys) - min(ys)
            if wid * hei < min_area:
                continue
            if outline is not None and wid >= outline_min_px and hei >= outline_min_px:
                draw.polygon(outer, fill=fill, outline=outline, width=outline_w)
            else:
                draw.polygon(outer, fill=fill)
            for inner in poly[1:]:
                ipts = [to_px(lon, lat) for lon, lat in inner]
                if len(ipts) >= 3:
                    draw.polygon(ipts, fill=BACKGROUND)

    # ---- 4. 逐层绘制 ----
    for geom, tags in land_polys:
        draw_poly(geom, land_color(tags), min_area=3)

    for geom in water_polys:
        draw_poly(geom, WATER, outline=WATER_LINE, outline_w=1, min_area=3,
                  outline_min_px=14)

    for geom in water_lines:
        for line in iter_lines(geom):
            pts = [to_px(lon, lat) for lon, lat in line]
            if len(pts) >= 2:
                draw.line(pts, fill=RIVER, width=2, joint="curve")

    # 行政边界：半透明细虚线
    for geom in boundaries:
        for line in iter_lines(geom):
            pts = [to_px(lon, lat) for lon, lat in line]
            if len(pts) < 2:
                continue
            for i in range(0, len(pts) - 1, 2):
                draw.line(pts[i:i + 2], fill=BOUNDARY, width=1)

    # 道路
    road_width = {"primary": 3, "secondary": 2, "tertiary": 1,
                  "unclassified": 1, "residential": 1, "living_street": 1}
    road_color = {"primary": ROAD_PRIMARY, "secondary": ROAD_SECONDARY,
                  "tertiary": ROAD_TERTIARY}
    for geom, hw in roads:
        if labels == "major" and hw in ("residential", "unclassified", "living_street"):
            continue
        w = road_width.get(hw, 1)
        col = road_color.get(hw, ROAD_MINOR)
        for line in iter_lines(geom):
            pts = [to_px(lon, lat) for lon, lat in line]
            if len(pts) >= 2:
                draw.line(pts, fill=col, width=w, joint="curve")

    # 建筑：仅 --labels all 时绘制（总览图太密会糊）
    if labels == "all":
        for geom, tags in buildings:
            draw_poly(geom, BUILDING, outline=None, min_area=0.6)

    # ---- 5. 地名标注 ----
    big = width >= 2000
    font_city = load_font(30 if big else 22)
    font_dist = load_font(24 if big else 18)
    font_town = load_font(17 if big else 14)

    seen = {}
    for coord, name, rank in label_pts:
        if labels == "major" and rank > 1:
            continue
        if name not in seen or rank < seen[name][2]:
            seen[name] = (coord, name, rank)

    placed = []
    for coord, name, rank in sorted(seen.values(), key=lambda t: t[2]):
        px, py = to_px(coord[0], coord[1])
        if not (0 <= px <= width and header <= py <= canvas_h):
            continue
        if any(abs(px - qx) < 90 and abs(py - qy) < 28 for qx, qy in placed):
            continue
        placed.append((px, py))
        if rank <= 1:
            font, color = font_city, LABEL_CITY
        elif rank == 2:
            font, color = font_dist, LABEL_DIST
        else:
            font, color = font_town, LABEL_TOWN
        tw = draw.textlength(name, font=font)
        draw_text(draw, (px - tw / 2, py + 5), name, font, color)

    # ---- 6. 指定名称标注（--annotate） ----
    if annotate:
        af = load_font(36 if big else 24)
        for o in objects:
            if (o.get("name") or "") not in annotate:
                continue
            geom = o.get("geometry") or {}
            gt = geom.get("type")
            anchor = None
            if gt in ("Polygon", "MultiPolygon"):
                for poly in iter_polygons(geom):
                    pts = [to_px(lon, lat) for lon, lat in poly[0]]
                    if len(pts) >= 3:
                        draw.line(pts + [pts[0]], fill=HIGHLIGHT, width=4, joint="curve")
                try:
                    from shapely.geometry import shape as _shape
                    rp = _shape(geom).representative_point()
                    anchor = to_px(rp.x, rp.y)
                except Exception:
                    allp = [p for poly in iter_polygons(geom) for p in poly[0]]
                    if allp:
                        anchor = to_px(sum(p[0] for p in allp) / len(allp),
                                       sum(p[1] for p in allp) / len(allp))
            elif gt in ("LineString", "MultiLineString"):
                first = None
                for line in iter_lines(geom):
                    pts = [to_px(lon, lat) for lon, lat in line]
                    if len(pts) >= 2:
                        draw.line(pts, fill=HIGHLIGHT, width=4, joint="curve")
                        if first is None:
                            first = line[len(line) // 2]
                if first:
                    anchor = to_px(first[0], first[1])
            elif gt == "Point":
                anchor = to_px(geom["coordinates"][0], geom["coordinates"][1])

            if anchor:
                ax, ay = anchor
                draw.ellipse([ax - 9, ay - 9, ax + 9, ay + 9],
                             fill=HIGHLIGHT, outline=BACKGROUND, width=3)
                txt = o.get("name") or ""
                lx, ly = ax + 16, ay - 12
                draw.line([(ax + 9, ay), (lx + 4, ly + 14)], fill=HIGHLIGHT, width=2)
                draw_text(draw, (lx, ly), txt, af, HIGHLIGHT, halo=BACKGROUND, width=3)

    # ---- 7. 应有范围虚线框（--region） ----
    for rb, caption in (regions or []):
        x0, y0 = to_px(rb[0], rb[3])
        x1, y1 = to_px(rb[2], rb[1])
        draw_dashed_rect(draw, x0, y0, x1, y1, REGION_COLOR, width=3)
        if caption:
            rf = load_font(26 if big else 18)
            cx = min(max(x0 + 8, 8), max(width - 320, 8))
            cy = min(max(y0 + 8, header + 8), canvas_h - 40)
            draw_text(draw, (cx, cy), caption, rf, REGION_COLOR,
                      halo=BACKGROUND, width=2)

    # ---- 8. 比例尺 / 指北针 / 标题 / 边框 ----
    center_lat = (view[1] + view[3]) / 2
    km_per_px = (360.0 * 111.32 * math.cos(math.radians(center_lat))) / scale
    target_km = 10
    for cand in (50, 20, 10, 5):
        if cand / km_per_px <= width * 0.28:
            target_km = cand
            break
    bar_px = target_km / km_per_px
    bx = width - 70 - bar_px
    by = canvas_h - 44
    sf = load_font(20 if big else 15)
    draw.line([(bx, by), (bx + bar_px, by)], fill=INK, width=4)
    for xx in (bx, bx + bar_px):
        draw.line([(xx, by - 9), (xx, by + 9)], fill=INK, width=4)
    label = f"{target_km} km"
    lw = draw.textlength(label, font=sf)
    draw_text(draw, (bx + bar_px / 2 - lw / 2, by - 34), label, sf, INK)

    # 指北针
    nx = width - 66
    ny = header + 54
    draw.polygon([(nx, ny - 30), (nx - 11, ny + 10), (nx, ny + 2), (nx + 11, ny + 10)],
                 fill=INK)
    nf = load_font(22 if big else 16)
    nw = draw.textlength("N", font=nf)
    draw_text(draw, (nx - nw / 2, ny + 14), "N", nf, INK)

    if title:
        tfont = load_font(40 if big else 28)
        tw = draw.textlength(title, font=tfont)
        draw_text(draw, ((width - tw) / 2, 16), title, tfont, INK, width=2)

    draw.rectangle([2, 2, width - 3, canvas_h - 3], outline=INK_SOFT, width=3)

    img.save(out_path)
    print(f"已生成: {out_path}  ({width}x{canvas_h})  view={view}")
    return out_path


def parse_bbox(s):
    parts = [float(x) for x in s.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("bbox 需要 4 个数：min_lon,min_lat,max_lon,max_lat")
    return parts


def parse_region(s):
    """格式：min_lon,min_lat,max_lon,max_lat|标题"""
    if "|" in s:
        bbox_s, caption = s.split("|", 1)
    else:
        bbox_s, caption = s, ""
    return (parse_bbox(bbox_s), caption)


def main():
    ap = argparse.ArgumentParser(description="从 JSON 绘制总览地图 PNG")
    ap.add_argument("input", help="输入的 JSON 文件（如 数据/岳阳_OSM全量.json）")
    ap.add_argument("-o", "--output", default="map.png", help="输出 PNG 路径")
    ap.add_argument("--width", type=int, default=2400, help="输出宽度像素（默认 2400）")
    ap.add_argument("--margin", type=float, default=0.04, help="四周留白比例（默认 0.04）")
    ap.add_argument("--title", default=None, help="地图标题")
    ap.add_argument("--labels", choices=["none", "major", "all"], default="major",
                    help="地名标注级别：none/major/all（默认 major）")
    ap.add_argument("--full", action="store_true", help="使用完整数据范围（含远处尾巴）")
    ap.add_argument("--bbox", type=parse_bbox, default=None,
                    help="手动指定范围：min_lon,min_lat,max_lon,max_lat")
    ap.add_argument("--annotate", default=None,
                    help="高亮标注指定名称（逗号分隔），如 --annotate 洞庭湖")
    ap.add_argument("--region", type=parse_region, action="append", default=None,
                    help="画虚线框标注区域，格式 min_lon,min_lat,max_lon,max_lat|标题，可重复")
    args = ap.parse_args()

    if not os.path.exists(args.input):
        print(f"错误：找不到 {args.input}", file=sys.stderr)
        sys.exit(1)

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    annotate = None
    if args.annotate:
        annotate = {x.strip() for x in args.annotate.split(",") if x.strip()}

    build_map(data, args.output, width=args.width, margin_frac=args.margin,
              title=args.title, labels=args.labels, bbox=args.bbox, full=args.full,
              annotate=annotate, regions=args.region)


if __name__ == "__main__":
    main()
