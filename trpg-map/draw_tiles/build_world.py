# -*- coding: utf-8 -*-
"""
build_world.py
==============
南宋世界生成器（推翻现代 OSM 城区，只保留自然地理 + 史实锚点，其余算法生成）。

支持多城市：布局参数集中在下面的 `CITY_CONFIGS`（投影中心 / 老城范围 / 坊名池 /
街巷改名 / 史实锚点 / 城外聚落）。用 `TRPG_CITY=<城市>` 或 `生成.py --city <城市>` 切换。

数据流：
    ../数据/<城市>_OSM精简.json (抽稀后 OSM) ─┐
    ../数据/<城市>_布点锚点.json (布点锚点)  ─┼─► build_world.py
                                           └─► ../数据/<城市>_南宋世界.json（同名覆盖，下游零改动）

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
    Point, LineString, Polygon, MultiPolygon, box as shp_box, shape,
)
from shapely.ops import nearest_points, unary_union, transform as shp_transform

from song_kinds import KINDS as SONG_KINDS
from water_width import width_m as waterway_width_m

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 数据统一放在 trpg-map/数据/（与 draw_tiles/ 同级）
DATA_DIR = os.path.join(os.path.dirname(BASE_DIR), "数据")

# 城市（可用 TRPG_CITY 覆盖）——决定输入/输出文件名
CITY = os.environ.get("TRPG_CITY", "扬州")

SOURCE_FILE = os.path.join(DATA_DIR, f"{CITY}_OSM精简.json")
CUSTOM_FILE = os.path.join(DATA_DIR, f"{CITY}_布点锚点.json")
OUTPUT_FILE = os.path.join(DATA_DIR, f"{CITY}_南宋世界.json")

# POI 冻结表：存在则**只读它**，不再随机生成。
# 为什么：build_pois 原本每次跑都随机采样位置 + 随机取名，
# 导致存档/足迹/见闻里的地名每次重跑都对不上（实测保留率仅 16%）。
POI_FILE = os.path.join(DATA_DIR, f"{CITY}_POI.json")

# 建筑群（宫观 / 府邸 / 别业）：<城市>_建筑群.json
#   与 POI 不同，建筑群是**手工定点的院落**，build_world 按布局生成院墙/殿宇/廊庑/园圃
COMPOUND_FILE = os.path.join(DATA_DIR, f"{CITY}_建筑群.json")

# 「中轴三进」宫观布局（归一化：u,v ∈ [-0.5,0.5]；v 正 = 北/后，负 = 南/前/
# 即面南临水）。每项：(名称后缀, ancient_kind, u, v, 宽占比例, 高占比例)
PALACE_PARTS = [
    ("宫门", "宫门", 0.000, -0.415, 0.220, 0.080),
    ("正殿", "殿",   0.000, -0.120, 0.360, 0.170),
    ("西厢", "殿",  -0.355, -0.060, 0.100, 0.300),
    ("东厢", "殿",   0.355, -0.060, 0.100, 0.300),
    ("后殿", "殿",   0.000,  0.175, 0.300, 0.140),
    ("高楼", "楼",   0.000,  0.395, 0.110, 0.110),
]
# 竹廊：中轴两侧的长廊（连接宫门 → 正殿 → 后殿）
PALACE_CORRIDORS = [
    (-0.240, -0.130, 0.028, 0.600),
    (0.240, -0.130, 0.028, 0.600),
]

SEED = 42

#: 五行神庙：五座神各主一行；一城（城内+城外）合计上限
FIVE_TEMPLE_ROWS = (
    ("祝融庙", "火"), ("玄冥庙", "水"), ("句芒庙", "木"),
    ("蓐收庙", "金"), ("后土庙", "土"),
)
FIVE_TEMPLE_MAX = 10
#: 岛屿环水（护城河）宽度（米）——把岛与岸隔开
ISLAND_MOAT_M = 400.0

# 覆盖检查：若某条水道的中线有这么多比例已经落在「已有水面」里，
# 就不再 buffer（已有水面就是真相），避免小河被错误撑宽。
COVERAGE_SKIP = 0.5

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
# 城市布局配置（新增城市：在 CITY_CONFIGS 里加一条即可）
#
#   ⚠️ 「扬州」条目是原先的硬编码值，SEED=42 下输出必须逐字节不变，勿改。
#   岳阳 = 岳州古城：西墙即洞庭湖岸（岳阳门/岳阳楼），东至岳州文庙一带，
#          约 2.1×2.4 km；投影中心取古城中心。
# ----------------------------------------------------------------------
CITY_CONFIGS = {
    "扬州": {
        # 投影中心（文昌阁）
        "center": (119.4282, 32.3964),
        # 老城核心区（护城河/小秦淮河/古运河/挹江门 围合，约 2.3×2.3 km）
        "old_city_bbox": (119.4245, 32.3835, 119.4485, 32.4045),
        "content_radius_m": 30000.0,
        "ward_names": [
            "太平坊", "仁丰坊", "开明坊", "甘泉坊", "东关坊", "通泗坊",
            "大东门坊", "小东门坊", "湾子坊", "彩衣坊", "文峰坊", "琼花坊",
            "广陵坊", "汶河坊", "盐阜坊", "便益门坊", "徐凝门坊", "南河下坊",
            "梅岭坊", "竹西坊", "皮市坊", "教场坊", "辕门坊", "御码头坊",
            "莲花坊", "双桂坊", "崇儒坊", "崇俭坊", "务本坊", "观德坊",
            "清宁坊", "敦化坊", "乐善坊", "兴仁坊", "积善坊", "迎恩坊",
        ],
        # 老城历史街巷改名（现代名 -> 南宋名）
        "road_rename": {
            "四望亭路": "四望亭街", "国庆路": "国庆街", "大东门街": "大东门街",
            "彩衣街": "彩衣街", "徐凝门路": "徐凝门街", "汶河北路": "汶河街",
            "汶河南路": "汶河街", "泰州路": "泰州街", "甘泉路": "甘泉街",
            "盐阜东路": "盐阜街", "盐阜西路": "盐阜街", "通泗街": "通泗街",
            "便益门大街": "便益门大街", "北门外大街": "北门外大街",
            "广陵路": "广陵街", "竹西路": "竹西街", "梅岭西路": "梅岭街",
            "文昌中路": "文昌街", "文昌西路": "文昌街", "文昌东路": "文昌街",
            "江阳中路": "江阳街", "江阳西路": "江阳街", "文汇西路": "文汇街",
            "维扬路": "维扬街", "史可法路": "史可法街", "高桥路": "高桥街",
        },
        # 史实锚点 name -> 南宋 kind
        "anchor_kind": {
            "文昌阁": "高台", "鼓楼": "钟鼓楼", "四望亭": "亭", "五亭桥": "桥",
            "文峰塔": "高台", "天宁塔": "高台", "琼花观": "观", "个园": "园苑",
            "何园": "园苑", "瘦西湖": "湖", "东关古渡": "渡口",
            "北门遗址": "城门", "挹江门": "城门", "隋炀帝陵遗址博物馆": "义冢",
            "崔致远纪念馆": "祠", "朱自清故居": "民居", "张若虚雕塑": "高台",
            # 史实景点补充（避免 tourism/historic 白名单化时被误删）
            "汪氏小苑": "民居", "小盘谷": "园", "小金山": "园",
            "熙春台": "高台", "钓鱼台": "亭", "仪征联营墓葬群": "义冢",
        },
        # 城外官道连接的聚落（取自源 OSM place 点）
        "towns": [
            "瓜洲镇", "邵伯镇", "湾头镇", "仪征市", "江都区", "槐泗镇",
            "施桥镇", "杭集镇", "蒋王街道", "西湖街道", "汊河街道", "头桥镇",
            "八里镇", "李典镇", "泰安镇", "新集镇", "朴席镇", "甘泉街道",
        ],
    },

    "岳阳": {
        # 投影中心：岳州古城中心（岳阳楼西门 ~20 km 内为城区）
        "center": (113.0975, 29.3765),
        # 岳州古城：西墙即洞庭湖岸（岳阳门/岳阳楼），东至岳州文庙
        "old_city_bbox": (113.0865, 29.3655, 113.1085, 29.3875),
        "content_radius_m": 30000.0,
        # 岳州坊名（不足的由通用吉祥字根池补齐）
        "ward_names": [
            "巴陵坊", "洞庭坊", "岳阳坊", "君山坊", "南津坊", "城陵坊",
            "云梦坊", "三江坊", "鹿角坊", "岳州坊", "白沙坊", "青草坊",
            "龙湾坊", "新墙坊", "太平坊", "迎恩坊",
        ],
        # 岳阳老城街巷改名（现代名 -> 南宋名）
        "road_rename": {
            "洞庭北路": "洞庭街", "洞庭南路": "洞庭街", "洞庭大道": "洞庭街",
            "巴陵西路": "巴陵街", "巴陵中路": "巴陵街", "巴陵东路": "巴陵街",
            "巴陵大桥": "巴陵桥", "城陵矶路": "城陵矶街",
            "南湖路": "南湖街", "云梦路": "云梦街", "得胜路": "得胜街",
            "建设路": "建设街", "站前路": "站前街", "青年路": "青年街",
        },
        # 岳阳史实锚点 name -> 南宋 kind（OSM 里 historic/tourism 的对象）
        "anchor_kind": {
            "文庙": "州学",      # 岳州文庙 / 岳州学宫
            "岳阳楼": "高台",    # OSM 暂无本体，留作备用
            "慈氏塔": "高台",
            "南津古渡": "渡口",
            "岳州关": "税场",    # 城陵矶海关
            "三醉亭": "亭", "仙梅亭": "亭",
            "小乔墓": "义冢", "鲁肃墓": "义冢",
        },
        # 城外聚落（画框内 30 km 的镇/街道，取自源 OSM place 点）
        "towns": [
            "城陵矶街道", "郭镇乡", "康王乡", "麻塘街道", "新开镇", "新墙镇",
            "筻口镇", "鹿角镇", "鹿角", "广兴洲镇", "云溪街道", "西塘镇",
            "长塘镇",
        ],
        # 地名改名（现代/中性名 -> 南宋名）；只改名字，几何不动
        "rename": {
            # OSM 的「君山银针茶园」面本来就覆盖整个君山岛。
            # 茶园归君山（去现代品种名「银针」），**不得叫「锦香宫茶园」**——
            # 锦香宫是宫，不是茶园。
            "君山银针茶园": "君山茶园",
        },
    },
}

if CITY not in CITY_CONFIGS:
    raise SystemExit(
        "build_world.py 没有「%s」的布局配置；请在 CITY_CONFIGS 里补一条（见文件顶部说明）" % CITY
    )

_CFG = CITY_CONFIGS[CITY]

CENTER_LON, CENTER_LAT = _CFG["center"]
OLD_CITY_BBOX = tuple(_CFG["old_city_bbox"])
CONTENT_RADIUS_M = float(_CFG.get("content_radius_m", 30000.0))
WARD_NAMES = list(_CFG["ward_names"])
ROAD_RENAME = dict(_CFG["road_rename"])
ANCHOR_KIND = dict(_CFG["anchor_kind"])
TOWNS = list(_CFG["towns"])
# 地名改名（现代/中性名 -> 南宋名）；在 load_keep_objects 里统一应用
NAME_RENAME = dict(_CFG.get("rename", {}))

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


# 有名字的天然要素 → 山水 kind（供地图图标 / 知识库）
_NATURE_KIND = (
    ("山", ("山", "冈", "岡", "峰", "岭", "嶺", "丘", "岗", "嶂", "岩")),
    ("洲", ("洲", "渚")),
    ("林", ("林",)),
    ("园", ("园", "苑")),
    ("湖", ("湖", "荡", "蕩", "漾", "潭", "池", "淀")),
)
# 水域只认「湖」类关键词（避免「沿山河」被“山”吃掉、「枣林水库」被“林”吃掉）
_WATER_KIND_KEYS = ("湖", "荡", "蕩", "漾", "潭", "池", "淀", "水库", "水庫")


def _nature_kind(name, cat, tags):
    if not name:
        return None
    if cat in ("water", "waterway"):
        return "湖" if any(k in name for k in _WATER_KIND_KEYS) else None
    if cat in ("natural", "landuse"):
        # 先按**结尾**匹配：中文地名多为「专名 + 通名」，通名在末尾。
        # 否则「君山茶园」「五岭公园」会先命中「山」而被误判为山体。
        for kind, keys in _NATURE_KIND:
            if any(name.endswith(k) for k in keys):
                return kind
        for kind, keys in _NATURE_KIND:
            if any(k in name for k in keys):
                return kind
    return None


def _with_nature_kind(o, cat, tags):
    """给有名字的天然要素补 ancient_kind（不改已有 kind）。"""
    if o.get("ancient_kind"):
        return o
    k = _nature_kind(o.get("name"), cat, tags)
    if not k:
        return o
    o = dict(o)
    o["ancient_kind"] = k
    return o

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
        "递铺": 1, "园": 1, "书场": 1, "棋馆": 1, "市集": 2,
        "绣坊": 1, "织坊": 1,
    },
        # edge 池不能有水类 kind：edge 是**随机撒点**（不看水），放水类就会陆上行舟。
    "edge": {
        "驿站": 3, "递铺": 3, "车马行": 5, "马厩": 2, "棺材铺": 2,
        "纸扎铺": 2, "义冢": 2, "坟地": 2, "寺": 2, "观": 2, "祠": 1,
        "磨坊": 2, "油坊": 2, "豆腐坊": 1, "酒坊": 2, "染坊": 1,
        "客栈": 2, "镖行": 1,
    },
}

# ----------------------------------------------------------------------
# 几何小工具
# ----------------------------------------------------------------------

#: 必须依水的 POI kind（随机布点池里已移除；这里对冻结表再做一道校验）
WATER_POI_KINDS = {"画舫", "船行", "码头", "渡口", "鱼行", "浮桥", "桥"}
WATER_POI_KEEP_M = 60.0     # ≤ 此距离：已在岸边，不动
WATER_POI_SNAP_M = 2000.0   # ≤ 此距离：吸附到最近水域；> 此距离：删除


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
        self.water_polys = []       # 米制水面（**只含面**，buffer 时用来去重）
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
            if name and name in NAME_RENAME:
                o = dict(o)
                o["name"] = NAME_RENAME[name]
                name = o["name"]
            if cat in ("water", "waterway"):
                o = _with_nature_kind(o, cat, tags)
                keep.append(o)
                self._collect_water(o, water_geoms)
            elif cat == "natural":
                if name and _is_modern_name(name):
                    continue
                o = _with_nature_kind(o, cat, tags)
                keep.append(o)
                self._collect_water(o, water_geoms)
            elif cat == "landuse" and tags.get("landuse") in (
                "farmland", "forest", "wood", "grass", "meadow",
                "cemetery", "recreation_ground", "village_green",
            ):
                if name and _is_modern_name(name):
                    continue
                o = _with_nature_kind(o, cat, tags)
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
            elif name and cat == "area" and tags.get("place") in ("island", "islet"):
                # 岛屿（如洞庭君山岛）——保留为独立面，否则岛上没有任何地物
                o = dict(o)
                o["ancient_kind"] = "洲"
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
                self.water_polys.append(shp)
            elif gt == "MultiPolygon":
                for poly in g["coordinates"]:
                    shp = Polygon([lonlat_to_xy(x, y) for x, y in poly[0]])
                    out.append(shp)
                    self.water_features.append(shp)
                    self.water_polys.append(shp)
            elif gt == "LineString":
                # 自来水道只有中心线 → 按**真实宽度** buffer（不再硬编码 12m）
                shp = LineString([lonlat_to_xy(x, y) for x, y in g["coordinates"]])
                w = waterway_width_m(o.get("tags"), o.get("name"))
                out.append(shp.buffer(w / 2.0, cap_style=2, join_style=1))
                self.water_features.append(shp)
            elif gt == "MultiLineString":
                for line in g["coordinates"]:
                    shp = LineString([lonlat_to_xy(x, y) for x, y in line])
                    w = waterway_width_m(o.get("tags"), o.get("name"))
                    out.append(shp.buffer(w / 2.0, cap_style=2, join_style=1))
                    self.water_features.append(shp)
        except Exception:
            pass

    # ---------------- 1b. 水道 buffer 成面（路径 A） ----------------
    def buffer_waterways(self):
        """把水道中心线按真实宽度 buffer 成水面多边形。

        OSM 里大河常常**只有中心线**（如扬州的长江），没有水面多边形。
        若不 buffer，空间库里它就是一条**零宽度线**——碰撞会认为可以直接
        走过去，渲染也只能画成一根细线（而真实宽度 1500m）。

        做法：同名河段先合并 → 中心线 buffer(width/2) → 减去已有水面
              → 作为 category=water 写入输出；原水道线删除。
        """
        ww = [o for o in self.objects if o.get("category") == "waterway"]
        if not ww:
            return []

        existing = [p for p in self.water_polys if not p.is_empty]

        tree = None
        if existing:
            try:
                from shapely.strtree import STRtree
                tree = STRtree(existing)
            except Exception:
                tree = None

        # 同名河段先归组（长江在数据里是 5 段）
        groups = {}
        for i, o in enumerate(ww):
            key = o.get("name") or ("__noname_%d" % i)
            groups.setdefault(key, []).append(o)

        out = []
        geoms_m = []          # 米制，供后续 water_geom 使用
        skipped = []          # 因“已有水面”而跳过的河
        buffered_objs = []    # 被 buffer 掉的原水道对象（要删）

        for name, items in groups.items():
            tags = items[0].get("tags") or {}
            w = waterway_width_m(tags, items[0].get("name"))

            # 先收集全部中线点（米制），用于两项判断：
            #   a. 已被已有水面覆盖多少（高覆盖率 → 根本不 buffer）
            #   b. 真正要 buffer 的几何
            parts = []
            sample_pts = []
            for o in items:
                g = o.get("geometry") or {}
                gt = g.get("type")
                if gt == "LineString":
                    raw = [g.get("coordinates") or []]
                elif gt == "MultiLineString":
                    raw = g.get("coordinates") or []
                else:
                    continue
                for ln in raw:
                    if len(ln) < 2:
                        continue
                    try:
                        xy = [lonlat_to_xy(x, y) for x, y in ln]
                        parts.append(LineString(xy).buffer(
                            w / 2.0, cap_style=2, join_style=1))
                        sample_pts.extend(xy)
                    except Exception:
                        pass

            if not parts:
                continue

            # ---- 覆盖检查：已有水面就是真相，不要再 buffer ----
            if existing and sample_pts:
                try:
                    idxs = tree.query(LineString(sample_pts)) if tree is not None else None
                except Exception:
                    idxs = None
                near = [existing[j] for j in idxs] if idxs is not None and len(idxs) else existing
                step = max(1, len(sample_pts) // 60)
                probe = sample_pts[::step]
                covered = sum(
                    1 for p in probe
                    if any(g.contains(Point(p)) for g in near)
                ) / max(1, len(probe))
                if covered >= COVERAGE_SKIP:
                    # 保留原中线（它带着河名，而那些水面多边形是无名的），
                    # 打上 covered 标记 → 渲染器跳过（不然水面上会多一条深色中线）
                    for o in items:
                        o.setdefault("tags", {})["covered"] = "yes"
                    skipped.append((name, covered))
                    continue

            try:
                buf = unary_union(parts)
            except Exception:
                continue

            # 减去已有水面（避免重叠 → 水面上出现多余内轮廓）
            if existing:
                if tree is not None:
                    try:
                        near = [existing[j] for j in tree.query(buf)]
                    except Exception:
                        near = [p for p in existing if p.intersects(buf)]
                else:
                    near = [p for p in existing if p.intersects(buf)]
                if near:
                    try:
                        buf = buf.difference(unary_union(near))
                    except Exception:
                        pass

            if buf.is_empty:
                continue

            gj = xy_geom_to_geojson(buf)
            if not gj:
                continue

            geoms_m.append(buf)

            wt = tags.get("waterway")
            out.append({
                "id": None,
                "name": None if name.startswith("__noname_") else name,
                "category": "water",
                "geometry": gj,
                "tags": {
                    "water": "river" if wt in ("river", "stream") else "canal",
                    "buffered_from": "waterway",
                    "buffered_width_m": round(w, 1),
                },
            })
            buffered_objs.extend(items)

        # 只删「真正被 buffer 掉」的水道线；
        # 被覆盖而跳过的保留（它们带着河名，且渲染时会跳过）。
        drop_ids = {id(o) for o in buffered_objs}
        self.objects = [o for o in self.objects if id(o) not in drop_ids]

        # 让 buffer 出来的河面也参与后续计算（建房避水等）
        try:
            merged = ([self.water_geom] if self.water_geom is not None else []) + geoms_m
            self.water_geom = unary_union(merged) if merged else None
        except Exception:
            pass

        print("水道 buffer：%d 条中线 → %d 个河面（%d 组因已有水面跳过，保留中线）"
              % (len(ww), len(out), len(skipped)))
        return out

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

        # ---- 冻结表优先：POI 的名字/位置永久稳定，存档不会对不上 ----
        if os.path.exists(POI_FILE):
            out = self._load_frozen_pois(POI_FILE)
            print("POI（冻结表）:", len(out))
            return out

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

        # 首次生成后落盘冻结（之后不再随机）
        self._save_frozen_pois(out, POI_FILE)
        return out

    # ---- POI 冻结表读写 ----
    def _repair_water_pois(self, objs):
        """把「必须依水」的 POI 吸附到最近水域；离水 > WATER_POI_SNAP_M 的直接删除。

        幂等：已在岸边（≤ WATER_POI_KEEP_M）的不动。**冻结表**与**随机生成**都过一遍，
        从根上杠绝「陆地上的船行 / 画舫 / 码头 / 桥」。
        """
        if self.water_geom is None or self.water_geom.is_empty:
            return objs
        kept, moved, dropped = [], 0, 0
        for o in objs:
            if o.get("ancient_kind") not in WATER_POI_KINDS:
                kept.append(o); continue
            g = o.get("geometry") or {}
            if g.get("type") != "Point" or not g.get("coordinates"):
                kept.append(o); continue
            lon, lat = g["coordinates"][:2]
            p = Point(*lonlat_to_xy(lon, lat))
            near = nearest_points(p, self.water_geom)[1]
            d = p.distance(near)
            if d > WATER_POI_SNAP_M:
                dropped += 1
                continue
            if d > WATER_POI_KEEP_M:
                nlon, nlat = xy_to_lonlat(near.x, near.y)
                o = dict(o)
                o["geometry"] = {"type": "Point", "coordinates": [nlon, nlat]}
                moved += 1
            kept.append(o)
        if moved or dropped:
            print(f"水域 POI 校验修复：吸附 {moved}、删除 {dropped}")
        return kept

    def _load_frozen_pois(self, path):
        data = json.load(open(path, encoding="utf-8"))
        out = []
        for p in data.get("objects", []):
            out.append({
                "id": self.new_id(),
                "name": p.get("name"),
                "category": "custom",
                "geometry": {"type": "Point",
                             "coordinates": [p["lon"], p["lat"]]},
                "tags": {},
                "ancient_kind": p.get("kind"),
            })
        return self._repair_water_pois(out)

    def _save_frozen_pois(self, objs, path):
        pois = []
        for o in objs:
            c = o["geometry"]["coordinates"]
            pois.append({
                "name": o.get("name"),
                "kind": o.get("ancient_kind"),
                "lon": round(c[0], 7),
                "lat": round(c[1], 7),
            })
        data = {
            "comment": f"{CITY} POI 冻结表 —— build_world 只读它，不再随机生成",
            "city": CITY,
            "count": len(pois),
            "objects": pois,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        print("POI 冻结表已写出：", path)

    def _append_frozen_pois(self, objs):
        """把新生成的 POI（如五行神庙）追加进冻结表 → 下次重跑被当作「已有」、不重复。

        不存在的冻结表（首次随机生成场景）不管；只在已有表上追加。
        """
        if not objs or not os.path.exists(POI_FILE):
            return
        try:
            with open(POI_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return
        rows = data.setdefault("objects", [])
        seen = {(p.get("name"), round(float(p.get("lon", 0)), 5),
                 round(float(p.get("lat", 0)), 5)) for p in rows}
        added = 0
        for o in objs:
            g = o.get("geometry") or {}
            c = g.get("coordinates") if g.get("type") == "Point" else None
            if not c:
                continue
            key = (o.get("name"), round(c[0], 5), round(c[1], 5))
            if key in seen:
                continue
            rows.append({"id": o.get("id"), "name": o.get("name"),
                         "kind": o.get("ancient_kind"),
                         "lon": round(c[0], 7), "lat": round(c[1], 7),
                         "jitter": False, "note": "五行神庙（生成器加入）"})
            added += 1
        if added:
            data["count"] = len(rows)
            with open(POI_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
            print("POI 冻结表追加:", added)

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

    # ---------------- 7. 建筑群（宫观 / 府邸） ----------------
    def build_compounds(self):
        """手工定点的大型院落：院墙 + 殿宇 + 廊庑 + 园圃 + 泊船处。

        数据源：`数据/<城市>_建筑群.json`。没有该文件就是不生成（不影响其它城市）。
        """
        if not os.path.exists(COMPOUND_FILE):
            print("建筑群: 0（无 %s）" % os.path.basename(COMPOUND_FILE))
            return []
        with open(COMPOUND_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        out = []
        for c in data.get("compounds", []):
            out += self._build_compound(c)
        print("建筑群: %d 个对象（%d 座院落）"
              % (len(out), len(data.get("compounds", []))))
        return out

    def _build_compound(self, c):
        name = c["name"]
        w = float(c.get("w_m", 500.0))
        h = float(c.get("h_m", 360.0))
        ang = math.radians(float(c.get("angle_deg", 0.0)))
        cx, cy = lonlat_to_xy(float(c["lon"]), float(c["lat"]))
        rename = c.get("rename") or {}
        layout = c.get("layout", "palace")
        objs = []

        def add(nm, kind, geom, cat="building", tags=None):
            objs.append({
                "id": self.new_id(),
                "name": nm,
                "category": cat,
                "geometry": xy_geom_to_geojson(geom),
                "tags": tags if tags is not None else {"building": "yes"},
                "ancient_kind": kind,
            })

        # ---- 院墙：4 段细矩形（不用城墙层，免得与州城城墙的 26m 粗黑线混同）----
        t = float(c.get("wall_t_m", 6.0))
        add(name + "院墙", "院墙", rect_poly(cx, cy + (h - t) / 2, w, t, ang))
        add(name + "院墙", "院墙", rect_poly(cx, cy - (h - t) / 2, w, t, ang))
        add(name + "院墙", "院墙", rect_poly(cx - (w - t) / 2, cy, t, h - 2 * t, ang))
        add(name + "院墙", "院墙", rect_poly(cx + (w - t) / 2, cy, t, h - 2 * t, ang))

        if layout == "palace":
            # ---- 殿宇（中轴三进）----
            for suffix, kind, u, v, wf, hf in PALACE_PARTS:
                nm = rename.get(suffix) or (name + suffix)
                add(nm, kind,
                    rect_poly(cx + u * w, cy + v * h, w * wf, h * hf, ang))
            # ---- 竹廊 ----
            for i, (u, v, wf, hf) in enumerate(PALACE_CORRIDORS):
                add(name + "竹廊", "廊",
                    rect_poly(cx + u * w, cy + v * h, w * wf, h * hf, ang),
                    tags={"building": "roof", "roof:material": "bamboo"})

        # ---- 园圃（茶园 / 果林）----
        for g in c.get("gardens", []):
            gx, gy = lonlat_to_xy(float(g["lon"]), float(g["lat"]))
            gl = g.get("landuse", "farmland")
            add(g.get("name") or (name + ("茶园" if gl == "farmland" else "果林")),
                "茶园" if gl == "farmland" else "果园",
                rect_poly(gx, gy, float(g["w_m"]), float(g["h_m"]),
                          math.radians(float(g.get("angle_deg", 0.0)))),
                cat="landuse", tags={"landuse": gl})

        # ---- 院内具名建筑（如锦香宫内的玄冥庙）----
        # 规格：u/v 为相对院中心的归一化坐标（同 PALACE_PARTS）；w_frac/h_frac 为占院宽/高的比例
        for b in c.get("buildings", []):
            add(b.get("name") or (name + "建筑"), b.get("kind", "殿"),
                rect_poly(cx + float(b.get("u", 0.0)) * w,
                          cy + float(b.get("v", 0.0)) * h,
                          w * float(b.get("w_frac", 0.14)),
                          h * float(b.get("h_frac", 0.20)), ang))

        # ---- 泊船处 / 码头 ----
        for d in c.get("docks", []):
            add(d.get("name") or (name + "泊船处"), "码头",
                Point(*lonlat_to_xy(float(d["lon"]), float(d["lat"]))),
                cat="custom", tags={})

        return objs

    # ---------------- 7b. 岛屿环水 / 五行神庙 ----------------
    def _obj_point(self, o):
        """取对象的一个代表性经纬度（Point 直取；面取重心）。"""
        g = o.get("geometry") or {}
        if g.get("type") == "Point":
            return g.get("coordinates")
        try:
            c = shape(g).centroid
            return (c.x, c.y)
        except Exception:
            return None

    def build_island_moats(self, k_m=ISLAND_MOAT_M):
        """给每个「洲」(岛屿) 加一圈水域（护城河）——岛被水包住，不再与岸相连。

        背景：OSM 湖面的外环在部分岛屿处是凹的，岛落在湖面之外、贴着陆地
        （实测君山岛外 120m 环带只有 7% 是水 → 看起来跟岸边连着）。
        做法：岛 buffer(k_m) − 岛 → 并入水面。与湖面接上后岛就被水完全包围。
        """
        out = []
        for o in list(self.objects):
            if o.get("ancient_kind") != "洲":
                continue
            g = o.get("geometry") or {}
            try:
                ll = shape(g)
            except Exception:
                continue
            if ll.is_empty:
                continue
            try:
                xy = shp_transform(lambda x, y: lonlat_to_xy(x, y), ll)
                moat = xy.buffer(k_m).difference(xy)
            except Exception:
                continue
            if moat.is_empty:
                continue
            out.append({
                "id": self.new_id(),
                "name": (o.get("name") or "洲") + "环水",
                "category": "water",
                "geometry": xy_geom_to_geojson(moat),
                "tags": {"natural": "water"},
                "ancient_kind": "水域",
            })
            self.water_geom = unary_union([self.water_geom, moat]) \
                if self.water_geom is not None else moat
        if out:
            print("岛屿环水:", len(out), "个（宽 %.0fm）" % k_m)
        return out

    def build_five_temples(self, max_total=FIVE_TEMPLE_MAX):
        """五行神庙：每座神 2 所（城内官修 1 + 城外野庙 1），合计 ≤ max_total。

        - 先数已有（锚点 / 建筑群，如锦香宫内置的玄冥庙）；已存在的格子不再重复放；
        - 城内用 core 采样，城外用 edge 采样（2.5–20km）；避开水面。
        """
        rows = {k: r for k, r in FIVE_TEMPLE_ROWS}
        have = {k: {"城": 0, "外": 0} for k in rows}
        total = 0
        for o in self.objects:
            k = o.get("ancient_kind")
            if k not in rows:
                continue
            total += 1
            p = self._obj_point(o)
            if not p:
                continue
            x, y = lonlat_to_xy(p[0], p[1])
            inside = self.core_poly is not None and self.core_poly.covers(Point(x, y))
            have[k]["城" if inside else "外"] += 1

        core_region = self.core_poly.difference(self.water_geom) \
            if self.water_geom is not None else self.core_poly
        general_region = self.core_poly.buffer(1500).difference(self.water_geom) \
            if self.water_geom is not None else self.core_poly.buffer(1500)
        out = []
        for kind, _row in FIVE_TEMPLE_ROWS:
            for where in ("城", "外"):
                if total >= max_total:
                    break
                if have[kind][where]:
                    continue
                pt = self._sample_zone("core" if where == "城" else "edge",
                                       core_region, general_region)
                if pt is None:
                    continue
                if any(dist_m(pt, Point(o["_x"], o["_y"])) < 60 for o in out):
                    continue
                out.append({
                    "id": self.new_id(), "name": kind, "category": "custom",
                    "geometry": xy_geom_to_geojson(pt), "tags": {},
                    "ancient_kind": kind, "_x": pt.x, "_y": pt.y,
                })
                have[kind][where] += 1
                total += 1
        for o in out:
            o.pop("_x", None)
            o.pop("_y", None)
        print("五行神庙（生成）:", len(out), "| 含已有共:", total)
        return out

    def _nearest_gate(self, lon, lat):
        x, y = lonlat_to_xy(lon, lat)
        minx, miny, maxx, maxy = self.core_poly.bounds
        cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
        candidates = [(maxx, cy), (minx, cy), (cx, miny), (cx, maxy)]
        return min(candidates, key=lambda p: (p[0] - x) ** 2 + (p[1] - y) ** 2)

    # ---------------- 组装 ----------------
    def run(self):
        self.objects = self.load_keep_objects()
        # 注意：不能写成 self.objects += self.buffer_waterways()
        # （Python 会先取旧列表再求值右边，buffer 里换掉的新列表会被丢弃）
        buffered_water = self.buffer_waterways()
        self.objects += buffered_water
        self.objects += self.build_island_moats()   # 岛屿环水（隔断「岛连岸」）
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
            self.objects += self.build_compounds()
            temples = self.build_five_temples()   # 五行神庙（≤10 / 城）
            self.objects += temples
            self._append_frozen_pois(temples)     # 写回冻结表 → 下次重跑不重复

        data = {
            "name": f"{CITY}地图",
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
