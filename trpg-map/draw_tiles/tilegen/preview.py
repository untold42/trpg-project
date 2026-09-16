"""
快速预览：只渲染指定地点周边 N×N 张瓦片，拼成一张大图方便查看。

用法（在 tilegen/ 下）：
    python preview.py                # 默认 z16，扬州城中心，3×3
    python preview.py 16             # 指定 zoom
    python preview.py 16 119.4175 32.41 4   # zoom lon lat span(每边张数)

输出：../_preview/preview_z{zoom}.png
"""

import json
import os
import sys

from config import INPUT_FILE, TILE_SIZE
from projection import lonlat_to_pixel
from spatial_index import build_tile_index
from renderer import generate_tile


def main():

    zoom = int(sys.argv[1]) if len(sys.argv) > 1 else 16
    lon = float(sys.argv[2]) if len(sys.argv) > 2 else 119.4175
    lat = float(sys.argv[3]) if len(sys.argv) > 3 else 32.41
    span = int(sys.argv[4]) if len(sys.argv) > 4 else 3
    tag = sys.argv[5] if len(sys.argv) > 5 else ""

    print(f"预览 z{zoom}  ({lon},{lat})  每边 {span} 张")

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    objects = data.get("objects", [])

    index = build_tile_index(objects, zoom)

    cx, cy = lonlat_to_pixel(lon, lat, zoom)
    tx0 = int(cx // TILE_SIZE)
    ty0 = int(cy // TILE_SIZE)

    size = span * 2 + 1

    canvas = None

    from PIL import Image

    canvas = Image.new(
        "RGB",
        (TILE_SIZE * size, TILE_SIZE * size),
        (255, 0, 255)
    )

    for j in range(size):
        for i in range(size):
            tx = tx0 - span + i
            ty = ty0 - span + j
            layers = index.get((tx, ty))
            if layers is None:
                layers = {
                    "land": [], "water": [], "waterway": [],
                    "wall": [], "road": [], "building": [], "point": []
                }
            img = generate_tile(layers, zoom, tx, ty, save=False)
            canvas.paste(img, (i * TILE_SIZE, j * TILE_SIZE))

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_preview", "latest")
    os.makedirs(out_dir, exist_ok=True)

    out = os.path.join(out_dir, f"preview_z{zoom}{tag}.png")

    try:
        canvas.save(out)
    except OSError:
        # 文件被看图程序占用 → 换个名字
        import time
        out = os.path.join(
            out_dir, f"preview_z{zoom}{tag}_{int(time.time())}.png"
        )
        canvas.save(out)

    print("已保存：", os.path.abspath(out))


if __name__ == "__main__":
    main()
