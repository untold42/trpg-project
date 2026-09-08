import json

from config import (
    INPUT_FILE,
    MIN_ZOOM,
    MAX_ZOOM,
    SKIP_EMPTY_TILES,
    CONTENT_CENTER_LON,
    CONTENT_CENTER_LAT,
    CONTENT_MAX_KM,
    MAP_ASPECT_W,
    MAP_ASPECT_H,
    MAP_MARGIN_FRACTION
)

from projection import (
    get_tiles_for_bbox,
    haversine_km,
    expand_bbox_to_aspect
)

from geometry import (
    get_points_from_geometry
)

from spatial_index import (
    build_tile_index
)

from renderer import (
    generate_tile
)


def calculate_map_bbox(objects):

    min_lon = float("inf")
    min_lat = float("inf")

    max_lon = float("-inf")
    max_lat = float("-inf")

    valid_objects = []

    for obj in objects:

        points = get_points_from_geometry(
            obj.get("geometry")
        )

        if not points:
            continue

        valid_objects.append(obj)

        for lon, lat in points:

            min_lon = min(min_lon, lon)
            max_lon = max(max_lon, lon)

            min_lat = min(min_lat, lat)
            max_lat = max(max_lat, lat)

    return (
        min_lon,
        min_lat,
        max_lon,
        max_lat,
        valid_objects
    )


def get_content_frame(objects):

    """
    自动取景：
    1. 只统计离 CONTENT_CENTER 在 CONTENT_MAX_KM 以内的对象；
    2. 用它们的外接矩形作为“内容范围”；
    3. 以中心为基准外扩成 16:9，并加留白。

    远处的铁路/边界等“尾巴”不参与取景，
    但它们的几何体只要伸进画框对应的瓦片里，仍然会被绘制。
    """

    min_lon = float("inf")
    min_lat = float("inf")

    max_lon = float("-inf")
    max_lat = float("-inf")

    counted = 0

    for obj in objects:

        points = get_points_from_geometry(
            obj.get("geometry")
        )

        if not points:
            continue

        max_extent = max(
            haversine_km(
                CONTENT_CENTER_LON,
                CONTENT_CENTER_LAT,
                lon,
                lat
            )
            for lon, lat in points
        )

        if max_extent > CONTENT_MAX_KM:
            continue

        counted += 1

        for lon, lat in points:

            min_lon = min(min_lon, lon)
            max_lon = max(max_lon, lon)

            min_lat = min(min_lat, lat)
            max_lat = max(max_lat, lat)

    if counted == 0:
        return None

    content_bbox = (
        min_lon,
        min_lat,
        max_lon,
        max_lat
    )

    frame = expand_bbox_to_aspect(
        content_bbox,
        MAP_ASPECT_W,
        MAP_ASPECT_H,
        MAP_MARGIN_FRACTION
    )

    print(
        f"取景：{counted} 个对象在 {CONTENT_MAX_KM}km 内"
    )

    print(
        f"内容范围：{content_bbox}"
    )

    print(
        f"16:9 画框（含留白）：{frame}"
    )

    return frame


def main():

    print("=" * 60)
    print("古代扬州地图 Tile Generator")
    print("=" * 60)

    with open(
        INPUT_FILE,
        "r",
        encoding="utf-8"
    ) as f:

        data = json.load(f)

    objects = data.get(
        "objects",
        []
    )

    print(
        "对象数量：",
        len(objects)
    )

    bbox = get_content_frame(objects)

    if bbox is None:

        (
            min_lon,
            min_lat,
            max_lon,
            max_lat,
            valid_objects
        ) = calculate_map_bbox(objects)

        bbox = (
            min_lon,
            min_lat,
            max_lon,
            max_lat
        )

    else:

        valid_objects = objects

    for zoom in range(
        MIN_ZOOM,
        MAX_ZOOM + 1
    ):

        print()
        print("=" * 60)
        print(f"生成 Zoom: {zoom}")
        print("=" * 60)

        (
            min_tile_x,
            max_tile_x,
            min_tile_y,
            max_tile_y
        ) = get_tiles_for_bbox(
            bbox,
            zoom
        )

        tile_index = build_tile_index(
            valid_objects,
            zoom
        )

        generated = 0

        for tile_y in range(
            min_tile_y,
            max_tile_y + 1
        ):

            for tile_x in range(
                min_tile_x,
                max_tile_x + 1
            ):

                layers = tile_index.get(
                    (tile_x, tile_y)
                )

                if SKIP_EMPTY_TILES and layers is None:
                    continue

                if layers is None:

                    layers = {
                        "land": [],
                        "water": [],
                        "waterway": [],
                        "wall": [],
                        "road": [],
                        "building": [],
                        "point": []
                    }

                generate_tile(
                    layers,
                    zoom,
                    tile_x,
                    tile_y
                )

                generated += 1

        print(
            f"Zoom {zoom} 完成："
            f"{generated} 张"
        )

    print()
    print("Tile 生成完成！")


if __name__ == "__main__":
    main()