from config import (
    FARMLAND_COLOR,
    FOREST_COLOR,
    GRASS_COLOR,
    CEMETERY_COLOR,
    SCRUB_COLOR,
    BARE_ROCK_COLOR,
    WETLAND_COLOR,

    PRIMARY_COLOR,
    PRIMARY_FILL,
    SECONDARY_COLOR,
    SECONDARY_FILL,
    TERTIARY_COLOR,
    TERTIARY_FILL,
    RESIDENTIAL_COLOR,
    RESIDENTIAL_FILL,
    OTHER_ROAD_COLOR,
    OTHER_ROAD_FILL,

    BUILDING_COLOR,
    BUILDING_OUTLINE,

    HISTORIC_BUILDING_COLOR,
    HISTORIC_BUILDING_OUTLINE,

    TEMPLE_COLOR,
    TEMPLE_OUTLINE
)


# ============================================================
# 土地：返回 (填充色, 纹理类型)
#
# 纹理类型供 renderer 决定是否叠加点阵 / 斜线：
#   None   普通平涂
#   "dot"  密点（林地、灌木）
#   "hatch" 斜线（农田）
# ============================================================

def get_land_style(tags):

    landuse = tags.get("landuse")
    natural = tags.get("natural")

    if landuse == "farmland":
        return FARMLAND_COLOR, "hatch"

    if landuse in ("forest", "wood") or natural == "wood":
        return FOREST_COLOR, "dot"

    if natural == "scrub":
        return SCRUB_COLOR, "dot"

    if landuse in (
        "grass",
        "meadow",
        "recreation_ground",
        "village_green"
    ) or natural in ("grassland", "heath"):
        return GRASS_COLOR, None

    if landuse == "cemetery":
        return CEMETERY_COLOR, None

    if natural == "bare_rock":
        return BARE_ROCK_COLOR, None

    if natural == "wetland":
        return WETLAND_COLOR, None

    return None, None


def get_landuse_color(tags):

    """兼容旧调用：只要填充色。"""

    return get_land_style(tags)[0]


def should_draw_building(tags, zoom):

    """保留（瓦片不再画房屋；POI 由前端 icon 承担）。"""

    return False


# ============================================================
# 道路：(颜色, 宽度)
#
# 无描边；官道最深，巷最浅（颜色区分）。
# 宽度由「真实米数」换算（config.ROAD_WIDTH_M）。
# ============================================================

_ROAD_TABLE = {
    "primary": PRIMARY_COLOR,
    "secondary": SECONDARY_COLOR,
    "tertiary": TERTIARY_COLOR,
    "residential": RESIDENTIAL_COLOR,
    "living_street": RESIDENTIAL_COLOR,
    "unclassified": OTHER_ROAD_COLOR,
    "road": OTHER_ROAD_COLOR,
}


def get_road_style(tags, zoom):

    from config import ROAD_WIDTH_M, ROAD_WIDTH_SCALE
    from projection import meters_to_px

    highway = tags.get("highway")

    if highway not in _ROAD_TABLE:
        return None

    if highway == "service":
        return None

    width_m = ROAD_WIDTH_M.get(highway)

    if width_m is None:
        return None

    floor = 2 if (highway in ("primary", "secondary") and zoom <= 13) else 1

    width_px = meters_to_px(
        width_m, zoom, scale=ROAD_WIDTH_SCALE, minimum=floor
    )

    # 低 zoom 下细巷（1px）不画，避免路面糊成一片
    if zoom <= 12 and width_px <= 1:
        return None

    return (_ROAD_TABLE[highway], width_px)
