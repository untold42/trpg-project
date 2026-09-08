from geometry import (
    prepare_object,
    get_pixel_bbox
)

from classifier import classify_object
from projection import lonlat_to_pixel


LAYERS = (
    "land",
    "water",
    "waterway",
    "wall",
    "road",
    "building",
    "point"
)


def build_tile_index(objects, zoom):

    print("建立空间索引...")

    tile_index = {}

    prepared_count = 0

    for obj in objects:

        prepared = prepare_object(
            obj,
            zoom,
            lonlat_to_pixel
        )

        if prepared is None:
            continue

        prepared_count += 1

        bbox = get_pixel_bbox(prepared)

        if bbox is None:
            continue

        prepared["bbox"] = bbox

        object_type = classify_object(
            prepared
        )

        if object_type == "other":
            continue

        min_x, min_y, max_x, max_y = bbox

        min_tile_x = int(min_x // 256)
        max_tile_x = int(max_x // 256)

        min_tile_y = int(min_y // 256)
        max_tile_y = int(max_y // 256)

        for tile_y in range(
            min_tile_y,
            max_tile_y + 1
        ):

            for tile_x in range(
                min_tile_x,
                max_tile_x + 1
            ):

                key = (
                    tile_x,
                    tile_y
                )

                if key not in tile_index:

                    tile_index[key] = {
                        layer: []
                        for layer in LAYERS
                    }

                tile_index[key][
                    object_type
                ].append(prepared)

    print("空间索引建立完成")

    print(
        "准备对象：",
        prepared_count
    )

    print(
        "索引 Tile 数量：",
        len(tile_index)
    )

    return tile_index