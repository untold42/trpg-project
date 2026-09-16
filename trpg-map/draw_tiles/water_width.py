# -*- coding: utf-8 -*-
"""
water_width.py —— 水道宽度规则（米）

**单一真相源**：渲染、建库、碰撞都从这里取宽度，不在别处另写一份。

宽度优先级（从高到低）：
    1. OSM 的 `width` 标签（若有）
    2. 名字特判（大江大河，如 长江）
    3. 水道类型（river / canal / stream / ditch / drain / dock）
    4. 默认值
"""

import re


# ============================================================
# 按水道类型
# ============================================================

WATERWAY_WIDTH_M = {
    "river": 80.0,       # 普通河流（大江大河由下面的名字表覆盖）
    "canal": 50.0,       # 运河 / 渠
    "stream": 15.0,      # 小溪
    "ditch": 6.0,        # 沟
    "drain": 6.0,        # 排水沟
    "dock": 40.0,        # 船坞
    "dam": 15.0,         # 坝（本身不是水道，给个细条）
    "weir": 15.0,        # 堰
}

WATERWAY_DEFAULT_M = 8.0


# ============================================================
# 按名字特判（大江大河）
#
# 这些河在 OSM 里常常只有中心线（没有水面多边形），
# 必须靠这里的宽度 buffer 成面，否则会被当成一根细线。
# ============================================================

WATERWAY_WIDTH_BY_NAME = {
    # 长江水系
    "长江": 1500.0,
    "扬子江": 1500.0,
    "滁河": 200.0,
    # 运河水系
    "京杭大运河": 120.0,
    "京杭运河": 120.0,
    "大运河": 120.0,
    "古运河": 90.0,
    "通扬运河": 60.0,
    "新通扬运河": 60.0,
    # 洞庭湖水系（岳阳）
    "湘江": 800.0,
    "资水": 400.0,
    "沅水": 400.0,
    "澧水": 300.0,
    "汨罗江": 200.0,
    "新墙河": 300.0,
    "藕池河": 250.0,
    # 其它常见大河
    "汉水": 800.0,
    "汉江": 800.0,
    "淮河": 500.0,
    "黄河": 800.0,
    "赣江": 600.0,
    "钱塘江": 1000.0,
}


# ============================================================
# 解析 OSM 长度字符串
# ============================================================

_FT_TO_M = 0.3048


def parse_length_m(raw):
    """把 '12'、'12 m'、'12m'、'30 ft'、'0.5 km' 解析成米；失败返回 None。"""

    if raw is None:
        return None

    s = str(raw).strip().lower()

    m = re.match(r"^([0-9]*\.?[0-9]+)", s)
    if not m:
        return None

    try:
        v = float(m.group(1))
    except ValueError:
        return None

    rest = s[m.end():].strip()

    if rest.startswith("km"):
        v *= 1000.0
    elif rest.startswith("ft") or rest.startswith("'"):
        v *= _FT_TO_M
    # 'm' / 空 / 其它 → 当米

    return v if v > 0 else None


# ============================================================
# 对外入口
# ============================================================

def width_m(tags=None, name=None):
    """返回该水道的宽度（米）。"""

    tags = tags or {}

    # 1) OSM 显式 width
    v = parse_length_m(tags.get("width"))
    if v:
        return v

    # 2) 名字特判
    #    先精确匹配；再模糊匹配，但**只允许**：
    #      - 长度 >= 3 的键（如 京杭大运河）
    #      - 长度 == 2 的键，且出现在名字**开头**（如 “长江南京段”）
    #    这样可避免 “小秦淮河” 命中 “淮河” 这类误判。
    if name:
        if name in WATERWAY_WIDTH_BY_NAME:
            return WATERWAY_WIDTH_BY_NAME[name]

        best_key = None
        best_w = None
        for key, w in WATERWAY_WIDTH_BY_NAME.items():
            hit = (len(key) >= 3 and key in name) or \
                  (len(key) == 2 and name.startswith(key))
            if hit and (best_key is None or len(key) > len(best_key)):
                best_key, best_w = key, w
        if best_w is not None:
            return best_w

    # 3) 类型
    wt = tags.get("waterway")
    if wt in WATERWAY_WIDTH_M:
        return WATERWAY_WIDTH_M[wt]

    # 4) 默认
    return WATERWAY_DEFAULT_M


def half_width_m(tags=None, name=None):
    return width_m(tags, name) / 2.0
