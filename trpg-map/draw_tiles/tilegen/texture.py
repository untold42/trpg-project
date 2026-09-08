import random
from PIL import Image, ImageDraw

from config import TILE_SIZE


def add_paper_texture(img, tile_x, tile_y):
    """
    给地图瓦片添加轻微的宣纸颗粒纹理。

    只保留细小颗粒，不添加大面积斑驳。
    """

    rng = random.Random(
        tile_x * 73856093 +
        tile_y * 19349663
    )

    draw = ImageDraw.Draw(img)

    # 宣纸颗粒数量
    grain_count = int(TILE_SIZE * TILE_SIZE * 0.025)

    for _ in range(grain_count):
        x = rng.randrange(TILE_SIZE)
        y = rng.randrange(TILE_SIZE)

        # 以较浅的灰褐色作为纸张颗粒
        value = rng.choice([
            145,
            155,
            165,
            175,
            185,
        ])

        # RGB 模式下直接使用较浅颜色，
        # 让颗粒和背景发生非常轻微的对比
        draw.point(
            (x, y),
            fill=(value, value - 5, value - 15)
        )

    return img
