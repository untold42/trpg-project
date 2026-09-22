# -*- coding: utf-8 -*-
"""
城市.py —— 城市配置（中心 + 画框尺寸）

**为什么需要它**
    以前「PBF 裁剪」和「瓦片取景」是**两套互不相干的逻辑**：
      · PBF 不裁（全量覆盖 190×170 km）
      · 瓦片自己从数据里算一个 16:9 画框
    结果：数据里**绝大部分从来没被画出来**，纯属浪费（扬州 77MB 里只有 63% 有用）。

    现在两边共用**同一份画框定义**：画框外的数据在 PBF 转 JSON 时就直接不生成。

**用法**
    from 城市 import CITIES, frame_bbox
    frame_bbox("扬州")   # -> (min_lon, min_lat, max_lon, max_lat)

新增城市：在 CITIES 里加一条即可（center + frame_w_km）。
"""

import math

M_PER_DEG_LAT = 110574.0


CITIES = {
    "扬州": {
        "map_id": "yangzhou",
        "center_lon": 119.4175,
        "center_lat": 32.41,
        "frame_w_km": 100.7,      # 画框宽（东西向）
        "aspect": (16, 9),
        # 切换地图时玩家的落脚点（切图会把 位置 挪到这里，否则会离新城几百公里）
        "start": {"lon": 119.4282, "lat": 32.3964, "name": "文昌阁"},
    },
    "岳阳": {
        "map_id": "yueyang",
        "center_lon": 113.13,
        "center_lat": 29.37,
        "frame_w_km": 100.7,
        "aspect": (16, 9),
        # 源 PBF：岳阳无独立 extract，用湖南省全量（含完整洞庭湖）
        "pbf": "湖南",
        # 落脚点：岳州城西门（岳阳楼）
        "start": {"lon": 113.0884, "lat": 29.3807, "name": "岳阳楼"},
    },
}

DEFAULT_CITY = "扬州"

#: 城池尺寸档（**方形**，面积 km²）。城市在 CITIES 里写 "尺寸": "20"。
#: 10=州城 / 20=府城 / 30=大府 / 40=巨城 / 50=都城。
CITY_SIZES = {
    "10": 10.0,
    "20": 20.0,
    "30": 30.0,
    "40": 40.0,
    "50": 50.0,
}
DEFAULT_SIZE = "20"


def map_id(city=DEFAULT_CITY):
    """城市 -> 英文 map_id（目录名 / 服务端 TRPG_MAP 用）。"""
    return CITIES[city].get("map_id", city)


def m_per_deg_lon(lat):
    return 111320.0 * math.cos(math.radians(lat))


def km_per_deg_lon(lat):
    return m_per_deg_lon(lat) / 1000.0


def km_per_deg_lat():
    return M_PER_DEG_LAT / 1000.0


def frame_bbox(city=DEFAULT_CITY):
    """城市画框 -> (min_lon, min_lat, max_lon, max_lat)。"""

    c = CITIES[city]

    w = float(c["frame_w_km"])
    h = w * c["aspect"][1] / c["aspect"][0]

    dlon = (w / 2.0) / km_per_deg_lon(c["center_lat"])
    dlat = (h / 2.0) / km_per_deg_lat()

    return (
        c["center_lon"] - dlon,
        c["center_lat"] - dlat,
        c["center_lon"] + dlon,
        c["center_lat"] + dlat,
    )


def center_of(city=DEFAULT_CITY):
    c = CITIES[city]
    return (c["center_lon"], c["center_lat"])


def square_bbox(center_lon, center_lat, area_km2):
    """以 (center_lon, center_lat) 为中心的**方形**城池 bbox，面积 area_km2。

    返回 (min_lon, min_lat, max_lon, max_lat)。边长为 √(面积)，
    经纬方向各自按当地尺度换算，保证是「米制正方形」（等面积、等边长）。
    """
    side = math.sqrt(float(area_km2) * 1_000_000.0)   # 米
    dlat = (side / 2.0) / M_PER_DEG_LAT               # 米 / (米/度)
    dlon = (side / 2.0) / m_per_deg_lon(center_lat)   # 米 / (米/度)
    return (center_lon - dlon, center_lat - dlat,
            center_lon + dlon, center_lat + dlat)


def parse_bbox(text):
    """'min_lon,min_lat,max_lon,max_lat' -> tuple。"""
    parts = [float(x) for x in str(text).replace(" ", "").split(",")]
    if len(parts) != 4:
        raise ValueError("bbox 需要 4 个数字：min_lon,min_lat,max_lon,max_lat")
    return tuple(parts)
