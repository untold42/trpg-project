import os

import numpy as np

from PIL import Image, ImageDraw

from config import (
    TILE_SIZE,
    OUTPUT_DIR,

    BACKGROUND_COLOR,

    WATER_COLOR,
    WATER_OUTLINE,
    RIVER_COLOR,

    WALL_COLOR,

    FARMLAND_HATCH,
    FOREST_DOT,
    SCRUB_DOT,
)

from styles import (
    get_land_style,
    get_road_style,
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
# 全局网格（纹理图案用；跨瓦片连续）
# ============================================================

def _global_grid(tile_x, tile_y):

    gx = (
        np.arange(TILE_SIZE) + tile_x * TILE_SIZE
    ).astype(np.float64)[None, :]

    gy = (
        np.arange(TILE_SIZE) + tile_y * TILE_SIZE
    ).astype(np.float64)[:, None]

    return gx, gy


def _hash01(gx, gy):

    h = np.sin(gx * 12.9898 + gy * 78.233) * 43758.5453

    return h - np.floor(h)


def _overlay_mask(img, selected, color, alpha=1.0):

    if not selected.any():
        return

    data = (selected.astype(np.float64) * alpha * 255.0)

    mask = Image.fromarray(
        np.clip(data, 0, 255).astype(np.uint8),
        "L"
    )

    img.paste(
        Image.new("RGB", img.size, color),
        (0, 0),
        mask
    )


def _polygon_mask(ring, origin_x, origin_y):

    mask = Image.new("L", (TILE_SIZE, TILE_SIZE), 0)

    ImageDraw.Draw(mask).polygon(
        _local_points(ring, origin_x, origin_y),
        fill=255
    )

    return np.asarray(mask) > 0


# ============================================================
# 多边形 / 折线辅助
# ============================================================

def _iter_polygons(prepared):

    if prepared["type"] == "Polygon":
        yield prepared["coordinates"]

    elif prepared["type"] == "MultiPolygon":

        for polygon in prepared["coordinates"]:
            yield polygon


def _iter_lines(prepared):

    if prepared["type"] == "LineString":
        yield prepared["coordinates"]

    elif prepared["type"] == "MultiLineString":

        for line in prepared["coordinates"]:
            yield line


# ============================================================
# 土地
# ============================================================

def _draw_land(img, draw, layer, zoom, tile_x, tile_y, origin_x, origin_y):

    gx, gy = _global_grid(tile_x, tile_y)

    dots = _hash01(gx, gy) > 0.972
    hatch = ((gx + gy) % 7.0) < 1.0

    forest_fill = get_land_style({"landuse": "forest"})[0]

    for prepared in layer:

        tags = prepared["obj"].get("tags", {})

        fill, pattern = get_land_style(tags)

        if fill is None:
            continue

        for polygon in _iter_polygons(prepared):

            if not polygon:
                continue

            outer_ring = _local_points(polygon[0], origin_x, origin_y)

            if len(outer_ring) < 3:
                continue

            draw.polygon(outer_ring, fill=fill)

            if pattern is None or zoom < 13:
                continue

            inside = _polygon_mask(polygon[0], origin_x, origin_y)

            if pattern == "dot":

                color = FOREST_DOT if fill == forest_fill else SCRUB_DOT

                _overlay_mask(img, inside & dots, color, alpha=0.75)

            elif pattern == "hatch":

                _overlay_mask(img, inside & hatch, FARMLAND_HATCH, alpha=0.55)


# ============================================================
# 水（面）
# ============================================================

def _draw_water(draw, layer, zoom, origin_x, origin_y):

    from config import WATER_EDGE_M
    from projection import meters_to_px

    edge_w = meters_to_px(WATER_EDGE_M, zoom, minimum=1, maximum=6)

    for prepared in layer:

        for polygon in _iter_polygons(prepared):

            if not polygon:
                continue

            ring = _local_points(polygon[0], origin_x, origin_y)

            if len(ring) < 3:
                continue

            draw.polygon(ring, fill=WATER_COLOR)

            draw.line(
                ring + [ring[0]],
                fill=WATER_OUTLINE,
                width=edge_w,
                joint="curve"
            )


# ============================================================
# 水道（线）
# ============================================================

def _waterway_width(tags, zoom):

    from config import WATERWAY_WIDTH_M, WATERWAY_DEFAULT_M
    from projection import meters_to_px

    waterway = tags.get("waterway")

    width_m = WATERWAY_WIDTH_M.get(waterway, WATERWAY_DEFAULT_M)

    return meters_to_px(width_m, zoom, minimum=1, maximum=64)


def _draw_waterways(draw, layer, zoom, origin_x, origin_y):

    for prepared in layer:

        tags = prepared["obj"].get("tags", {})

        # 已被水面多边形覆盖的水道：不画。
        # （否则水面中央会多出一条深色中线；见 build_world.buffer_waterways）
        if tags.get("covered") == "yes":
            continue

        width = _waterway_width(tags, zoom)

        for line in _iter_lines(prepared):

            local_line = _local_points(line, origin_x, origin_y)

            if len(local_line) < 2:
                continue

            draw.line(
                local_line,
                fill=RIVER_COLOR,
                width=width,
                joint="curve"
            )


# ============================================================
# 道路（单色，无描边）
# ============================================================

def _draw_roads(draw, layer, zoom, origin_x, origin_y):

    for prepared in layer:

        style = get_road_style(
            prepared["obj"].get("tags", {}),
            zoom
        )

        if style is None:
            continue

        color, width = style

        for line in _iter_lines(prepared):

            local_line = _local_points(line, origin_x, origin_y)

            if len(local_line) < 2:
                continue

            draw.line(
                local_line,
                fill=color,
                width=width,
                joint="curve"
            )


# ============================================================
# 城墙（纯黑实心）
# ============================================================

def _draw_wall(draw, layer, zoom, origin_x, origin_y):

    from config import WALL_WIDTH_M
    from projection import meters_to_px

    width = meters_to_px(WALL_WIDTH_M, zoom, minimum=3, maximum=72)

    for prepared in layer:

        for line in _iter_lines(prepared):

            local_line = _local_points(line, origin_x, origin_y)

            if len(local_line) < 2:
                continue

            draw.line(
                local_line,
                fill=WALL_COLOR,
                width=width,
                joint="curve"
            )


# ============================================================
# 主入口
# ============================================================

def generate_tile(layers, zoom, tile_x, tile_y, save=True):

    img = Image.new(
        "RGB",
        (TILE_SIZE, TILE_SIZE),
        BACKGROUND_COLOR
    )

    draw = ImageDraw.Draw(img)

    origin_x = tile_x * TILE_SIZE
    origin_y = tile_y * TILE_SIZE

    _draw_land(
        img, draw,
        layers.get("land", []),
        zoom, tile_x, tile_y, origin_x, origin_y
    )

    _draw_water(
        draw,
        layers.get("water", []),
        zoom,
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

    img = add_paper_texture(img, tile_x, tile_y)

    if save:

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
