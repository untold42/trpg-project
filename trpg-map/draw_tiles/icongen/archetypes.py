# -*- coding: utf-8 -*-
"""
南宋建筑地图图标 · 原型库（archetypes）
======================================

54 个 icon 键不可能一个个手写。这里做的是**参数化原型**：同一套「脏石砖 + 青瓦 + 朱红 + 灯火」
的低模语言，靠 `SPECS` 参数表派生出全部键。

设计口径（与 kit 一致）
  · 只有 6 个色相：墨 / 石 / 青瓦 / 朱红 / 灯火 / 胭脂（同色相可多档深浅）
  · 一切门窗洞口走 `opening()`/`window_glow()` → 自动跟随昼夜（`kit.LIT`）
  · 底噪统一：台基(STONE_DK) → 墙身(STONE) → 墙脚水渍(STONE_DK) → 屋面(TILE)
  · 竖向骨架：屋面 y≈22~52，墙身 52~86，台基 86~102，踏道 102~110

每个原型 = 一个 `arch_xxx(d, **params)`；`render(key)` 查 SPECS 并调用。
"""

from kit import *   # noqa: F401,F403


# ==========================================================================
# 通用构件
# ==========================================================================
def podium(d, x0, x1, ground=102, h=12, steps=None, color=STONE_DK):
    """台基（上窄下宽梯形）+ 可选踏道。"""
    y = ground - h
    poly(d, [(x0 + 4, y), (x1 - 4, y), (x1, ground), (x0, ground)], fill=color, width=1.8)
    if steps:
        sx0, sx1 = steps
        poly(d, [(sx0, ground), (sx1, ground), (sx1 + 2.5, ground + 7), (sx0 - 2.5, ground + 7)],
             fill=STONE, width=1.2)
        seg(d, [(sx0 - 1.2, ground + 3.4), (sx1 + 1.2, ground + 3.4)], INK, 1.0)


def body(d, x0, x1, top, ground, stain=True, pillar=0.0, pillar_n=2):
    """墙身 + 墙脚水渍 + 角柱。"""
    rect(d, x0, top, x1, ground, fill=STONE, width=2.0)
    if stain:
        band(d, x0, ground - 5.5, x1, ground)
    if pillar:
        rect(d, x0, top, x0 + pillar, ground, fill=VERM, width=1.1)
        if pillar_n > 1:
            rect(d, x1 - pillar, top, x1, ground, fill=VERM, width=1.1)


def opening(d, x0, y0, x1, y1, radius=0.0, width=1.3):
    """门洞 / 敞口。**用 GLOW 填充 → 昼夜自动切换**（夜亮、昼暗）。"""
    if radius:
        rect(d, x0, y0, x1, y1, fill=GLOW, width=width, radius=radius)
    else:
        rect(d, x0, y0, x1, y1, fill=GLOW, width=width)


def lamp(d, x, y, r=2.6, plate=True):
    """一星光（夜里亮、白天暗）。用于门内、窗口一点暖光。"""
    if plate:
        rect(d, x - r, y - r, x + r, y + r, fill=GLOW, width=1.0)


def baoding(d, cx, top_y):
    """宝顶（攒尖顶用）。"""
    poly(d, [(cx, top_y - 5.5), (cx + 2.6, top_y - 2.6), (cx, top_y + 0.4), (cx - 2.6, top_y - 2.6)],
         fill=VERM, width=0.9)


def roof_style(d, style, cx, half, base_y, h=22, ribs=RIBS):
    """屋面四式（正面视差：只在平脊长度与檐口曲度）。

    gable   悬山/硬山 —— 民居、店铺（直线坡 + 正脊）
    xieshan 歇山顶   —— 厅堂、楼阁（最常用）
    hip     庑殿顶   —— 殿宇、官署（等级最高）
    pyramid 攒尖顶   —— 亭、塔、仓囷（加宝顶）
    """
    if style == "gable":
        ridge_y, g = base_y - h, 3.0
        poly(d, [(cx - half, base_y), (cx - half - g, ridge_y), (cx + half + g, ridge_y),
                 (cx + half, base_y)], fill=TILE, width=2.0)
        for f in (0.3, 0.55, 0.8):                     # 瓦垄：没有它屋顶就是一整块平色
            for sgn in (-1, 1):
                x = cx + sgn * half * f
                seg(d, [(x, ridge_y + (base_y - ridge_y) * f), (x, base_y)], TILE_DK, 1.1)
        seg(d, [(cx - half - g, ridge_y), (cx + half + g, ridge_y)], TILE_DK, 3.2)
        seg(d, [(cx - half, base_y), (cx + half, base_y)], TILE_LT, 1.6)
        if not LIT:
            shadow_band(d, [(cx - half, base_y), (cx + half, base_y)], drop=1.6, thick=4.2)
        return
    rh = {"xieshan": 0.26, "hip": 0.42, "pyramid": 0.0}[style] * half
    ridge_y = base_y - h
    tip_y = base_y - h * 0.42
    roof(d, cx, half, rh, ridge_y, base_y, tip_y, ribs=ribs,
         chiwei=(style != "pyramid"))
    if style == "pyramid":
        baoding(d, cx, ridge_y)


def sign_board(d, x, y, w=20, h=6, color=VERM):
    """匾额 / 招牌：一块横板（低模下不写字）。"""
    rect(d, x - w / 2, y, x + w / 2, y + h, fill=color, width=1.1)
    seg(d, [(x - w * 0.26, y + h / 2), (x + w * 0.26, y + h / 2)], INK, 1.2)


def hanging_sign(d, x, top_y, h=13, w=6.5, color=VERM):
    """竖幌子（店招）。夜里是暗红布，不发光。"""
    seg(d, [(x, top_y), (x, top_y + 2)], INK, 1.2)
    poly(d, [(x - w / 2, top_y + 2), (x + w / 2, top_y + 2), (x + w / 2, top_y + h),
             (x - w / 2, top_y + h)], fill=color, width=1.1)


def sunblind(d, x0, x1, y, sag=2.6, color=TILE_DK):
    """雨篷 / 布幔（店面前檐）。"""
    poly(d, [(x0, y), (x1, y), (x1, y + 3.4 + sag), (x0, y + 3.4 + sag)], fill=color, width=1.1)


def fence(d, x0, x1, y, h=8, posts=5):
    """篱 / 矮栏。"""
    for i in range(posts):
        x = x0 + (x1 - x0) * i / (posts - 1)
        seg(d, [(x, y), (x, y + h)], INK, 1.2)
    seg(d, [(x0, y + 2.2), (x1, y + 2.2)], INK, 1.1)
    seg(d, [(x0, y + h - 1.6), (x1, y + h - 1.6)], INK, 1.1)


def tree(d, x, ground, h=17, r=5.4):
    """树（松/杂树，低模两笔）。"""
    seg(d, [(x, ground), (x, ground - h * 0.42)], INK, 1.8)
    poly(d, [(x - r, ground - h * 0.34), (x, ground - h), (x + r, ground - h * 0.34)],
         fill=TILE_DK, width=1.1)


def mound(d, cx, base_y, w=26, h=15):
    """土丘 / 山。"""
    poly(d, [(cx - w / 2, base_y), (cx - w * 0.16, base_y - h), (cx + w * 0.1, base_y - h * 0.72),
             (cx + w / 2, base_y)], fill=TILE, width=1.2)


def waves(d, x0, x1, y, rows=3, gap=4.0):
    """水面波纹。"""
    for i in range(rows):
        yy = y + i * gap
        n = 4 if i % 2 == 0 else 3
        for j in range(n):
            xx = x0 + (x1 - x0) * (j + 0.5) / n
            seg(d, [(xx - 4.5, yy), (xx, yy - 1.6), (xx + 4.5, yy)], TILE, 1.5)


def boat_hull(d, cx, y, w=44, h=9):
    """船身（上宽下尖）+ 篷。"""
    poly(d, [(cx - w / 2, y), (cx + w / 2, y), (cx + w * 0.36, y + h), (cx - w * 0.36, y + h)],
         fill=TILE_DK, width=1.3)
    poly(d, [(cx - w * 0.22, y), (cx + w * 0.22, y), (cx + w * 0.18, y - h * 0.82),
             (cx - w * 0.18, y - h * 0.82)], fill=TILE, width=1.2)


# ==========================================================================
# 原型
# ==========================================================================
def arch_shop(d, cx=64, half=24, ground=102, floors=1, roof="gable", sign=True,
              hanging=False, awning=False, lanterns=0, door=(0, 0), win=2, **kw):
    """铺面 / 作坊 / 民宅：单层为主，招牌+雨篷+幌子区分行业。

    窄铺面（half<23）时窗口会撞角柱、幌子会压柱子 —— 这里统一**先算开间再摆窗**：
    窗口只放在「角柱内侧 ~ 门框外侧」的可用 bay 里，放不下就不放（宁缺勿撞）。
    """
    x0, x1 = cx - half, cx + half
    pillar = 4.2
    podium(d, x0 - 6, x1 + 6, ground, h=10, steps=(cx - 8, cx + 8) if kw.get("steps") else None)
    wall_top = ground - 34
    body(d, x0, x1, wall_top, ground, pillar=pillar)

    dw, dh = door if door != (0, 0) else (16, 22)
    opening(d, cx - dw / 2, ground - dh, cx + dw / 2, ground, radius=4.5)

    # 窗口：只放「角柱内侧 ~ 门框外侧」的可用 bay；太窄就不画（避开角柱重叠）
    inner_l, inner_r = x0 + pillar + 2.0, x1 - pillar - 2.0
    door_l, door_r = cx - dw / 2, cx + dw / 2
    if win:
        for b0, b1 in ((inner_l, door_l - 4.0), (door_r + 4.0, inner_r)):
            bay = b1 - b0
            if bay < 5.5:
                continue
            ww = min(9.0, bay)
            wx = (b0 + b1) / 2
            window_glow(d, wx - ww / 2, wall_top + 11, wx + ww / 2, wall_top + 23, width=1.1)

    if sign:
        sign_board(d, cx, wall_top + 4.5, w=min(26, half * 1.1))
    if hanging:
        # 幌子挂到**檐下外缘**（原来 x0+3.5 正好压在角柱/窗上）
        hanging_sign(d, x0 - 3.0, wall_top + 4)
    if awning:
        sunblind(d, x0 + half * 0.45, x1 - half * 0.45, wall_top + 5)
    if lanterns:
        if hanging:                     # 幌子占了左檐，灯笼只在右檐一盏
            lantern(d, x1 + 2, wall_top + 6, body_top=wall_top + 12)
        else:
            for sgn in (-1, 1):
                lantern(d, cx + sgn * (half + 2), wall_top + 6, body_top=wall_top + 12)
    roof_style(d, roof, cx, half + 8, wall_top + 3, h=20)


def arch_stall(d, cx=64, ground=102, canopy=True, flag=True, **kw):
    """摊子（算命摊 / 卜卦摊）：**无墙**，大伞 + 桌案 + 人影 + 招幡。

    算命是地摊不是房子（用户指出）。剪影靠“大伞”立住，40px 下也能认出。
    """
    # 桌案
    rect(d, cx - 18, ground - 24, cx + 12, ground - 13, fill=STONE, width=1.6)
    for lx in (cx - 15, cx + 8):
        rect(d, lx, ground - 13, lx + 2.6, ground, fill=STONE_DK, width=1.0)
    rect(d, cx - 14, ground - 31, cx - 8, ground - 24, fill=VERM, width=1.0)   # 签筒
    lamp(d, cx + 3, ground - 28, r=2.6)                                        # 案上灯火
    figure(d, cx - 5, ground - 13, 15)                                         # 摊主
    if canopy:                                                                 # 大伞
        px = cx + 10
        seg(d, [(px, ground), (px, ground - 56)], INK, 2.0)
        poly(d, [(cx - 30, ground - 52), (cx + 30, ground - 52),
                 (cx + 22, ground - 62), (cx - 22, ground - 62)], fill=TILE, width=1.6)
        seg(d, [(cx - 22, ground - 62), (cx + 22, ground - 62)], TILE_DK, 2.2)
        seg(d, [(cx - 30, ground - 52), (cx + 30, ground - 52)], TILE_LT, 1.4)
    if flag:                                                                   # 招幡
        fx = cx + 30
        seg(d, [(fx, ground), (fx, ground - 46)], INK, 1.6)
        poly(d, [(fx, ground - 46), (fx + 13, ground - 41), (fx, ground - 34)],
             fill=VERM, width=1.1)


def arch_tower(d, cx=64, half=20, ground=102, floors=2, lanterns=2, sign=True, **kw):
    """楼阁（二层重檐）：酒楼 / 客栈 / 藏书楼 / 望火楼。"""
    x0, x1 = cx - half, cx + half
    podium(d, x0 - 6, x1 + 6, ground, h=12, steps=(cx - 8, cx + 8))
    # 一层
    top1 = ground - 30
    body(d, x0, x1, top1, ground, stain=False, pillar=4.4)
    opening(d, cx - 9, ground - 20, cx + 9, ground, radius=4.5)
    # 腰檐
    eave(d, cx, half + 12, top1 - 1, 4.6, 5.6)
    # 二层
    top2 = top1 - 30
    body(d, x0 + 3, x1 - 3, top2, top1 - 4, stain=False, pillar=3.6)
    for sgn in (-1, 1):
        window_glow(d, cx + sgn * 9.5 - 5.5, top2 + 8, cx + sgn * 9.5 + 5.5, top2 + 21,
                    rose=3.2 if kw.get("rose") else None, width=1.2)
    if sign:
        sign_board(d, cx, top2 + 2.0, w=20)
    # 主檐
    roof_style(d, kw.get("roof", "xieshan"), cx, half + 14, top2 - 1, h=22)
    for i in range(lanterns):
        lantern(d, cx + (i * 2 - (lanterns - 1)) * (half + 6), top1 - 8, body_top=top1 - 3)


def arch_hall(d, cx=64, half=23, ground=102, roof="hip", drum=False, sign=True, **kw):
    """厅堂 / 官署 / 学宫：高台基 + 大殿 + 台阶（衙署加鸣冤鼓）。"""
    x0, x1 = cx - half, cx + half
    podium(d, x0 - 8, x1 + 8, ground, h=14, steps=(cx - 9, cx + 9))
    wall_top = ground - 36
    body(d, x0, x1, wall_top, ground, pillar=5.0)
    opening(d, cx - 10, ground - 26, cx + 10, ground, radius=5.0)
    for sgn in (-1, 1):
        window_glow(d, cx + sgn * 17 - 5, wall_top + 10, cx + sgn * 17 + 5, wall_top + 23,
                    mullions=1, width=1.1)
    if sign:
        sign_board(d, cx, wall_top + 4.0, w=26)
    if drum:
        rect(d, cx - 26, ground - 15, cx - 15, ground - 6, fill=VERM, width=1.1, radius=3.4)
    roof_style(d, roof, cx, half + 13, wall_top + 3, h=25)


def arch_temple(d, cx=64, half=21, ground=102, pagoda=False, **kw):
    """寺 / 观：殿宇 + 双幡杆 + 香炉。"""
    x0, x1 = cx - half, cx + half
    podium(d, x0 - 9, x1 + 9, ground, h=13, steps=(cx - 9, cx + 9))
    wall_top = ground - 34
    body(d, x0, x1, wall_top, ground, pillar=4.6)
    opening(d, cx - 11, ground - 25, cx + 11, ground, radius=5.5)
    for sgn in (-1, 1):
        window_glow(d, cx + sgn * 15 - 4.4, wall_top + 11, cx + sgn * 15 + 4.4, wall_top + 22,
                    width=1.1)
    for sgn in (-1, 1):                                   # 幡杆
        px = cx + sgn * (half + 17)
        seg(d, [(px, ground), (px, wall_top - 12)], INK, 1.6)
        poly(d, [(px, wall_top - 12), (px + sgn * 9, wall_top - 8), (px, wall_top - 4)],
             fill=VERM, width=1.1)
    rect(d, cx - 6, ground - 9, cx + 6, ground - 3, fill=STONE_DK, width=1.0)   # 香炉
    roof_style(d, "xieshan", cx, half + 12, wall_top + 3, h=24)


def arch_stage(d, cx=64, half=25, ground=102, canopy=True, **kw):
    """露台 / 戏台 / 相扑棚：台上演出（人影），可带乐棚顶。"""
    x0, x1 = cx - half, cx + half
    podium(d, x0, x1, ground, h=13)
    top = ground - 13
    if canopy:
        for px in (x0 + 5, x1 - 5):
            rect(d, px - 2.6, top - 26, px + 2.6, top, fill=VERM, width=1.6)
        roof_style(d, "gable", cx, half + 4, top - 25, h=15)
    if kw.get("ring"):                                     # 相扑棚：围栏
        fence(d, x0 + 2, x1 - 2, top + 3, h=9, posts=6)
    # 台上：一人 + 一鼓（或对打）
    if kw.get("figure", 1) == 2:
        figure(d, cx - 9, top - 1, 17, pose="dance")
        figure(d, cx + 9, top - 1, 17, pose="dance")
    else:
        figure(d, cx - 2, top - 1, 18, pose="dance")
        drum(d, cx + 13, top - 1, w=13, h=10)


def arch_bridge(d, cx=64, half=34, ground=98, arch=True, **kw):
    """桥：桥面 + 拱圈 + 桥墩 + 栏 + 水纹。"""
    deck = ground - 14
    x0, x1 = cx - half, cx + half
    seg(d, [(x0, deck), (x1, deck)], TILE, 8.0)                  # 桥面（粗带）
    seg(d, [(x0, deck - 4.4), (x1, deck - 4.4)], TILE_LT, 1.6)   # 面缘
    seg(d, [(x0, deck + 4.4), (x1, deck + 4.4)], INK, 1.2)
    if arch:
        for sgn in (-1, 1):                                      # 桥墩
            rect(d, cx + sgn * 17 - 3.4, deck + 3, cx + sgn * 17 + 3.4, ground + 13,
                 fill=STONE_DK, width=1.1)
        d.arc([(cx - 19) * S, (deck - 2) * S, (cx + 19) * S, (deck + 19) * S],
              start=0, end=180, fill=INK, width=int(3.0 * S))    # 拱圈
    for sgn in (-1, 1):                                      # 桥头灯柱
        px = cx + sgn * (half - 3)
        seg(d, [(px, deck), (px, deck - 15)], INK, 1.5)
        lantern(d, px, deck - 15, body_top=deck - 12, w=6.0, h=7.0)
    fence(d, x0 + 4, x1 - 4, deck - 12, h=8, posts=6)
    waves(d, x0 - 2, cx - 22, ground + 8, rows=2)
    waves(d, cx + 22, x1 + 2, ground + 8, rows=2)


def arch_boat(d, cx=64, y=88, w=46, sail=False, lit=True, **kw):
    """舟：船行 / 画舫 / 渡船。"""
    boat_hull(d, cx, y, w=w, h=10)
    if sail:
        seg(d, [(cx + 4, y), (cx + 4, y - 40)], INK, 1.8)
        poly(d, [(cx + 4, y - 38), (cx + 26, y - 12), (cx + 4, y - 8)], fill=STONE, width=1.2)
    if lit:
        for i in (-1, 1):
            seg(d, [(cx + i * 12, y), (cx + i * 12, y - 16)], INK, 1.2)
        for i in (-1, 1):
            lantern(d, cx + i * 12, y - 16, body_top=y - 13, w=7.5, h=9)
    waves(d, cx - w / 2 - 8, cx + w / 2 + 8, y + 15, rows=3)


def arch_nature(d, cx=64, ground=102, kind="water", **kw):
    """山水：湖 / 洲 / 山 / 林 / 园 / 村 / 碑 / 废墟 / 河。

    注意：这些都是「非建筑」，**最容易画成一条横带**（宽 96 高 45 → 40px 下只剩 32×10 的细缝，
    看起来就像没画）。所以一律要求**竖向撑满**：水面画成浑圆一片、园林配亭、坟配高碑高树。
    """
    if kind == "water":                                    # 湖：一片浑圆水面（不要一条带）
        poly(d, [(30, 40), (98, 40), (110, 66), (100, 100), (28, 100), (18, 66)],
             fill=TILE, width=2.0)
        for i, yy in enumerate((56, 64, 72, 80, 88)):       # 亮色波纹：与水面色拉开
            seg(d, [(30 + (i % 2) * 6, yy), (54 + (i % 2) * 6, yy - 3)], TILE_LT, 2.0)
            seg(d, [(68 + (i % 2) * 6, yy), (96 + (i % 2) * 6, yy - 3)], TILE_LT, 2.0)
        for x in (36, 44, 52):                             # 芦苇：硬结构
            seg(d, [(x, 50), (x + 2, 32)], INK, 1.7)
        tree(d, 88, 44, h=20)
    elif kind == "mountain":
        mound(d, cx, ground, w=84, h=52)
        mound(d, cx - 28, ground, w=44, h=32)
        mound(d, cx + 26, ground, w=48, h=38)
        seg(d, [(cx - 4, ground - 46), (cx + 5, ground - 28)], INK, 1.2)
    elif kind == "forest":
        for i, (dx, h) in enumerate(((-30, 30), (-14, 40), (2, 34), (18, 44), (32, 28))):
            tree(d, cx + dx, ground, h=h)
    elif kind == "islet":                                  # 洲：水中一块陆地 + 高树
        waves(d, 16, 112, ground + 12, rows=2, gap=7)
        poly(d, [(cx - 34, ground + 8), (cx - 20, ground - 4), (cx + 20, ground - 4),
                 (cx + 34, ground + 8)], fill=TILE_DK, width=1.3)
        tree(d, cx, ground - 2, h=38)
    elif kind == "village":
        for dx, hh in ((-24, 34), (0, 42), (24, 30)):
            hx = cx + dx
            top = ground - hh
            body(d, hx - 12, hx + 12, top, ground, pillar=3.0, stain=False)
            opening(d, hx - 4, ground - 12, hx + 4, ground, radius=2.8)
            roof_style(d, "gable", hx, 14, top + 3, h=13)
    elif kind == "monument":                               # 碑：高大的石碑
        podium(d, cx - 20, cx + 20, ground, h=12)
        rect(d, cx - 9, ground - 62, cx + 9, ground - 12, fill=STONE, width=1.5, radius=3.0)
        for yy in (ground - 50, ground - 40, ground - 30):
            seg(d, [(cx - 5, yy), (cx + 5, yy)], INK, 1.2)
        tree(d, cx + 34, ground, h=26)
    elif kind == "ruin":                                   # 废墟：断墙高低错落
        for x, w, hh in ((cx - 34, 26, 30), (cx - 2, 22, 46), (cx + 26, 16, 20)):
            rect(d, x, ground - hh, x + w, ground, fill=STONE, width=1.3)
            seg(d, [(x, ground - hh), (x + w * 0.5, ground - hh - 7)], INK, 1.4)
        tree(d, cx + 22, ground, h=30)
    elif kind == "river":                                  # 河：斜贯画面（横带会看不见）
        poly(d, [(20, 44), (44, 40), (108, 92), (108, 104), (84, 108), (20, 60)],
             fill=TILE, width=1.4)
        waves(d, 28, 56, 56, rows=1)
        waves(d, 60, 96, 88, rows=1)
    else:                                                  # garden 园林：园墙 + 月洞门 + 亭（有柱）+ 树
        # 园墙（横贯后半）
        seg(d, [(18, 76), (18, ground), (110, ground), (110, 76)], STONE_DK, 2.6)
        # 月洞门（开在墙上，夜亮）
        opening(d, 26, ground - 24, 46, ground - 4, radius=9.0)
        # 亭：台基 + 四柱 + 攒尖顶 + 亭内人影（原来只有一顶浮空的屋顶，没柱子）
        px = 84
        podium(d, px - 20, px + 20, ground, h=8)
        top = ground - 8
        for dx in (-13, 13):
            rect(d, px + dx - 2.4, top - 30, px + dx + 2.4, top, fill=VERM, width=1.2)
        roof_style(d, "pyramid", px, 19, top - 29, h=15)
        figure(d, px, top, 15)
        tree(d, 58, ground, h=30)


def arch_tomb(d, cx=64, ground=100, **kw):
    """坟地 / 义冢：**单坟包 + 高碑 + 一株松**。

    不画成「一排小土堆 + 两株远树」——那样宽 91 高 38，40px 下只有 32×14 的扁条，
    看起来就像没画。低模下宁可少而大。
    """
    poly(d, [(cx - 26, ground), (cx - 17, ground - 22), (cx + 17, ground - 22), (cx + 26, ground)],
         fill=TILE_DK, width=1.4)
    rect(d, cx - 7, ground - 56, cx + 7, ground - 22, fill=STONE, width=1.3, radius=2.6)
    for yy in (ground - 46, ground - 37):
        seg(d, [(cx - 4, yy), (cx + 4, yy)], INK, 1.2)
    tree(d, cx + 36, ground, h=48)
    tree(d, cx - 36, ground, h=34)


def arch_granary(d, cx=64, ground=102, kind="round", **kw):
    """粮仓：圆囷 / 方仓。"""
    if kind == "round":
        podium(d, cx - 24, cx + 24, ground, h=10)
        y = ground - 10
        ellipse(d, cx - 17, y - 30, cx + 17, y, fill=STONE, width=1.4)
        for yy in (y - 22, y - 14, y - 6):
            seg(d, [(cx - 16, yy), (cx + 16, yy)], STONE_DK, 1.1)
        roof_style(d, "pyramid", cx, 20, y - 29, h=12)
    else:
        podium(d, cx - 26, cx + 26, ground, h=10)
        wall_top = ground - 40
        body(d, cx - 22, cx + 22, wall_top, ground - 10, pillar=4.0)
        opening(d, cx - 9, ground - 20, cx + 9, ground - 10, radius=4.0)
        roof_style(d, "gable", cx, 26, wall_top + 3, h=16)


def arch_gate(d, cx=64, ground=104, **kw):
    """城门：城墙段 + 门洞 + 城楼。"""
    wall_top = ground - 40
    rect(d, 14, wall_top, 114, ground, fill=STONE, width=1.5)
    band(d, 14, ground - 7, 114, ground)
    opening(d, cx - 15, ground - 27, cx + 15, ground, radius=8.0)
    for yy in (wall_top + 8, wall_top + 20):               # 城墙砖缝
        seg(d, [(16, yy), (112, yy)], STONE_DK, 1.0)
    roof_style(d, "xieshan", cx, 26, wall_top + 2, h=20)   # 城楼


def arch_yard(d, cx=64, ground=102, prop="mill", **kw):
    """场院 / 作坊：矮屋 + 院墙 + 院内道具（磨盘 / 染缸 / 炉）。"""
    x0, x1 = cx - 26, cx - 2
    podium(d, x0 - 6, x1 + 6, ground, h=9)
    wall_top = ground - 26
    body(d, x0, x1, wall_top, ground, pillar=4.0)
    opening(d, cx - 22, ground - 17, cx - 12, ground, radius=3.5)
    window_glow(d, cx - 9, wall_top + 7, cx - 3, wall_top + 16, width=1.0)
    roof_style(d, "gable", cx - 14, 30, wall_top + 3, h=15)
    # 院墙
    seg(d, [(cx + 2, ground), (cx + 2, ground - 13), (cx + 34, ground - 13), (cx + 34, ground)],
        STONE_DK, 2.6)
    px = cx + 18
    if prop == "mill":                                     # 磨盘
        ellipse(d, px - 10, ground - 13, px + 10, ground - 1, fill=TILE, width=1.2)
        seg(d, [(px, ground - 13), (px, ground - 1)], TILE_DK, 1.2)
    elif prop == "dye":                                    # 染缸
        for i, dx in enumerate((-8, 8)):
            ellipse(d, px + dx - 7, ground - 12, px + dx + 7, ground - 1, fill=TILE_DK, width=1.1)
    elif prop == "forge":                                  # 炉
        rect(d, px - 8, ground - 12, px + 8, ground, fill=STONE_DK, width=1.2, radius=2.0)
        lamp(d, px, ground - 8, r=3.4)
    else:                                                  # stable 马厩：栅栏
        fence(d, px - 12, px + 12, ground - 14, h=13, posts=4)


# ==========================================================================
# 键 → 原型 / 参数
# ==========================================================================
SPECS = {
    # ---- 风月 / 百戏（专属 render 优先，这两个走 render；其余用原型）----
    "huafang":  ("boat",      dict(y=92, w=50, lit=True)),
    "theater":  ("stage",     dict(half=27, canopy=True, figure=2)),
    "stage":    ("stage",     dict(half=22, canopy=True, figure=1)),
    "story":    ("shop",      dict(half=23, hanging=True, awning=True, lanterns=2)),
    "arena":    ("stage",     dict(half=27, canopy=False, figure=2, ring=True)),
    "go":       ("shop",      dict(half=21, sign=True, lanterns=2)),
    "martial":  ("shop",      dict(half=22, sign=True, lanterns=1, win=0)),

    # ---- 金融 / 商市 / 百工 ----
    "money":    ("shop",      dict(half=22, sign=True, lanterns=2)),
    "pawn":     ("shop",      dict(half=22, hanging=True, sign=True)),
    "gamble":   ("shop",      dict(half=24, sign=True, lanterns=2, hanging=True)),
    "market":   ("shop",      dict(half=28, awning=True, sign=True, win=0)),
    "grain":    ("shop",      dict(half=24, awning=True, sign=True)),
    "food":     ("shop",      dict(half=22, awning=True, lanterns=1, sign=True)),
    "textile":  ("shop",      dict(half=24, awning=True, sign=True)),
    "dye":      ("yard",      dict(prop="dye")),
    "smith":    ("yard",      dict(prop="forge")),
    "carpenter":("yard",      dict(prop="mill")),
    "mill":     ("yard",      dict(prop="mill")),
    "stable":   ("yard",      dict(prop="stable")),
    "wine":     ("shop",      dict(half=23, hanging=True, lanterns=2, sign=True)),
    "incense":  ("shop",      dict(half=21, sign=True, lanterns=1)),
    "tea":      ("shop",      dict(half=22, awning=True, lanterns=1, sign=True)),
    "coffin":   ("shop",      dict(half=22, sign=False, lanterns=0, win=0)),
    "med":      ("shop",      dict(half=22, hanging=True, sign=True, lanterns=1)),
    "library":  ("tower",     dict(half=19, floors=2, lanterns=0, rose=False)),
    "academy":  ("hall",      dict(half=24, roof="xieshan", sign=True)),
    "fortune":  ("stall",     dict()),

    # ---- 行旅 / 交通 ----
    "inn":      ("tower",     dict(half=20, lanterns=2)),
    "tavern":   ("tower",     dict(half=21, lanterns=2, rose=True)),
    "post":     ("yard",      dict(prop="stable")),
    "ferry":    ("boat",      dict(y=94, w=42)),
    "boat":     ("boat",      dict(y=94, w=42, sail=True)),
    "bridge":   ("bridge",    dict()),
    "gate":     ("gate",      dict()),
    "office":   ("hall",      dict(half=25, roof="hip", drum=True)),
    "granary":  ("granary",   dict(kind="round")),
    "fire":     ("tower",     dict(half=15, floors=2, lanterns=2, sign=False)),

    # ---- 医药 / 信仰 / 礼 ----
    "vet":      ("yard",      dict(prop="stable")),
    "temple":   ("temple",    dict()),
    "shrine":   ("temple",    dict(half=18)),
    "grave":    ("tomb",      dict()),

    # ---- 山水 / 游乐 ----
    "water":    ("nature",    dict(kind="water")),
    "islet":    ("nature",    dict(kind="islet")),
    "mountain": ("nature",    dict(kind="mountain")),
    "forest":   ("nature",    dict(kind="forest")),
    "garden":   ("nature",    dict(kind="garden")),
    "sight":    ("shop",      dict(half=20, sign=True, lanterns=1)),

    # ---- 旧键（已不在 KINDS 里但历史 geojson 可能引用，一并出图）----
    "drink":    ("shop",      dict(half=21, hanging=True, lanterns=2, sign=True)),
    "house":    ("shop",      dict(half=20, sign=False, win=2)),
    "shop":     ("shop",      dict(half=22, awning=True, sign=True)),
    "town":     ("nature",    dict(kind="village")),
    "village":  ("nature",    dict(kind="village")),
    "monument": ("nature",    dict(kind="monument")),
    "ruin":     ("nature",    dict(kind="ruin")),
    "river":    ("nature",    dict(kind="river")),
    "museum":   ("hall",      dict(half=24, roof="xieshan", sign=True)),
}

ARCHES = {
    "shop": arch_shop, "tower": arch_tower, "hall": arch_hall, "temple": arch_temple,
    "stage": arch_stage, "bridge": arch_bridge, "boat": arch_boat, "nature": arch_nature,
    "tomb": arch_tomb, "granary": arch_granary, "gate": arch_gate, "yard": arch_yard,
    "stall": arch_stall,
}


def render(key):
    """按 SPECS 渲染一个键（返回 128x128 RGBA，未 fit）。"""
    arch, _params = SPECS[key]
    params = dict(_params)                      # 不改到 SPECS 本体
    body, d = blank()
    cx = params.pop("cx", 64.0)
    shadow = ground_shadow(box=(cx - 42, 100, cx + 42, 112))
    ARCHES[arch](d, cx=cx, **params)
    return compose(shadow, body)
