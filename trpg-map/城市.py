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
        "center_lon": 119.4175,
        "center_lat": 32.41,
        "frame_w_km": 100.7,      # 画框宽（东西向）
        "aspect": (16, 9),
    },
    "岳阳": {
        "center_lon": 113.13,
        "center_lat": 29.37,
        "frame_w_km": 100.7,
        "aspect": (16, 9),
    },
}

DEFAULT_CITY = "扬州"


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


def parse_bbox(text):
    """'min_lon,min_lat,max_lon,max_lat' -> tuple。"""
    parts = [float(x) for x in str(text).replace(" ", "").split(",")]
    if len(parts) != 4:
        raise ValueError("bbox 需要 4 个数字：min_lon,min_lat,max_lon,max_lat")
    return tuple(parts)
