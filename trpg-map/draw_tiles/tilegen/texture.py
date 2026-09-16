"""
纸纹：色差（柔和深浅 + 冷暖偏色）+ 污渍 / 霉斑 + 细颗粒。

全部基于「全局像素坐标」计算（连续函数，无需周期化）→ 跨瓦片无接缝。
（褶皱 / 手绘线条抖动已移除。）
"""

import numpy as np

from PIL import Image

from config import (
    TILE_SIZE,
    PAPER_GRAIN_STRENGTH,
    PAPER_MOTTLE_STRENGTH,
    PATCH_STRENGTH,
    PATCH_HUE,
    STAIN_STRENGTH,
    FOXING_COUNT,
    FOXING_STRENGTH,
    QUANTIZE_STEP,
)


def _hash01(gx, gy):

    h = np.sin(gx * 12.9898 + gy * 78.233) * 43758.5453

    return h - np.floor(h)


def _global_grid(tile_x, tile_y):

    gx = (
        np.arange(TILE_SIZE) + tile_x * TILE_SIZE
    ).astype(np.float64)[None, :]

    gy = (
        np.arange(TILE_SIZE) + tile_y * TILE_SIZE
    ).astype(np.float64)[:, None]

    return gx, gy


# ============================================================
# 色差：柔和的深浅 / 冷暖区块
#
# 用几组互不成整数倍的平面波叠加，得到没有周期感、没有网格感的
# 有机区块。因为是全局坐标的连续函数，跨瓦片自然衔接。
# ============================================================

_PATCH_WAVES = (
    (0.0021, 0.0043, 1.00),
    (0.0057, -0.0028, 0.75),
    (-0.0039, 0.0061, 0.60),
    (0.0083, 0.0034, 0.45),
    (0.0013, -0.0091, 0.38),
)


def _patch_field(gx, gy):

    s = np.zeros((TILE_SIZE, TILE_SIZE))
    wsum = 0.0

    for i, (a, b, w) in enumerate(_PATCH_WAVES):

        s += w * np.sin(a * gx + b * gy + i * 1.7)
        wsum += w

    return s / wsum


# ============================================================
# 污渍：陈年水渍 / 霉变（只压暗，不成块边界）
# ============================================================

def _stain_field(gx, gy):
    s = (
        np.sin(gx * 0.0031 + gy * 0.0022)
        + np.cos(gx * 0.0017 - gy * 0.0043)
        + np.sin((gx - gy) * 0.0013)
    ) / 3.0

    return 0.5 + 0.5 * s


def _foxing_mask(gx, gy):
    """稀疏霉斑：硬阀值，只有 0 / 1 两种值（否则 PNG 会爆炸）。"""
    n = _hash01(gx * 0.37, gy * 0.41)
    return (n > 1.0 - FOXING_COUNT).astype(np.float64)


# ============================================================
# 主入口
# ============================================================

def add_paper_texture(img, tile_x, tile_y):

    arr = np.asarray(img).astype(np.float64)

    gx, gy = _global_grid(tile_x, tile_y)

    patch = _patch_field(gx, gy)

    # 色差：明暗
    shade = 1.0 + PATCH_STRENGTH * patch

    # 色差：冷暖（暖处偏红黄，冷处偏青）
    shade_r = shade * (1.0 + PATCH_HUE * patch)
    shade_g = shade * (1.0 + PATCH_HUE * patch * 0.4)
    shade_b = shade * (1.0 - PATCH_HUE * patch)

    # 污渍
    stain = 1.0 - STAIN_STRENGTH * _stain_field(gx, gy)

    shade_r *= stain
    shade_g *= stain
    shade_b *= stain

    # 霉斑
    fox = 1.0 - FOXING_STRENGTH * _foxing_mask(gx, gy)
    shade_r *= fox
    shade_g *= fox
    shade_b *= fox

    arr[:, :, 0] *= shade_r
    arr[:, :, 1] *= shade_g
    arr[:, :, 2] *= shade_b

    # 细颗粒 + 低频纸浆不匀
    grain = _hash01(gx, gy) - 0.5
    mottle = (
        np.sin(gx * 0.0131)
        + np.cos(gy * 0.0173)
        + np.sin((gx + gy) * 0.0091)
    ) / 3.0

    arr += (
        grain * PAPER_GRAIN_STRENGTH
        + mottle * PAPER_MOTTLE_STRENGTH
    )[:, :, None]

    # 步长量化：所有瓦片用同一张量化表 → 无接缝，且 PNG 体积减半
    if QUANTIZE_STEP and QUANTIZE_STEP > 1:
        step = QUANTIZE_STEP
        arr = (np.floor(arr / step) * step) + (step / 2.0)

    out = np.clip(arr, 0, 255).astype(np.uint8)

    return Image.fromarray(out, "RGB")
