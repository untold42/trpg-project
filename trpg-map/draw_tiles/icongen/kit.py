# -*- coding: utf-8 -*-
"""
南宋建筑地图图标 · 工具箱（kit）
================================

这套工具箱把「画一张南宋建筑图标」拆成可复用的构件，目标是**下次画新建筑时只需拼装**。

核心约定
--------
1. 所有坐标写在 **128x128 逻辑空间**（1 个单位 = 最终 1 像素），内部自动乘 `S=4` 超采样，
   最后 LANCZOS 缩回 128 —— 天然抗锯齿，不需要手写抗锯齿。
2. 画完 `body` 后必须走 `compose(shadow, body)`：它负责加 **墨色 keyline**（剪影描边）。
   地图瓦片纸色是 (238,231,207)，石墙/粉墙很容易和它撞色，keyline 是分离度的保证。
3. 最后 `fit_icon()` 自适应裁边留白到 ~100/128，与既有 53 张图标的规格一致。

快速上手（画一个新建筑）
------------------------
    from kit import *

    def render_mybuilding():
        body, d = blank()
        shadow = ground_shadow()                      # 地面淡墨影（可选）

        rect(d, 40, 102, 88, 110, fill=STONE_DK)      # 台基
        rect(d, 44, 70, 84, 102, fill=STONE, width=1.4)   # 墙身
        band(d, 44, 95, 84, 102, STONE_DK)            # 墙脚水渍（脏感来源）

        eave(d, 64, 32, 68, 5, 6)                     # 腰檐
        roof(d, 64, 40, 9, 28, 50, 38)                # 主檐（歇山顶）
        lantern(d, 32, 62, )                          # 灯笼
        lantern(d, 96, 62)

        return compose(shadow, body)

然后 `python gen_map_icons.py mybuilding --preview --small 40` 就能看 ASCII 校验。
"""

from __future__ import annotations

import argparse
import os
import shutil
import time
from collections import Counter

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# --------------------------------------------------------------------------
# 画布规格
# --------------------------------------------------------------------------
S = 4           # 超采样倍数
BASE = 128      # 逻辑画布边长（= 输出尺寸）
FIT = 100       # 自适应留白后内容占据的边长（既有图标均为 ~100/128）

# --------------------------------------------------------------------------
# 色板（v4 石砖脏色版，全项目共用；新建筑请优先复用，不要新造色相）
# --------------------------------------------------------------------------
INK = (52, 46, 42, 255)             # 墨线
INK_SOFT = (52, 46, 42, 80)         # 淡墨（地面影）
STONE = (160, 150, 132, 255)        # 石砖墙身（脏灰褐；比瓦顶亮 48，40px 下才分得开）
STONE_DK = (116, 108, 94, 255)      # 石砖暗（台基 / 墙脚水渍）
TILE = (98, 106, 108, 255)          # 青瓦
TILE_DK = (72, 80, 82, 255)         # 青瓦暗（瓦垄 / 正脊）
TILE_LT = (134, 144, 146, 255)      # 青瓦亮（檐口滴水）
VERM = (140, 82, 68, 255)           # 朱红（脏砖红：柱 / 匾 / 灯盖）
LANTERN = (158, 88, 70, 255)        # 灯笼
GLOW = (232, 200, 142, 255)         # 窗火（柔暖黄，夜景唯一亮点）
GLOW_DK = (204, 170, 116, 255)      # 堂内灯火（同色相深一档）—— 大面积亮部用它，避免刺眼
ROSE = (152, 98, 98, 255)           # 胭脂（逆光深玫瑰）
FIGURE = (88, 66, 60, 255)          # 人物剪影（衬在窗火上）

# 校验用色表（字母 → 颜色）。注意：字母要挑**彼此距离足够远**的颜色，
# 否则 ascii_class() 会把边缘混合色判到隔壁类，读图时白费力气。
CLASSES = [
    ("T", TILE), ("K", TILE_DK), ("t", TILE_LT), ("R", VERM), ("l", LANTERN),
    ("S", STONE), ("s", STONE_DK), ("Y", GLOW), ("y", GLOW_DK), ("P", ROSE), ("F", FIGURE),
    ("#", INK), (".", INK_SOFT),
]

# 瓦垄默认位置（比例：0 = 正脊端，1 = 檐角端）。这是调过手感的值，直接复用。
RIBS = (0.34, 0.58, 0.82)

# --------------------------------------------------------------------------
# 日/夜两套色板
# --------------------------------------------------------------------------
# 夜色（默认）：就是上面那套「脏石砖 + 灯火」
# 日色：同一色相整体提亮、灯火炮灭（窗/门变成暗洞口），故建筑白天不自发光
# 白昼**只改光照，不改材质**：石还是那个石、瓦还是那个瓦，
# 变的是「灯灭不灭」与「有没有日照投影」。
LIT = True                                 # 夜里：点灯（窗火 + 灯笼光晕）
DAY_PALETTE = {
    "LIT": False,                          # 白昼：不点灯
    "GLOW": (92, 86, 76, 255),             # 窗/门 → 未点灯的洞口（暗）
    "GLOW_DK": (84, 78, 69, 255),
}


def with_palette(overrides, fn, mods=None):
    """临时替换色板后调用 render 函数 → **同一份绘图代码出日/夜两张图**。

    必须**同时改 kit 与 buildings 两个模块**：
      · `roof()/eave()/lantern()/figure()/drum()` 等构件定义在本模块，读的是本模块全局；
      · render 函数里直接写的颜色名，读的是 `buildings` 的全局（`from kit import *` 拷过去的）。
    第一版只改了 buildings，结果日图的屋顶仍是夜色（主色还是夜 TILE）—— 吃过这个亏。

        day = with_palette(kit.DAY_PALETTE, buildings.render_qinglou)
    """
    if mods is None:
        import sys
        mods = [globals()]
        for _n in ("buildings", "archetypes"):      # 新增绘图模块要登记到这里
            _m = sys.modules.get(_n)
            if _m is not None:
                mods.append(_m)
    saved = []
    for m in mods:
        d = m if isinstance(m, dict) else m.__dict__   # globals() 给的是 dict，模块要取 __dict__
        for k, v in overrides.items():
            if k in d:
                saved.append((d, k, d[k]))
                d[k] = v
    try:
        return fn()
    finally:
        for d, k, v in saved:
            d[k] = v


# --------------------------------------------------------------------------
# 基础绘图原语（全部接受 128 逻辑坐标，内部自动乘 S）
# --------------------------------------------------------------------------
def _sc(pts):
    return [(x * S, y * S) for x, y in pts]


def poly(d, pts, fill=None, outline=INK, width=2.0, joint="curve"):
    """多边形：先填充，再沿边界**居中**描边。

    陷阱：PIL 的 d.polygon() 不描边；描边必须自己用 d.line(p+[p[0]])，
    好处是描边居中（向外扩 width/2），细长构件不会被描边吃掉。
    """
    p = _sc(pts)
    if fill is not None:
        d.polygon(p, fill=fill)
    if outline is not None and width:
        d.line(p + [p[0]], fill=outline, width=max(1, int(width * S)), joint=joint)


def rect(d, x0, y0, x1, y1, fill=None, outline=INK, width=1.6, radius=0.0):
    """矩形。**必须走 poly 而不是 d.rectangle(outline=, width=)**：

    陷阱：PIL 的 rectangle(outline=..., width=...) 把描边画在矩形**内部**。
    4px 宽的柱子配 1.4px 描边，朱红只剩 1px —— 实测踩过，廊柱根本红不起来。
    有圆角时才用 rounded_rectangle（券门那种尺寸够大，吃得消）。
    """
    if radius:
        d.rounded_rectangle([x0 * S, y0 * S, x1 * S, y1 * S], radius=radius * S, fill=fill,
                            outline=outline if outline else None,
                            width=max(1, int(width * S)) if outline else 0)
        return
    poly(d, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], fill=fill, outline=outline, width=width)


def seg(d, pts, color=INK, width=1.6):
    """折线/直线，描边居中。"""
    d.line(_sc(pts), fill=color, width=max(1, int(width * S)), joint="curve")


def ellipse(d, x0, y0, x1, y1, fill=None, outline=INK, width=1.6):
    d.ellipse([x0 * S, y0 * S, x1 * S, y1 * S], fill=fill,
              outline=outline if outline else None,
              width=max(1, int(width * S)) if outline else 0)


def band(d, x0, y0, x1, y1, color=STONE_DK):
    """无描边的色带 —— 用来做**墙脚水渍 / 风化**，这是「脏」的主要来源。
    放在墙身之后、门窗之前画，门窗会自然压在渍线之上。"""
    rect(d, x0, y0, x1, y1, fill=color, outline=None)


def blank():
    """新建超采样画布，返回 (body, draw)。body 是建筑本体层（不含影子）。"""
    img = Image.new("RGBA", (BASE * S, BASE * S), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def ground_shadow(box=(30, 104, 98, 114), alpha=85, blur=3.2):
    """地面淡墨影（高斯模糊，柔化落地）。注意：它**不参与 keyline**，见 compose()。"""
    sh = Image.new("RGBA", (BASE * S, BASE * S), (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse([box[0] * S, box[1] * S, box[2] * S, box[3] * S],
                               fill=(52, 46, 42, alpha))
    return sh.filter(ImageFilter.GaussianBlur(blur * S))


# --------------------------------------------------------------------------
# 建筑构件（均已验证配方，直接调用即可）
# --------------------------------------------------------------------------
def roof_solid(cx, half_w, ridge_half, ridge_y, eave_center_y, tip_y, n=160):
    """中国屋顶正面轮廓（**核心公式**）：返回 (上缘, 下缘) 两条点列。

    三种屋顶靠参数切换（正面看只差在平脊长度与檐口曲度）：
      · 攒尖顶（亭/塔）：ridge_half ≈ 0 + 加宝顶
      · 庑殿顶：ridge_half ≈ 0.35 * half_w
      · 歇山顶：ridge_half ≈ 0.22 * half_w（本图标用 9/40），可再加博风/山花

    几何要点
      · 上缘：中段平脊（|x-cx| <= ridge_half），两侧按 `d*(2-d)` 下落
        —— 先陡后缓，就是宋《营造法式》「举折」的观感。
      · 下缘：檐口在角部**上翘**（`u*(2-u)`，u = 1-d），中间微垂 → 飞檐翘角。
      · 两条边在角部（d=1）汇于同一点，屋面自然收成尖角。
    """
    top, bot = [], []
    span = max(1e-6, half_w - ridge_half)
    for i in range(n + 1):
        x = cx - half_w + 2 * half_w * i / n
        d = abs(x - cx)
        d = 0.0 if d <= ridge_half else min(1.0, (d - ridge_half) / span)
        y_top = ridge_y + (tip_y - ridge_y) * (d * (2 - d))
        u = 1.0 - d
        y_bot = tip_y + (eave_center_y - tip_y) * (u * (2 - u))
        top.append((x, y_top))
        bot.append((x, y_bot))
    return top, bot


def eave_band(cx, half_w, base_y, sag, lift, n=140):
    """腰檐 / 披檐 / 雨篷：一条中间微垂、两角上翘的**带状**（不是实心屋面）。
    返回 (上缘, 下缘)。厚度在中段约为 sag*0.66，到角部收细 → 檐口薄而利。"""
    top, bot = [], []
    for i in range(n + 1):
        x = cx - half_w + 2 * half_w * i / n
        d = min(1.0, abs(x - cx) / half_w)
        bot.append((x, base_y + sag * (1 - d * d) - lift * (d ** 3)))
        top.append((x, base_y + sag * 0.34 * (1 - d * d) - lift * 1.18 * (d ** 3)))
    return top, bot


def roof(d, cx, half_w, ridge_half, ridge_y, eave_center_y, tip_y,
         ribs=RIBS, ridge_bar=True, chiwei=True, edge=2.0):
    """画一整套官式屋面：瓦面 + 檐口滴水 + 瓦垄 + 正脊 + 鸱尾。

    这是画南宋建筑**最省事的一步**：调好 6 个数字就是一座屋顶。
        cx            中轴
        half_w        檐口半宽（决定屋顶总宽）
        ridge_half    平脊半长（决定屋顶类型，见 roof_solid）
        ridge_y       正脊高度（屋顶最高点）
        eave_center_y 檐口中点高度（决定屋面进深观感）
        tip_y         檐角高度（比 eave_center_y 小 → 翘角）
    """
    top, bot = roof_solid(cx, half_w, ridge_half, ridge_y, eave_center_y, tip_y)
    poly(d, top + bot[::-1], fill=TILE, width=edge)
    seg(d, bot, TILE_LT, 1.4)                                  # 檐口滴水提亮
    for f in ribs:                                             # 瓦垄
        for sgn in (-1, 1):
            x = cx + sgn * (ridge_half + (half_w - ridge_half) * f)
            u = 1.0 - f
            y0 = ridge_y + (tip_y - ridge_y) * (f * (2 - f))
            y1 = tip_y + (eave_center_y - tip_y) * (u * (2 - u))
            seg(d, [(x, y0), (x, y1)], TILE_DK, 1.0)
    if not LIT:                                                # 白昼：檐下日照阴影
        shadow_band(d, bot, drop=2.0, thick=4.6)
    if ridge_bar:                                              # 正脊
        seg(d, [(cx - ridge_half, ridge_y), (cx + ridge_half, ridge_y)], TILE_DK, 3.2)
    if chiwei:                                                 # 鸱尾（南宋作鳍状，非后世龙吻）
        for sgn in (-1, 1):
            x = cx + sgn * ridge_half
            poly(d, [(x + sgn * 0.5, ridge_y + 1), (x + sgn * 5.5, ridge_y - 4.8),
                     (x + sgn * 3.2, ridge_y + 1)], fill=INK, outline=None)
    # 提示：鸱尾必须 **outline=None**。小三角配居中描边会整块变黑，第一版就吃了这个亏。


def eave(d, cx, half_w, base_y, sag=5.0, lift=6.0, edge=2.0):
    """腰檐（下层檐口）：`eave_band` + 檐口滴水。"""
    top, bot = eave_band(cx, half_w, base_y, sag, lift)
    poly(d, top + bot[::-1], fill=TILE, width=edge)
    seg(d, bot, TILE_LT, 1.3)
    if not LIT:                                                # 白昼：檐下阴影
        shadow_band(d, bot, drop=2.0, thick=4.0)


def shadow_band(d, curve, drop=2.0, thick=4.5, alpha=64):
    """沿一条檐口曲线往下投一道半透明阴影 —— **白昼的日照投影**。
    这是日图区别于夜图的主要手段（不改材质色）。"""
    band = [(x, y + drop) for x, y in curve] +            [(x, y + drop + thick) for x, y in reversed(curve)]
    p = _sc(band)
    d.polygon(p, fill=(52, 46, 42, alpha))


def lantern(d, x, hang_y, body_top=71.5, w=8.0, h=9.5):
    """灯笼。夜里带暖光晕（LIT=True），白天就是一只普通红灯。"""
    if LIT:
        glow = Image.new("RGBA", (BASE * S, BASE * S), (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse(
            [(x - w) * S, (body_top - 2) * S, (x + w) * S, (body_top + h + 2) * S],
            fill=(238, 196, 120, 120))
        d._image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(2.6 * S)))
    """灯笼（吊绳 + 灯盖 + 灯身 + 流苏）。默认 8x9.5 —— 低模下保持"小红点"体量。
    hang_y 一般取檐角高度，灯身会挂在檐下外侧。"""
    seg(d, [(x, hang_y), (x, body_top - 0.5)], INK, 1.0)
    rect(d, x - w / 4, body_top - 1, x + w / 4, body_top + 0.5, fill=VERM, width=0.9)
    ellipse(d, x - w / 2, body_top, x + w / 2, body_top + h, fill=LANTERN, width=1.0)
    seg(d, [(x, body_top + h), (x, body_top + h + 2.5)], VERM, 1.0)


def window_glow(d, x0, y0, x1, y1, rose=None, mullions=0, width=1.3):
    """灯火窗。rose=帘宽时在左右各压一道胭脂纱帘（风月/内室的关键线索）。
    亮度关系靠色板保证：窗火 203 > 纱帘 114 > 人影 72（亮度实测值）。"""
    rect(d, x0, y0, x1, y1, fill=GLOW, width=width)
    if mullions:
        for k in range(1, mullions + 1):
            xm = x0 + (x1 - x0) * k / (mullions + 1)
            seg(d, [(xm, y0), (xm, y1)], VERM_DARK_LINE, 0.85)
    if rose:
        rect(d, x0, y0, x0 + rose, y1, fill=ROSE, width=1.1)
        rect(d, x1 - rose, y0, x1, y1, fill=ROSE, width=1.1)


VERM_DARK_LINE = VERM   # 窗棂用脏砖红而非墨，避免细线糊成一团黑


def figure(d, x, foot_y, h=14.0, pose="stand", color=FIGURE):
    """人物剪影：头 + 肩身 + 手臂。默认高 14（约 40px 下 4.4px）。

    头径 0.28h、肩宽 0.42h、下摆 0.5h —— **肩宽 6~7px 才像人**；
    实测肩宽 10~13 会被用户一句“太魁梧”打回。

    pose:  "stand" 立姿 / "dance" 扬袖（长袖舞） / "lean" 凭栏
    """
    hw = h * 0.21                       # 肩半宽
    hd = h * 0.28                       # 头径
    top = foot_y - h
    ellipse(d, x - hd / 2, top, x + hd / 2, top + hd, fill=color, width=0.9)
    shy = top + hd * 0.92               # 肩线
    poly(d, [(x - hw, shy), (x + hw, shy), (x + hw * 1.18, foot_y), (x - hw * 1.18, foot_y)],
         fill=color, width=0.9)
    if pose == "dance":                 # 扬袖：两臂斜上外张（乐舞的最强识别符号）
        seg(d, [(x - hw * 0.8, shy + 1), (x - hw * 2.0, shy - h * 0.16)], color, 1.5)
        seg(d, [(x + hw * 0.8, shy + 1), (x + hw * 2.0, shy - h * 0.16)], color, 1.5)
    elif pose == "lean":                # 凭栏：一臂前伸
        seg(d, [(x + hw * 0.6, shy + 1), (x + hw * 2.8, shy + 1.6)], color, 1.3)


def drum(d, x, foot_y, w=13.0, h=9.0, body=VERM, headc=GLOW):
    """大鼓（乐舞/宴饮场面的符号物）：鼓身 + 鼓面亮边 + 鼓架。"""
    top = foot_y - h
    rect(d, x - w / 2, top, x + w / 2, foot_y, fill=body, width=1.1, radius=h * 0.38)
    seg(d, [(x - w / 2 + 1.4, top + h * 0.3), (x + w / 2 - 1.4, top + h * 0.3)], headc, 1.5)
    for sgn in (-1, 1):                                        # 鼓架
        seg(d, [(x + sgn * w * 0.3, foot_y), (x + sgn * w * 0.44, foot_y + 2.6)], INK, 1.2)


def add_keyline(img, grow=1.4, color=INK):
    """给整幅剪影包一圈墨色描边（贴纸式）。
    为什么必须有：地图瓦片纸色 (238,231,207)，而石墙 (144,134,118) 距离 162 尚可，
    但早期粉墙 (218,209,190) 距离只有 34 —— 不勾边墙就直接糊进纸里。
    做法：对 alpha 通道做 MaxFilter 膨胀，铺一层纯色，再把本体叠上去。
    于是膨胀环只在「本体原本透明」处显形，内部不受影响。
    """
    k = int(grow * S) * 2 + 1
    grown = img.getchannel("A").filter(ImageFilter.MaxFilter(k))
    layer = Image.new("RGBA", img.size, color)
    layer.putalpha(grown)
    layer.alpha_composite(img)
    return layer


def compose(shadow, body):
    """合成最终图：影子在最底（不参与 keyline），建筑本体带 keyline 压在上面。"""
    out = Image.new("RGBA", (BASE * S, BASE * S), (0, 0, 0, 0))
    if shadow is not None:
        out.alpha_composite(shadow)
    out.alpha_composite(add_keyline(body))
    return out


# --------------------------------------------------------------------------
# 收尾：自适应留白
# --------------------------------------------------------------------------
def fit_icon(img, size=BASE, target=FIT):
    """裁到内容边界 → 等比缩放到 target 边长 → 居中放回 size 画布 → 缩到输出尺寸。
    保证所有图标内容占比一致（~100/128），地图上大小才统一。

    ⚠️ **必须对 alpha 取阈值再求 bbox**：地面那道淡影是 alpha≈85、横跨 22~106 的大椭圆，
    直接 getbbox() 会把它算成内容边界 → 真正的主体被压小，
    40px 下只剩一条细缝（garden 28×10、water 30×7、monument 12×15 就是这么废掉的）。
    """
    solid = img.getchannel("A").point(lambda v: 255 if v > 128 else 0)
    bbox = solid.getbbox() or img.getchannel("A").getbbox()
    if not bbox:
        return img.resize((size, size), Image.LANCZOS)
    crop = img.crop(bbox)
    k = (target * S) / max(crop.size)
    crop = crop.resize((max(1, round(crop.width * k)), max(1, round(crop.height * k))), Image.LANCZOS)
    canvas = Image.new("RGBA", (size * S, size * S), (0, 0, 0, 0))
    canvas.paste(crop, ((canvas.width - crop.width) // 2, (canvas.height - crop.height) // 2), crop)
    return canvas.resize((size, size), Image.LANCZOS)


# --------------------------------------------------------------------------
# 校验工具（本 AI 看不见图片，靠这几个"眼睛"）
# --------------------------------------------------------------------------
def _nearest_class(px):
    r, g, b, a = px
    best, bd = "?", 1e9
    for ch, (cr, cg, cb, _) in CLASSES:
        dist = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
        if dist < bd:
            bd, best = dist, ch
    return best


def ascii_alpha(img, w=64, h=32):
    """轮廓图：只看 alpha，判断剪影是否成立、有没有破洞/悬空。"""
    a = img.getchannel("A").resize((w, h), Image.BOX)
    px = a.load()
    chars = " .:-=+*#%@"
    return "\n".join("".join(chars[min(9, px[x, y] * 10 // 256)] for x in range(w)) for y in range(h))


def ascii_class(img, w=96, h=48):
    """配色分区图：每格取「纯像素(alpha>=200)中出现最多的颜色类」。
    注意**不要**用缩放平均（Image.BOX）再判色 —— 平均会把墨线与亮面混成中间色，
    整张图会误报成一片泥。"""
    W, H = img.size
    px = img.load()
    out = []
    for ry in range(h):
        y0, y1 = int(ry * H / h), max(int(ry * H / h) + 1, int((ry + 1) * H / h))
        row = []
        for rx in range(w):
            x0, x1 = int(rx * W / w), max(int(rx * W / w) + 1, int((rx + 1) * W / w))
            cnt = Counter()
            for y in range(y0, y1):
                for x in range(x0, x1):
                    r, g, b, a = px[x, y]
                    if a >= 200:
                        cnt[_nearest_class((r, g, b, a))] += 1
            row.append(cnt.most_common(1)[0][0] if cnt else " ")
        out.append("".join(row))
    return "\n".join(out)


def scan(img, ys):
    """扫描线：指定 y 上逐像素报色块。**排版错位的唯一可靠检查手段**。
    例：y=88 | 38-39:# 40-44:R 46-54:Y 59-69:Y 73-80:Y 84-87:R
    （= 墙线 / 左柱 / 左窗 / 中门 / 右窗 / 右柱）"""
    px = img.load()
    for y in ys:
        runs, prev, start = [], None, 0
        for x in range(img.width):
            r, g, b, a = px[x, y]
            c = " " if a < 128 else _nearest_class((r, g, b, a))
            if c != prev:
                if prev is not None:
                    runs.append((start, x - 1, prev))
                prev, start = c, x
        runs.append((start, img.width - 1, prev))
        runs = [q for q in runs if q[2] != " " or (q[1] - q[0]) > 2]
        print("y=%3d | " % y + " ".join("%d-%d:%s" % q for q in runs))


def small_view(img, size):
    """按地图上的**真实显示尺寸**再预览一遍。这一步不能省：
    前端 iconSizeFor() 在 z15 只有 40px，细节多寡的取舍全看这一关。"""
    tiny = img.resize((size, size), Image.LANCZOS)
    print("--- %dpx 实际显示尺寸（上：轮廓 / 下：配色）---" % size)
    print(ascii_alpha(tiny, w=size, h=size // 2))
    print(ascii_class(tiny, w=size, h=size // 2))


def stats(img, sizes=(40, 64, 128)):
    """客观指标：不透明像素数 / 平均亮度 / 亮暗占比 / 平均纯度。
    用来回答"会不会太暗、太花、太闷"这类主观问题的**可比较**版本。
    实测基准：旧线稿图标 meanL=0、纯色徽章 meanL 95~120。"""
    import colorsys

    for size in sizes:
        t = img.resize((size, size), Image.LANCZOS)
        px = [p for p in t.get_flattened_data() if p[3] > 40]
        if not px:
            continue
        lum = [0.299 * r + 0.587 * g + 0.114 * b for r, g, b, a in px]
        sat = sum(colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)[1] for r, g, b, a in px) / len(px)
        print("%3dpx: 不透明 %4d/%5d  meanL %5.1f  纯度 %2.0f%%  亮>150 %2.0f%%  暗<=90 %2.0f%%" % (
            size, len(px), size * size, sum(lum) / len(lum), 100 * sat,
            100 * sum(1 for l in lum if l > 150) / len(lum),
            100 * sum(1 for l in lum if l <= 90) / len(lum)))


def preview(img, scan_ys=()):
    print("--- 轮廓（alpha）---")
    print(ascii_alpha(img))
    print("--- 配色分区 ---")
    print(ascii_class(img))
    if scan_ys:
        print("--- 扫描线 ---")
        scan(img, scan_ys)
    print("图例: " + " ".join("%s=%s" % (c, n) for c, n in (
        ("T", "青瓦"), ("K", "瓦暗"), ("t", "瓦亮"), ("R", "砖红"), ("l", "灯笼"),
        ("S", "石墙"), ("s", "石暗"), ("Y", "窗火"), ("y", "堂火"), ("P", "胭脂"), ("F", "人影"),
        ("#", "墨线"), (".", "淡墨"))))


def make_sheet(img, name, sizes=(40, 48, 64, 128), paper=(238, 231, 207), suffix=""):
    """出「贴在地图纸色上」的多尺寸预览图，给**人**看。
    本 AI 看不到图片，审美判断必须交给用户，这张图就是给他的验收材料。"""
    W = 40 + sum(s + 22 for s in sizes)
    sheet = Image.new("RGBA", (W, 210), paper + (255,))
    d = ImageDraw.Draw(sheet)
    try:
        f = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 15)
        fs = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 13)
    except Exception:
        f = fs = ImageFont.load_default()
    d.text((16, 8), "%s —— 贴在地图瓦片纸色 (238,231,207) 上" % name, fill=(60, 50, 42), font=f)
    x = 16
    for s in sizes:
        sheet.alpha_composite(img.resize((s, s), Image.LANCZOS), (x, 46 + (128 - s) // 2))
        d.text((x, 186), "%dpx" % s, fill=(90, 80, 70), font=fs)
        x += s + 22
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_preview", "%s%s_sheet.png" % (name, suffix))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    sheet.convert("RGB").save(out)
    return out


# --------------------------------------------------------------------------
# CLI 骨架：新建筑不用再写入口
# --------------------------------------------------------------------------
def _backup(path, here):
    """写入前备份同名旧文件（时间戳命名，避免反复调参时互相覆盖）。"""
    bak = os.path.join(here, "_backup")
    os.makedirs(bak, exist_ok=True)
    name = "%s.%s.png" % (os.path.splitext(os.path.basename(path))[0],
                          time.strftime("%m%d-%H%M%S"))
    shutil.copy2(path, os.path.join(bak, name))
    print("已备份 →", os.path.join(bak, name))


def _safe_save(img, out, tries=6):
    """先写临时文件再原子替换。

    坑：在 Windows（尤其桌面开了 OneDrive / 杀软实时扫描）直接 img.save(同名文件)
    会偶发 OSError EINVAL —— 与路径无关，是文件被瞬时占用，实测踩过两次。
    """
    tmp = os.path.join(os.path.dirname(out), ".%s.tmp" % os.path.basename(out))
    img.save(tmp, format="PNG")        # 必须显式指定：PIL 靠扩展名猜格式，.tmp 会报 unknown file extension
    last = None
    for _ in range(tries):
        try:
            os.replace(tmp, out)
            return
        except OSError as e:            # 目标被占用 → 稍等重试
            last = e
            time.sleep(0.3)
    raise last


def cli(buildings, default, argv=None):
    """单张设计 / 校验入口。批量生产走 make_icons.py。"""
    here = os.path.dirname(os.path.abspath(__file__))
    mapicons = os.path.normpath(os.path.join(here, "..", "..", "..",
                                            "trpg-client", "public", "mapicons"))
    ap = argparse.ArgumentParser(description="南宋建筑地图图标生成器（单张设计 / 校验）")
    ap.add_argument("building", nargs="?", default=default, choices=sorted(buildings))
    ap.add_argument("-o", "--out", default=None, help="指定输出文件（配合 --mode day|night）")
    ap.add_argument("--mode", choices=["day", "night", "both"], default="both",
                    help="出哪一面；默认两面都出（day 走 DAY_PALETTE）")
    ap.add_argument("--preview", action="store_true", help="只打印 ASCII 校验图")
    ap.add_argument("--no-fit", action="store_true",
                    help="不做自适应留白（保留排版坐标，便于扫描校对）")
    ap.add_argument("--scan", default="", help="逗号分隔的 y 值，打印扫描线")
    ap.add_argument("--small", type=int, default=0, help="按指定像素尺寸再预览（如 40）")
    ap.add_argument("--stats", action="store_true", help="打印亮度/纯度客观指标")
    ap.add_argument("--sheet", action="store_true", help="出多尺寸预览图给用户看")
    ap.add_argument("--backup", action="store_true", help="写入前备份同名旧文件（带时间戳）")
    args = ap.parse_args(argv)

    fn = buildings[args.building]

    def render(mode):
        """night = 原色（夜色）；day = 换日色板（同一份绘图代码）。"""
        return fn() if mode == "night" else with_palette(DAY_PALETTE, fn)

    # ---- 预览：默认看夜色（原稿）；--mode day 可看日色 ----
    if args.preview:
        img = render("day" if args.mode == "day" else "night")
        img = img.resize((BASE, BASE), Image.LANCZOS) if args.no_fit else fit_icon(img)
        if args.small:
            small_view(img, args.small)
        preview(img, [int(v) for v in args.scan.split(",") if v.strip()])
        if args.stats:
            print("--- 客观指标 ---")
            stats(img)
        return

    # ---- 落盘：默认 <mapicons>/<building>/{day,night}.png ----
    out_dir = os.path.dirname(os.path.abspath(args.out)) if args.out         else os.path.join(mapicons, args.building)
    modes = ["day", "night"] if args.mode == "both" else [args.mode]
    for mode in modes:
        path = os.path.abspath(args.out) if (args.out and args.mode != "both")             else os.path.join(out_dir, mode + ".png")
        img = fit_icon(render(mode))
        if args.backup and os.path.exists(path):
            _backup(path, here)
        _safe_save(img, path)
        print("已生成 →", path, img.size, "内容 bbox =", img.getchannel("A").getbbox())
        if args.stats:
            stats(img)
        if args.sheet:
            print("预览图 →", make_sheet(img, args.building, suffix="-" + mode))
