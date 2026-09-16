# -*- coding: utf-8 -*-
"""
generate_tiles.py —— 按「城市画框」逐 zoom 逐瓦片生成。

画框来自 trpg-map/城市.py（与 PBF 裁剪共用同一份），
所以**画框外的数据在 PBF 转 JSON 时就已经不存在了**，这里不再需要自动取景。
"""

import json

from config import (
    INPUT_FILE,
    MIN_ZOOM,
    MAX_ZOOM,
    SKIP_EMPTY_TILES,
    FRAME,
    CITY,
    TILE_SIZE,
    OUTPUT_DIR,
)

from projection import get_tiles_for_bbox

from spatial_index import (
    build_tile_index,
    LAYERS,
)

from renderer import generate_tile


def empty_layers():
    return {layer: [] for layer in LAYERS}


def main():

    print("=" * 60)
    print(f"古代城市地图 Tile Generator —— {CITY}")
    print("=" * 60)
    print("输入：", INPUT_FILE)
    print("输出：", OUTPUT_DIR)
    print("画框：", tuple(round(v, 6) for v in FRAME))

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        objects = json.load(f).get("objects", [])

    print("对象数量：", len(objects))

    total = 0

    for zoom in range(MIN_ZOOM, MAX_ZOOM + 1):

        print()
        print("=" * 60)
        print(f"生成 Zoom: {zoom}")
        print("=" * 60)

        min_tx, max_tx, min_ty, max_ty = get_tiles_for_bbox(FRAME, zoom)

        tile_index = build_tile_index(objects, zoom)

        generated = 0

        for tile_y in range(min_ty, max_ty + 1):
            for tile_x in range(min_tx, max_tx + 1):

                layers = tile_index.get((tile_x, tile_y))

                if SKIP_EMPTY_TILES and layers is None:
                    continue

                if layers is None:
                    layers = empty_layers()

                generate_tile(layers, zoom, tile_x, tile_y)

                generated += 1

        total += generated

        print(f"Zoom {zoom} 完成：{generated} 张")

    print()
    print(f"Tile 生成完成！共 {total} 张")


if __name__ == "__main__":
    main()
