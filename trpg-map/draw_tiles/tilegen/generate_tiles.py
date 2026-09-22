# -*- coding: utf-8 -*-
"""
generate_tiles.py —— 按「城市画框」逐 zoom 逐瓦片生成。

画框来自 trpg-map/城市.py（与 PBF 裁剪共用同一份），
所以**画框外的数据在 PBF 转 JSON 时就已经不存在了**，这里不再需要自动取景。

性能：瓦片之间互相独立 → 用**线程池**并行。
  numpy / PIL 的 C 运算会释放 GIL，实测 8 线程约 4x（再多受内存带宽限制）。
  可用 TRPG_TILE_WORKERS 覆盖线程数。
"""

import os
import shutil
from concurrent.futures import ThreadPoolExecutor

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

WORKERS = int(os.environ.get("TRPG_TILE_WORKERS", "0") or 0) or max(1, (os.cpu_count() or 4))


def empty_layers():
    return {layer: [] for layer in LAYERS}


def _render(task):
    layers, zoom, tile_x, tile_y = task
    generate_tile(layers, zoom, tile_x, tile_y)


def main():

    print("=" * 60)
    print(f"古代城市地图 Tile Generator —— {CITY}（{WORKERS} 线程）")
    print("=" * 60)
    print("输入：", INPUT_FILE)
    print("输出：", OUTPUT_DIR)
    print("画框：", tuple(round(v, 6) for v in FRAME))

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        objects = json.load(f).get("objects", [])

    print("对象数量：", len(objects))

    # 清空旧瓦片（否则旧版本遗留的瓦片会混进来，sync 时全部拷到前端）
    if os.path.isdir(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    total = 0

    for zoom in range(MIN_ZOOM, MAX_ZOOM + 1):

        min_tx, max_tx, min_ty, max_ty = get_tiles_for_bbox(FRAME, zoom)

        tile_index = build_tile_index(objects, zoom,
                                      (min_tx, max_tx, min_ty, max_ty))

        tasks = []
        for tile_y in range(min_ty, max_ty + 1):
            for tile_x in range(min_tx, max_tx + 1):
                layers = tile_index.get((tile_x, tile_y))
                if layers is None:
                    if SKIP_EMPTY_TILES:
                        continue
                    layers = empty_layers()
                tasks.append((layers, zoom, tile_x, tile_y))

        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            list(ex.map(_render, tasks))

        total += len(tasks)
        print()
        print(f"Zoom {zoom} 完成：{len(tasks)} 张", flush=True)

    print()
    print(f"Tile 生成完成！共 {total} 张")


if __name__ == "__main__":
    main()
