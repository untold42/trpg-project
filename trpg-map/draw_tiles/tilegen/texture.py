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


#: 低频道场（色差/污渍/纸浆不匀/霉斑）在 1/COARSE 分辨率上计算，再双线性放大。
#: 这些场都是低频连续函数，降采样看不出来；而逐像素三角函数是瓦片生成的大头。
COARSE = 8


def _coarse_axes(tile_x, tile_y):
    """该瓦片的**全局**粗网格坐标（含右/下各多一格，供双线性）。"""
    g = TILE_SIZE // COARSE
    gx = (np.arange(g + 1) * COARSE + tile_x * TILE_SIZE).astype(np.float64)[None, :]
    gy = (np.arange(g + 1) * COARSE + tile_y * TILE_SIZE).astype(np.float64)[:, None]
    return gx, gy


def _upsample(coarse):
    im = Image.fromarray(np.asarray(coarse, dtype=np.float32), "F")
    return np.asarray(im.resize((TILE_SIZE, TILE_SIZE), Image.BILINEAR),
                      dtype=np.float64)


def _global_grid(tile_x, tile_y):

    gx = (
        np.arange(TILE_SIZE) + tile_x * TILE_SIZE
    ).astype(np.float64)[None, :]

    gy = (
        np.arange(TILE_SIZE) + tile_y * TILE_SIZE
    ).astype(np.float64)[:, None]

    return gx, gy


def _mottle_field(gx, gy):
    return (
        np.sin(gx * 0.0131)
        + np.cos(gy * 0.0173)
        + np.sin((gx + gy) * 0.0091)
    ) / 3.0


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

    s = np.zeros((gy.shape[0], gx.shape[1]))
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

    # 低频场：粗网格算 + 双线性放大（跨瓦片仍连续，因粗坐标对齐全局）
    gx, gy = _coarse_axes(tile_x, tile_y)

    patch = _upsample(_patch_field(gx, gy))
    stain_f = _upsample(_stain_field(gx, gy))
    mottle = _upsample(_mottle_field(gx, gy))

    # 色差：明暗
    shade = 1.0 + PATCH_STRENGTH * patch

    # 色差：冷暖（暖处偏红黄，冷处偏青）
    shade_r = shade * (1.0 + PATCH_HUE * patch)
    shade_g = shade * (1.0 + PATCH_HUE * patch * 0.4)
    shade_b = shade * (1.0 - PATCH_HUE * patch)

    # 污渍
    st = 1.0 - STAIN_STRENGTH * stain_f
    shade_r *= st
    shade_g *= st
    shade_b *= st

    # 霉斑（稀疏；粗网格足够）
    fox = 1.0 - FOXING_STRENGTH * _upsample(_foxing_mask(gx, gy))
    shade_r *= fox
    shade_g *= fox
    shade_b *= fox

    # 三通道合成一次乘法
    arr *= np.stack([shade_r, shade_g, shade_b], axis=2)

    # 低频纸浆不匀（grain 已停用；若要颗粒感请在前端叠可平铺小图）
    arr += mottle[:, :, None] * PAPER_MOTTLE_STRENGTH
    if PAPER_GRAIN_STRENGTH:
        gg, hh = _global_grid(tile_x, tile_y)
        arr += ((_hash01(gg, hh) - 0.5) * PAPER_GRAIN_STRENGTH)[:, :, None]

    # 步长量化：所有瓦片用同一张量化表 → 无接缝，且 PNG 体积减半
    if QUANTIZE_STEP and QUANTIZE_STEP > 1:
        step = QUANTIZE_STEP
        arr = (np.floor(arr / step) * step) + (step / 2.0)

    out = np.clip(arr, 0, 255).astype(np.uint8)

    return Image.fromarray(out, "RGB")
