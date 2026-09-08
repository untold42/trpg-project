# -*- coding: utf-8 -*-
"""
build_world.py
==============
南宋扬州世界生成器（推翻现代 OSM 城区，只保留自然地理 + 史实锚点，其余算法生成）。

数据流：
    map_ancient_center.json (OSM 原始) ─┐
    custom_ancient.json   (76 布点锚点) ─┼─► build_world.py
                                         └─► map_ancient_song.json（同名覆盖，下游零改动）

生成顺序（--stage 控制）：
    1 = 保留层(自然地理+锚点) + 城墙/城门 + 老城道路 + 坊面层
    2 = + 坊内民居矩形
    3 = + POI 布点 + 城外官道/聚落（完整）

用法：
    python build_world.py --stage 1
    python build_world.py              # 完整
"""

import argparse
import json
import math
import os
import random

from shapely.geometry import (
    Point, LineString, Polygon, MultiPolygon, box as shp_box,
)
from shapely.ops import unary_union

from song_kinds import KINDS as SONG_KINDS

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE_FILE = os.path.join(BASE_DIR, "map_ancient_center.json")
CUSTOM_FILE = os.path.join(BASE_DIR, "custom_ancient.json")
OUTPUT_FILE = os.path.join(BASE_DIR, "map_ancient_song.json")

SEED = 42

# ----------------------------------------------------------------------
# 投影：局部等距（米制），中心取画框中心
# ----------------------------------------------------------------------
PROJ_LON0 = 119.4175
PROJ_LAT0 = 32.41
M_PER_DEG_LAT = 110574.0


def _m_per_deg_lon(lat):
    return 111320.0 * math.cos(math.radians(lat))


def lonlat_to_xy(lon, lat):
    return (
        (lon - PROJ_LON0) * _m_per_deg_lon(PROJ_LAT0),
        (lat - PROJ_LAT0) * M_PER_DEG_LAT,
    )


def xy_to_lonlat(x, y):
    return (
        PROJ_LON0 + x / _m_per_deg_lon(PROJ_LAT0),
        PROJ_LAT0 + y / M_PER_DEG_LAT,
    )


def xy_geom_to_geojson(g):
    """把米制 shapely 几何转成 lon/lat GeoJSON geometry dict。"""
    if g is None or g.is_empty:
        return None
    t = g.geom_type
    if t == "Point":
        lon, lat = xy_to_lonlat(g.x, g.y)
        return {"type": "Point", "coordinates": [round(lon, 7), round(lat, 7)]}
    if t == "LineString":
        return {"type": "LineString",
                "coordinates": [[round(xy_to_lonlat(x, y)[0], 7),
                                 round(xy_to_lonlat(x, y)[1], 7)]
                                for x, y in g.coords]}
    if t == "Polygon":
        outer = [[round(xy_to_lonlat(x, y)[0], 7),
                  round(xy_to_lonlat(x, y)[1], 7)]
                 for x, y in g.exterior.coords]
        inners = [[[round(xy_to_lonlat(x, y)[0], 7),
                    round(xy_to_lonlat(x, y)[1], 7)]
                   for x, y in r.coords] for r in g.interiors]
        return {"type": "Polygon", "coordinates": [outer] + inners}
    if t == "MultiPolygon":
        polys = []
        for p in g.geoms:
            outer = [[round(xy_to_lonlat(x, y)[0], 7),
                      round(xy_to_lonlat(x, y)[1], 7)]
                     for x, y in p.exterior.coords]
            inners = [[[round(xy_to_lonlat(x, y)[0], 7),
                        round(xy_to_lonlat(x, y)[1], 7)]
                       for x, y in r.coords] for r in p.interiors]
            polys.append([outer] + inners)
        return {"type": "MultiPolygon", "coordinates": polys}
    if t == "MultiLineString":
        return {"type": "MultiLineString",
                "coordinates": [[[round(xy_to_lonlat(x, y)[0], 7),
                                  round(xy_to_lonlat(x, y)[1], 7)]
                                 for x, y in line.coords] for line in g.geoms]}
    return None


# ----------------------------------------------------------------------
# 城市几何常量（据真实 OSM 锚点量取）
# ----------------------------------------------------------------------
CENTER_LON = 119.4282   # 文昌阁
CENTER_LAT = 32.3964

# 老城核心区（护城河/小秦淮河/古运河/挹江门 围合，约 2.3×2.3 km）
OLD_CITY_BBOX = (119.4245, 32.3835, 119.4485, 32.4045)

CONTENT_RADIUS_M = 30000.0   # 30km

# ----------------------------------------------------------------------
# 命名
# ----------------------------------------------------------------------
_PREFIX_A = [
    "福", "瑞", "泰", "永", "广", "长", "顺", "德", "庆", "祥",
    "安", "昌", "春", "清", "文", "金", "义", "和", "聚", "兴",
    "万", "同", "景", "崇", "承", "怀", "通", "元", "升", "正",
    "开", "迎", "双", "桂", "莲", "梅", "竹", "仁", "善", "乐",
    "观", "务", "敦", "积", "康",
]
_PREFIX_B = [
    "来", "祥", "和", "昌", "聚", "兴", "安", "盛", "丰", "瑞",
    "泰", "隆", "熙", "华", "玉", "顺", "德", "宁", "平", "乐",
    "济", "福", "元", "景", "成", "源", "茂", "发", "通", "义",
]
PREFIX2 = [a + b for a in _PREFIX_A for b in _PREFIX_B]

WARD_NAMES = [
    "太平坊", "仁丰坊", "开明坊", "甘泉坊", "东关坊", "通泗坊",
    "大东门坊", "小东门坊", "湾子坊", "彩衣坊", "文峰坊", "琼花坊",
    "广陵坊", "汶河坊", "盐阜坊", "便益门坊", "徐凝门坊", "南河下坊",
    "梅岭坊", "竹西坊", "皮市坊", "教场坊", "辕门坊", "御码头坊",
    "莲花坊", "双桂坊", "崇儒坊", "崇俭坊", "务本坊", "观德坊",
    "清宁坊", "敦化坊", "乐善坊", "兴仁坊", "积善坊", "迎恩坊",
]

# 老城历史街巷改名（现代名 -> 南宋名）
ROAD_RENAME = {
    "四望亭路": "四望亭街", "国庆路": "国庆街", "大东门街": "大东门街",
    "彩衣街": "彩衣街", "徐凝门路": "徐凝门街", "汶河北路": "汶河街",
    "汶河南路": "汶河街", "泰州路": "泰州街", "甘泉路": "甘泉街",
    "盐阜东路": "盐阜街", "盐阜西路": "盐阜街", "通泗街": "通泗街",
    "便益门大街": "便益门大街", "北门外大街": "北门外大街",
    "广陵路": "广陵街", "竹西路": "竹西街", "梅岭西路": "梅岭街",
    "文昌中路": "文昌街", "文昌西路": "文昌街", "文昌东路": "文昌街",
    "江阳中路": "江阳街", "江阳西路": "江阳街", "文汇西路": "文汇街",
    "维扬路": "维扬街", "史可法路": "史可法街", "高桥路": "高桥街",
}

# 史实锚点 name -> 南宋 kind
ANCHOR_KIND = {
    "文昌阁": "高台", "鼓楼": "钟鼓楼", "四望亭": "亭", "五亭桥": "桥",
    "文峰塔": "高台", "天宁塔": "高台", "琼花观": "观", "个园": "园苑",
    "何园": "园苑", "瘦西湖": "湖", "东关古渡": "渡口",
    "北门遗址": "城门", "挹江门": "城门", "隋炀帝陵遗址博物馆": "义冢",
    "崔致远纪念馆": "祠", "朱自清故居": "民居", "张若虚雕塑": "高台",
    # 史实景点补充（避免 tourism/historic 白名单化时被误删）
    "汪氏小苑": "民居", "小盘谷": "园", "小金山": "园",
    "熙春台": "高台", "钓鱼台": "亭", "仪征联营墓葬群": "义冢",
}

# 现代设施名称标记：landuse/natural 保留层若名字命中则丢弃。
# tourism/historic 已走 ANCHOR_KIND 白名单，无需此表。
MODERN_NAME_MARKERS = (
    "酒店", "宾馆", "旅馆", "招待所", "旅舍", "青年旅",
    "博物馆", "会议中心", "服务中心", "游客服务", "咨询服务",
    "大学", "校区", "操场", "球场", "试验田", "校友", "晚报",
    "公园", "湿地", "风景区", "梦幻", "碉堡", "教育馆", "纪念亭",
    "母校", "感恩", "师恩", "圣像", "校徽", "示意图",
)


def _is_modern_name(name):
    return any(m in name for m in MODERN_NAME_MARKERS)

# 官署 / 城防 / 礼用等直接以 kind 为名（不加前缀）
PLAIN_KINDS = {
    "州衙", "县衙", "巡检司", "牢狱", "粮仓", "税场", "城门", "城楼",
    "钟鼓楼", "望火楼", "更房", "城隍庙", "土地庙", "义冢", "坟地",
    "渡口", "码头", "浮桥", "桥", "园苑", "高台", "瓦舍", "勾栏",
    "戏台", "书场", "市集", "镖行", "惠民药局",
}

# 坊名池：先保留 36 个专名，再用两字吉祥字根组合出更多（供 165 坊用）
_WARD_SEQ = None
_WARD_NUM = 0
WARD_STEM_A = [
    "太", "永", "安", "长", "庆", "和", "兴", "仁", "义", "崇",
    "德", "文", "武", "清", "宁", "甘", "广", "琼", "梅", "竹",
    "通", "彩", "东", "西", "南", "北", "双", "桂", "莲", "迎",
    "福", "泰", "顺", "昌", "隆", "景", "承", "怀", "乐", "善",
    "观", "务", "敦", "积", "正", "开",
]
WARD_STEM_B = [
    "平", "仁", "丰", "明", "泉", "关", "泗", "门", "子", "衣",
    "峰", "花", "陵", "河", "阜", "益", "凝", "下", "岭", "市",
    "场", "辕", "头", "桂", "儒", "俭", "本", "德", "宁", "化",
    "善", "恩", "阳", "安",
]

# ----------------------------------------------------------------------
# POI 布点权重（只允许 song_kinds 里存在的 kind）
# ----------------------------------------------------------------------
ZONE_POOLS = {
    "core": {
        "酒楼": 6, "酒肆": 5, "茶坊": 5, "食铺": 4, "饼铺": 2,
        "客栈": 4, "邸店": 2, "钱铺": 3, "金银铺": 3, "当铺": 3,
        "绸缎庄": 3, "布行": 2, "绣坊": 2, "书坊": 2, "医馆": 3,
        "药铺": 3, "青楼": 3, "教坊": 2, "瓦舍": 2, "勾栏": 2,
        "戏台": 2, "书场": 2, "棋馆": 2, "赌坊": 2, "算命摊": 2,
        "香烛铺": 2, "州衙": 1, "县衙": 1, "巡检司": 2, "牢狱": 1,
        "书院": 2, "蒙馆": 2, "城隍庙": 1, "土地庙": 2, "高台": 1,
        "园": 2, "市集": 2, "州学": 1, "藏书楼": 1, "惠民药局": 1,
    },
    "water": {
        "画舫": 5, "码头": 4, "渡口": 4, "鱼行": 3, "船行": 2,
        "染坊": 2, "浮桥": 2, "桥": 3, "酒肆": 2, "食铺": 2, "茶坊": 2,
    },
    "general": {
        "酒肆": 3, "茶坊": 4, "食铺": 4, "饼铺": 3, "客栈": 4,
        "药铺": 3, "医馆": 3, "粮行": 2, "绸缎庄": 2, "布行": 2,
        "书坊": 2, "铁匠铺": 2, "木匠行": 2, "磨坊": 2, "油坊": 1,
        "豆腐坊": 1, "酱园": 1, "酒坊": 2, "寺": 2, "观": 2, "祠": 2,
        "土地庙": 2, "蒙馆": 2, "武馆": 1, "车马行": 1, "马厩": 1,
        "递铺": 1, "桥": 2, "园": 1, "书场": 1, "棋馆": 1, "市集": 2,
        "绣坊": 1, "织坊": 1,
    },
    "edge": {
        "驿站": 3, "递铺": 3, "车马行": 3, "马厩": 2, "棺材铺": 2,
        "纸扎铺": 2, "义冢": 2, "坟地": 2, "寺": 2, "观": 2, "祠": 1,
        "磨坊": 2, "油坊": 2, "豆腐坊": 1, "酒坊": 2, "染坊": 1,
        "客栈": 2, "渡口": 2, "码头": 1, "镖行": 1,
    },
}

# 城外官道连接的聚落（取自源 OSM place 点）
TOWNS = [
    "瓜洲镇", "邵伯镇", "湾头镇", "仪征市", "江都区", "槐泗镇",
    "施桥镇", "杭集镇", "蒋王街道", "西湖街道", "汊河街道", "头桥镇",
    "八里镇", "李典镇", "泰安镇", "新集镇", "朴席镇", "甘泉街道",
]

# ----------------------------------------------------------------------
# 几何小工具
# ----------------------------------------------------------------------

def bbox_polygon(lon_min, lat_min, lon_max, lat_max):
    """lon/lat bbox -> 米制 Polygon"""
    x1, y1 = lonlat_to_xy(lon_min, lat_min)
    x2, y2 = lonlat_to_xy(lon_max, lat_max)
    return shp_box(min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))


def rounded_rect(bbox_xy, corner_m):
    """把 bbox 做成带切角的近似圆角矩形（米制 Polygon）。"""
    minx, miny, maxx, maxy = bbox_xy.bounds
    c = min(corner_m, (maxx - minx) / 2, (maxy - miny) / 2)
    pts = [
        (minx + c, miny), (maxx - c, miny), (maxx, miny + c),
        (maxx, maxy - c), (maxx - c, maxy), (minx + c, maxy),
        (minx, maxy - c), (minx, miny + c),
    ]
    return Polygon(pts)


def rect_poly(cx, cy, w, h, ang=0.0):
    c, s = math.cos(ang), math.sin(ang)
    corners = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
    return Polygon([(cx + px * c - py * s, cy + px * s + py * c)
                    for px, py in corners])


def dist_m(p, q):
    return math.hypot(p.x - q.x, p.y - q.y)


# ----------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------

class WorldBuilder:
    def __init__(self, stage=3, seed=SEED):
        self.stage = stage
        self.rng = random.Random(seed)
        self.objects = []
        self._next_id = -1
        self._used_ids = set()
        self.core_poly = None       # 米制
        self.zicheng_poly = None
        self.water_geom = None      # 米制 union
        self.water_features = []    # 米制 water 线/面（供画舫贴岸）
        self.center_xy = lonlat_to_xy(CENTER_LON, CENTER_LAT)

    # ---------------- id ----------------
    def new_id(self):
        while self._next_id in self._used_ids:
            self._next_id -= 1
        self._used_ids.add(self._next_id)
        i = self._next_id
        self._next_id -= 1
        return i

    # ---------------- 1. 保留层 ----------------
    def load_keep_objects(self):
        with open(SOURCE_FILE, "r", encoding="utf-8") as f:
            src = json.load(f)
        keep = []
        water_geoms = []
        for o in src.get("objects", []):
            cat = o.get("category")
            tags = o.get("tags") or {}
            name = o.get("name")
            if cat in ("water", "waterway"):
                keep.append(o)
                self._collect_water(o, water_geoms)
            elif cat == "natural":
                if name and _is_modern_name(name):
                    continue
                keep.append(o)
                self._collect_water(o, water_geoms)
            elif cat == "landuse" and tags.get("landuse") in (
                "farmland", "forest", "wood", "grass", "meadow",
                "cemetery", "recreation_ground", "village_green",
            ):
                if name and _is_modern_name(name):
                    continue
                keep.append(o)
            elif name and cat in ("historic", "tourism"):
                kind = ANCHOR_KIND.get(name)
                if kind:
                    o = dict(o)
                    o["ancient_kind"] = kind
                    keep.append(o)
            elif name and cat == "place" and tags.get("place") in (
                "town", "village", "hamlet", "suburb", "neighbourhood",
            ):
                o = dict(o)
                p = tags.get("place")
                o["ancient_kind"] = "镇" if p in ("town",) else "村"
                keep.append(o)
        # 76 布点锚点
        if os.path.exists(CUSTOM_FILE):
            with open(CUSTOM_FILE, "r", encoding="utf-8") as f:
                custom = json.load(f)
            for item in custom.get("objects", []):
                keep.append({
                    "id": item.get("id", self.new_id()),
                    "name": item.get("name"),
                    "category": "custom",
                    "geometry": {"type": "Point",
                                 "coordinates": [item["lon"], item["lat"]]},
                    "tags": {},
                    "ancient_kind": item.get("kind"),
                })
        self.water_geom = unary_union(water_geoms) if water_geoms else None
        self._used_ids = {o.get("id") for o in keep if o.get("id")}
        self._next_id = min([0] + [i for i in self._used_ids if i < 0]) - 1
        print("保留层对象:", len(keep), " 水几何:", len(water_geoms))
        return keep

    def _collect_water(self, o, out):
        g = o.get("geometry") or {}
        gt = g.get("type")
        try:
            if gt == "Polygon":
                shp = Polygon([lonlat_to_xy(x, y) for x, y in g["coordinates"][0]])
                out.append(shp)
                self.water_features.append(shp)
            elif gt == "MultiPolygon":
                for poly in g["coordinates"]:
                    shp = Polygon([lonlat_to_xy(x, y) for x, y in poly[0]])
                    out.append(shp)
                    self.water_features.append(shp)
            elif gt == "LineString":
                shp = LineString([lonlat_to_xy(x, y) for x, y in g["coordinates"]])
                out.append(shp.buffer(12.0))
                self.water_features.append(shp)
            elif gt == "MultiLineString":
                for line in g["coordinates"]:
                    shp = LineString([lonlat_to_xy(x, y) for x, y in line])
                    out.append(shp.buffer(12.0))
                    self.water_features.append(shp)
        except Exception:
            pass

    # ---------------- 2. 城墙 / 城门 ----------------
    def build_wall(self):
        objs = []
        self.core_poly = rounded_rect(
            bbox_polygon(*OLD_CITY_BBOX), corner_m=160.0
        )
        self.zicheng_poly = None
        line = LineString(list(self.core_poly.exterior.coords))
        objs.append({
            "id": self.new_id(),
            "name": "大城城墙",
            "category": "road",
            "geometry": xy_geom_to_geojson(line),
            "tags": {"man_made": "city_wall", "highway": "primary"},
            "ancient_kind": "城墙",
        })
        print("城墙:", len(objs))
        return objs

    def build_gates(self):
        """城门放在主街与城墙的交点，而不是四边中点。"""
        objs = []
        ring = self.core_poly.exterior
        minx, miny, maxx, maxy = self.core_poly.bounds
        tol = 40.0
        cand = {"东": [], "西": [], "南": [], "北": []}
        for o in self.objects:
            if o.get("category") != "road":
                continue
            tags = o.get("tags") or {}
            if tags.get("man_made") or tags.get("highway") not in ("primary", "secondary"):
                continue
            line = self._geojson_to_xy_line(o["geometry"])
            if line is None:
                continue
            inter = line.intersection(ring)
            for pt in self._points(inter):
                if abs(pt.x - maxx) < tol:
                    cand["东"].append(pt)
                elif abs(pt.x - minx) < tol:
                    cand["西"].append(pt)
                elif abs(pt.y - miny) < tol:
                    cand["南"].append(pt)
                elif abs(pt.y - maxy) < tol:
                    cand["北"].append(pt)
        cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
        mid = {"东": Point(maxx, cy), "西": Point(minx, cy),
               "南": Point(cx, miny), "北": Point(cx, maxy)}
        for dname, gname in (("东", "东门"), ("西", "西门"),
                             ("南", "南门"), ("北", "北门")):
            pts = cand[dname]
            pt = min(pts, key=lambda p: dist_m(p, mid[dname])) if pts else mid[dname]
            objs.append({
                "id": self.new_id(),
                "name": gname,
                "category": "custom",
                "geometry": xy_geom_to_geojson(pt),
                "tags": {"man_made": "city_gate"},
                "ancient_kind": "城门",
            })
        # 水门：水系穿墙处（优先东墙古运河）
        wpt = self._water_gate_point(ring, minx, maxx)
        if wpt is not None:
            objs.append({
                "id": self.new_id(),
                "name": "水门",
                "category": "custom",
                "geometry": xy_geom_to_geojson(wpt),
                "tags": {"man_made": "city_gate", "gate": "water"},
                "ancient_kind": "城门",
            })
        print("城门:", len(objs))
        return objs

    def _points(self, g):
        if g.is_empty:
            return []
        if g.geom_type == "Point":
            return [g]
        if g.geom_type == "MultiPoint":
            return list(g.geoms)
        return []

    def _water_gate_point(self, ring, minx, maxx):
        best = None
        for f in self.water_features:
            if f.geom_type != "LineString":
                continue
            inter = f.intersection(ring)
            for pt in self._points(inter):
                if abs(pt.x - maxx) < 80:   # 优先东墙（古运河）
                    return pt
                if best is None:
                    best = pt
        return best

    # ---------------- 3. 老城道路 ----------------
    def build_roads(self):
        with open(SOURCE_FILE, "r", encoding="utf-8") as f:
            src = json.load(f)
        core_buf = self.core_poly.buffer(150.0)
        roads = []
        for o in src.get("objects", []):
            if o.get("category") != "road":
                continue
            g = o.get("geometry") or {}
            if g.get("type") != "LineString":
                continue
            line = LineString([lonlat_to_xy(x, y) for x, y in g["coordinates"]])
            clipped = line.intersection(core_buf)
            if clipped.is_empty:
                continue
            parts = [clipped] if clipped.geom_type == "LineString" else list(clipped.geoms)
            highway = (o.get("tags") or {}).get("highway")
            new_hw = {
                "primary": "primary", "secondary": "secondary",
            }.get(highway, "residential")
            for part in parts:
                if part.is_empty or part.length < 20:
                    continue
                name = o.get("name")
                ancient_name = ROAD_RENAME.get(name)
                if new_hw == "residential":
                    ancient_name = None   # 坊巷不点名
                roads.append({
                    "id": self.new_id(),
                    "name": ancient_name,
                    "category": "road",
                    "geometry": xy_geom_to_geojson(part),
                    "tags": {"highway": new_hw, "source": "osm_old_city"},
                    "ancient_kind": "坊巷" if new_hw == "residential" else "官道",
                })
        print("老城道路:", len(roads))
        return roads

    # ---------------- 4. 坊面层 ----------------
    def build_wards(self):
        # 用主街缓冲 + 水面，从核心区里"抠"出街区；大块再补坊巷细分
        road_objs = [o for o in self.objects
                     if o.get("category") == "road" and not o.get("tags", {}).get("man_made")]
        major_geoms = []
        for o in road_objs:
            line = self._geojson_to_xy_line(o["geometry"])
            hw = (o.get("tags") or {}).get("highway")
            half = {"primary": 6.0, "secondary": 4.0}.get(hw, 2.5)
            if line is not None and line.length > 0:
                major_geoms.append(line.buffer(half))
        major_space = unary_union(major_geoms) if major_geoms else Polygon()

        blocks = self.core_poly.difference(major_space)
        if self.water_geom is not None:
            blocks = blocks.difference(self.water_geom)

        # 大块补坊巷（里坊制棋盘格，间距抖动）
        alleys = []
        for bp in self._to_polys(blocks):
            if bp.area >= 0.06e6:   # >= 0.06 km² 才细分
                alleys += self._subdivide_block(bp, 280.0)
        alley_objs = []
        for line in alleys:
            if line.length < 25:
                continue
            alley_objs.append({
                "id": self.new_id(),
                "name": None,
                "category": "road",
                "geometry": xy_geom_to_geojson(line),
                "tags": {"highway": "residential"},
                "ancient_kind": "坊巷",
            })
        self.objects += alley_objs

        alley_space = unary_union([a.buffer(2.0) for a in alleys]) if alleys else Polygon()
        buildable = self.core_poly.difference(major_space).difference(alley_space)
        if self.water_geom is not None:
            buildable = buildable.difference(self.water_geom)

        wards = []
        for p in self._to_polys(buildable):
            if p.area < 2000:   # 太小，忽略
                continue
            p = p.simplify(2.0, preserve_topology=True)
            if p.geom_type != "Polygon":
                continue
            name = self._ward_name()
            wards.append({
                "id": self.new_id(),
                "name": name,
                "category": "area",
                "geometry": xy_geom_to_geojson(p),
                "tags": {"ward": "yes"},
                "ancient_kind": "坊",
                "_poly": p,
            })
        print("坊:", len(wards), " 生成坊巷:", len(alley_objs))
        return wards

    def _to_polys(self, geom):
        if geom.is_empty:
            return []
        if geom.geom_type == "Polygon":
            return [geom]
        if geom.geom_type == "MultiPolygon":
            return [g for g in geom.geoms if g.geom_type == "Polygon"]
        return []

    def _subdivide_block(self, block, spacing):
        rng = self.rng
        lines = []
        minx, miny, maxx, maxy = block.bounds
        y = miny + spacing * 0.5
        while y < maxy:
            seg = LineString([(minx, y), (maxx, y)]).intersection(block)
            lines += self._seg_lines(seg)
            y += spacing * rng.uniform(0.8, 1.2)
        x = minx + spacing * 0.5
        while x < maxx:
            seg = LineString([(x, miny), (x, maxy)]).intersection(block)
            lines += self._seg_lines(seg)
            x += spacing * rng.uniform(0.8, 1.2)
        return lines

    def _seg_lines(self, seg):
        if seg.is_empty:
            return []
        if seg.geom_type == "LineString":
            return [seg]
        if seg.geom_type == "MultiLineString":
            return [g for g in seg.geoms]
        return []

    def _geojson_to_xy_line(self, gj):
        coords = gj.get("coordinates", [])
        return LineString([lonlat_to_xy(x, y) for x, y in coords])

    def _ward_name(self):
        global _WARD_SEQ, _WARD_NUM
        if _WARD_SEQ is None:
            seen = set()
            pool = []
            for n in WARD_NAMES:
                if n not in seen:
                    seen.add(n)
                    pool.append(n)
            for a in WARD_STEM_A:
                for b in WARD_STEM_B:
                    nm = a + b + "坊"
                    if nm not in seen:
                        seen.add(nm)
                        pool.append(nm)
            _WARD_SEQ = pool
        if _WARD_SEQ:
            return _WARD_SEQ.pop(0)
        _WARD_NUM += 1
        return f"第{_WARD_NUM}坊"

    # ---------------- 5. 坊内民居 ----------------
    def build_buildings(self, wards):
        out = []
        for w in wards:
            p = w["_poly"]
            cls = self._ward_class(p)
            density = {"core": 2000, "water": 1800,
                       "general": 1400, "edge": 600}[cls]
            area_km2 = p.area / 1e6
            n = int(round(area_km2 * density))
            placed = []
            minx, miny, maxx, maxy = p.bounds
            attempts = n * 10 + 10
            while len(placed) < n and attempts > 0:
                attempts -= 1
                cx = self.rng.uniform(minx, maxx)
                cy = self.rng.uniform(miny, maxy)
                if not p.covers(Point(cx, cy)):
                    continue
                if self.water_geom is not None and self.water_geom.covers(Point(cx, cy)):
                    continue
                wdt = self.rng.uniform(6, 12)
                hgt = self.rng.uniform(7, 15)
                ang = self.rng.uniform(0, math.pi)
                b = rect_poly(cx, cy, wdt, hgt, ang)
                if not p.covers(b):
                    continue
                if any(b.intersects(q) for q in placed):
                    continue
                placed.append(b)
                out.append({
                    "id": self.new_id(),
                    "name": "民居",
                    "category": "building",
                    "geometry": xy_geom_to_geojson(b),
                    "tags": {"building": "house"},
                    "ancient_kind": "民居",
                })
        print("民居:", len(out))
        return out

    def _ward_class(self, p):
        c = p.centroid
        d_center = dist_m(c, Point(*self.center_xy))
        east_edge = self.core_poly.bounds[2]
        d_river = east_edge - c.x
        if d_center < 250:
            return "core"
        if d_river < 320:
            return "water"
        if (c.x < self.core_poly.bounds[0] + 180
                or c.x > east_edge - 180
                or c.y < self.core_poly.bounds[1] + 180
                or c.y > self.core_poly.bounds[3] - 180):
            return "edge"
        return "general"

    # ---------------- 6. POI ----------------
    def build_pois(self):
        core_region = self.core_poly.difference(self.water_geom) if self.water_geom else self.core_poly
        general_region = self.core_poly.buffer(1500).difference(self.water_geom) \
            if self.water_geom else self.core_poly.buffer(1500)
        counts = {"core": 900, "water": 350, "general": 650, "edge": 300}
        out = []
        used_names = set()
        for zone, total in counts.items():
            pool = ZONE_POOLS[zone]
            weights = list(pool.values())
            kinds = list(pool.keys())
            for _ in range(total):
                kind = self.rng.choices(kinds, weights=weights, k=1)[0]
                pt = self._sample_zone(zone, core_region, general_region)
                if pt is None:
                    continue
                # 最小间距
                if any(dist_m(pt, Point(o["_x"], o["_y"])) < 35 for o in out):
                    continue
                name = self._make_name(kind, used_names)
                gj = xy_geom_to_geojson(pt)
                obj = {
                    "id": self.new_id(),
                    "name": name,
                    "category": "custom",
                    "geometry": gj,
                    "tags": {},
                    "ancient_kind": kind,
                    "_x": pt.x, "_y": pt.y,
                }
                out.append(obj)
        for o in out:
            o.pop("_x", None)
            o.pop("_y", None)
        print("POI:", len(out))
        return out

    def _sample_zone(self, zone, core_region, general_region):
        rng = self.rng
        if zone == "core":
            for _ in range(60):
                pt = self._rand_in(core_region)
                if pt is not None:
                    return pt
            return None
        if zone == "water":
            return self._sample_near_water()
        if zone == "general":
            for _ in range(60):
                pt = self._rand_in(general_region)
                if pt is not None and not self.core_poly.covers(pt):
                    return pt
                if pt is not None:
                    return pt
            return None
        # edge：城外 2.5–20km
        for _ in range(60):
            ang = rng.uniform(0, math.tau)
            r = rng.uniform(2500, 20000)
            pt = Point(self.center_xy[0] + r * math.cos(ang),
                       self.center_xy[1] + r * math.sin(ang))
            if self.water_geom is not None and self.water_geom.covers(pt):
                continue
            if self.core_poly.covers(pt):
                continue
            return pt
        return None

    def _rand_in(self, region):
        if region.is_empty:
            return None
        minx, miny, maxx, maxy = region.bounds
        for _ in range(80):
            pt = Point(self.rng.uniform(minx, maxx),
                       self.rng.uniform(miny, maxy))
            if region.covers(pt):
                return pt
        return None

    def _sample_near_water(self):
        rng = self.rng
        feats = [f for f in self.water_features
                 if self.core_poly.buffer(800).intersects(f)]
        if not feats:
            feats = self.water_features
        for _ in range(60):
            src = rng.choice(feats)
            if src.geom_type == "LineString" and src.length > 1:
                p = src.interpolate(rng.uniform(0, src.length))
            elif src.geom_type == "Polygon" and src.exterior.length > 1:
                p = src.exterior.interpolate(rng.uniform(0, src.exterior.length))
            else:
                continue
            ang = rng.uniform(0, math.tau)
            off = rng.uniform(8, 40)
            q = Point(p.x + off * math.cos(ang), p.y + off * math.sin(ang))
            if self.water_geom is not None and self.water_geom.covers(q):
                continue
            return q
        return None

    def _make_name(self, kind, used):
        if kind in PLAIN_KINDS:
            return kind
        for _ in range(60):
            name = self.rng.choice(PREFIX2) + kind
            if name not in used:
                used.add(name)
                return name
        used.add(kind)
        return kind

    # ---------------- 7. 城外官道 / 聚落 ----------------
    def build_country(self):
        with open(SOURCE_FILE, "r", encoding="utf-8") as f:
            src = json.load(f)
        town_pts = {}
        for o in src.get("objects", []):
            if (o.get("category") == "place"
                    and o.get("name") in TOWNS
                    and (o.get("geometry") or {}).get("type") == "Point"):
                town_pts[o["name"]] = o["geometry"]["coordinates"]
        houses = []
        for tname, (tlon, tlat) in town_pts.items():
            if dist_m(Point(*lonlat_to_xy(tlon, tlat)), Point(*self.center_xy)) > CONTENT_RADIUS_M:
                continue
            tx, ty = lonlat_to_xy(tlon, tlat)
            n_houses = self.rng.randint(6, 15)
            for _ in range(n_houses):
                ang = self.rng.uniform(0, math.tau)
                r = self.rng.uniform(30, 180)
                hx = tx + r * math.cos(ang)
                hy = ty + r * math.sin(ang)
                if self.water_geom is not None and self.water_geom.covers(Point(hx, hy)):
                    continue
                b = rect_poly(hx, hy, self.rng.uniform(6, 12),
                              self.rng.uniform(7, 15), self.rng.uniform(0, math.pi))
                houses.append({
                    "id": self.new_id(),
                    "name": "民居",
                    "category": "building",
                    "geometry": xy_geom_to_geojson(b),
                    "tags": {"building": "house"},
                    "ancient_kind": "民居",
                })
        print("城外聚落民居:", len(houses))
        return houses

    def _nearest_gate(self, lon, lat):
        x, y = lonlat_to_xy(lon, lat)
        minx, miny, maxx, maxy = self.core_poly.bounds
        cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
        candidates = [(maxx, cy), (minx, cy), (cx, miny), (cx, maxy)]
        return min(candidates, key=lambda p: (p[0] - x) ** 2 + (p[1] - y) ** 2)

    # ---------------- 组装 ----------------
    def run(self):
        self.objects = self.load_keep_objects()
        self.objects += self.build_wall()
        self.objects += self.build_roads()
        self.objects += self.build_gates()
        wards = self.build_wards()
        if self.stage >= 2:
            self.objects += self.build_buildings(wards)
        # 坊对象要去掉内部字段
        for w in wards:
            w.pop("_poly", None)
            self.objects.append(w)
        if self.stage >= 3:
            self.objects += self.build_pois()
            self.objects += self.build_country()

        data = {
            "name": "扬州地图",
            "version": 3,
            "source": "OSM(自然地理+锚点) + 算法生成城区",
            "generator": "build_world.py",
            "objects": self.objects,
        }
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        print("=" * 60)
        print("输出:", OUTPUT_FILE)
        print("总对象:", len(self.objects))
        from collections import Counter
        cats = Counter(o.get("category") for o in self.objects)
        print("category:", dict(cats))
        kinds = Counter(o.get("ancient_kind") for o in self.objects if o.get("ancient_kind"))
        print("kind 种类数:", len(kinds))
        for k, v in kinds.most_common(40):
            print(f"   {k}: {v}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", type=int, default=3, choices=[1, 2, 3])
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    WorldBuilder(stage=args.stage, seed=args.seed).run()


if __name__ == "__main__":
    main()
