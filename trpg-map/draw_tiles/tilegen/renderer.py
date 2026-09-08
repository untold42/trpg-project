import os

from PIL import Image, ImageDraw

from config import (
    TILE_SIZE,
    OUTPUT_DIR,

    BACKGROUND_COLOR,

    WATER_COLOR,
    WATER_OUTLINE,
    RIVER_COLOR,

    BUILDING_COLOR,
    BUILDING_OUTLINE,

    HISTORIC_BUILDING_COLOR,
    HISTORIC_BUILDING_OUTLINE,

    TEMPLE_COLOR,
    TEMPLE_OUTLINE,

    WALL_COLOR,

    POINT_COLOR,

    GRASS_COLOR
)

from styles import (
    get_landuse_color,
    get_road_style,
    should_draw_building
)

from texture import add_paper_texture


# ============================================================
# 坐标换算
#
# prepare_object 产生的是“全球像素坐标”，
# 渲染单个 Tile 时需要减去当前 Tile 的左上角像素坐标。
# ============================================================

def _local(point, origin_x, origin_y):

    return (
        point[0] - origin_x,
        point[1] - origin_y
    )


def _local_points(points, origin_x, origin_y):

    return [
        _local(point, origin_x, origin_y)
        for point in points
    ]


# ============================================================
# 多边形辅助
# ============================================================

def _iter_polygons(prepared):

    """
    把 Polygon / MultiPolygon 统一成：
    一个生成器，每次 yield 一个“多边形”，
    每个多边形是 [外环, 内环, ...]。
    """

    if prepared["type"] == "Polygon":
        yield prepared["coordinates"]

    elif prepared["type"] == "MultiPolygon":

        for polygon in prepared["coordinates"]:
            yield polygon


def _draw_polygons(
    draw,
    layer,
    origin_x,
    origin_y,
    color_fn,
    outline_fn=None
):

    """
    通用的多边形绘制：
    - 只画外环（忽略内环），避免简单填充把洞填死；
    - 超出 Tile 的部分交给 PIL 自动裁剪。
    """

    for prepared in layer:

        tags = prepared["obj"].get("tags", {})

        fill = color_fn(tags)

        if fill is None:
            continue

        outline = outline_fn(tags) if outline_fn else None

        for polygon in _iter_polygons(prepared):

            if not polygon:
                continue

            outer_ring = _local_points(
                polygon[0],
                origin_x,
                origin_y
            )

            if len(outer_ring) < 3:
                continue

            draw.polygon(
                outer_ring,
                fill=fill,
                outline=outline
            )


# ============================================================
# 各图层绘制
# ============================================================

def _draw_land(draw, layer, origin_x, origin_y):

    def color_fn(tags):
        return get_landuse_color(tags) or GRASS_COLOR

    _draw_polygons(
        draw,
        layer,
        origin_x,
        origin_y,
        color_fn=color_fn
    )


def _draw_water(draw, layer, origin_x, origin_y):

    def color_fn(tags):
        return WATER_COLOR

    def outline_fn(tags):
        return WATER_OUTLINE

    _draw_polygons(
        draw,
        layer,
        origin_x,
        origin_y,
        color_fn=color_fn,
        outline_fn=outline_fn
    )


def _waterway_width(tags, zoom):

    waterway = tags.get("waterway")

    widths = {
        "river": 3,
        "canal": 2,
        "dock": 2,
        "ditch": 1,
        "drain": 1,
        "stream": 1
    }

    base = widths.get(waterway, 1)

    if zoom >= 14 and waterway in ("river", "canal"):
        base += 1

    return base


def _draw_waterways(draw, layer, zoom, origin_x, origin_y):

    for prepared in layer:

        width = _waterway_width(
            prepared["obj"].get("tags", {}),
            zoom
        )

        lines = []

        if prepared["type"] == "LineString":
            lines.append(prepared["coordinates"])

        elif prepared["type"] == "MultiLineString":
            lines.extend(prepared["coordinates"])

        for line in lines:

            local_line = _local_points(
                line,
                origin_x,
                origin_y
            )

            if len(local_line) < 2:
                continue

            draw.line(
                local_line,
                fill=RIVER_COLOR,
                width=width,
                joint="curve"
            )


def _draw_roads(draw, layer, zoom, origin_x, origin_y):

    for prepared in layer:

        style = get_road_style(
            prepared["obj"].get("tags", {}),
            zoom
        )

        if style is None:
            continue

        color, width = style

        lines = []

        if prepared["type"] == "LineString":
            lines.append(prepared["coordinates"])

        elif prepared["type"] == "MultiLineString":
            lines.extend(prepared["coordinates"])

        for line in lines:

            local_line = _local_points(
                line,
                origin_x,
                origin_y
            )

            if len(local_line) < 2:
                continue

            draw.line(
                local_line,
                fill=color,
                width=width,
                joint="curve"
            )


def _draw_wall(draw, layer, zoom, origin_x, origin_y):

    """城墙：粗深色线，随 zoom 变粗。"""

    width = 3 if zoom < 13 else (5 if zoom < 15 else 7)

    for prepared in layer:

        lines = []

        if prepared["type"] == "LineString":
            lines.append(prepared["coordinates"])

        elif prepared["type"] == "MultiLineString":
            lines.extend(prepared["coordinates"])

        for line in lines:

            local_line = _local_points(
                line,
                origin_x,
                origin_y
            )

            if len(local_line) < 2:
                continue

            draw.line(
                local_line,
                fill=WALL_COLOR,
                width=width,
                joint="curve"
            )


def _building_colors(tags):

    building = tags.get("building")
    amenity = tags.get("amenity")

    if (
        building == "temple"
        or amenity in ("temple", "place_of_worship")
        or tags.get("religion")
    ):
        return TEMPLE_COLOR, TEMPLE_OUTLINE

    if (
        tags.get("historic")
        or building in ("monument", "museum")
    ):
        return (
            HISTORIC_BUILDING_COLOR,
            HISTORIC_BUILDING_OUTLINE
        )

    return BUILDING_COLOR, BUILDING_OUTLINE


def _draw_buildings(draw, layer, zoom, origin_x, origin_y):

    for prepared in layer:

        tags = prepared["obj"].get("tags", {})

        if not should_draw_building(tags, zoom):
            continue

        fill, outline = _building_colors(tags)

        for polygon in _iter_polygons(prepared):

            if not polygon:
                continue

            outer_ring = _local_points(
                polygon[0],
                origin_x,
                origin_y
            )

            if len(outer_ring) < 3:
                continue

            draw.polygon(
                outer_ring,
                fill=fill,
                outline=outline
            )


# ============================================================
# 主入口
# ============================================================

def generate_tile(layers, zoom, tile_x, tile_y):

    """
    生成单张 256x256 的 PNG 瓦片。

    参数
    ----
    layers : dict
        由 spatial_index.build_tile_index 产生的图层字典，
        每个图层是 prepared 对象列表。
    zoom / tile_x / tile_y : int
        瓦片的 z/x/y 编号。
    """

    img = Image.new(
        "RGB",
        (TILE_SIZE, TILE_SIZE),
        BACKGROUND_COLOR
    )

    draw = ImageDraw.Draw(img)

    origin_x = tile_x * TILE_SIZE
    origin_y = tile_y * TILE_SIZE

    # 绘制顺序：土地 -> 水 -> 河流 -> 道路 -> 建筑 -> POI
    _draw_land(
        draw,
        layers.get("land", []),
        origin_x,
        origin_y
    )

    _draw_water(
        draw,
        layers.get("water", []),
        origin_x,
        origin_y
    )

    _draw_waterways(
        draw,
        layers.get("waterway", []),
        zoom,
        origin_x,
        origin_y
    )

    _draw_roads(
        draw,
        layers.get("road", []),
        zoom,
        origin_x,
        origin_y
    )

    _draw_wall(
        draw,
        layers.get("wall", []),
        zoom,
        origin_x,
        origin_y
    )

    _draw_buildings(
        draw,
        layers.get("building", []),
        zoom,
        origin_x,
        origin_y
    )

    add_paper_texture(img, tile_x, tile_y)

    out_dir = os.path.join(
        OUTPUT_DIR,
        str(zoom),
        str(tile_x)
    )

    os.makedirs(out_dir, exist_ok=True)

    img.save(
        os.path.join(out_dir, f"{tile_y}.png")
    )

    return img
