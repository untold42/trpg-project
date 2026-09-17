# -*- coding: utf-8 -*-
"""
南宋建筑地图图标 · 各建筑
=========================

每个建筑 = 一个 `render_xxx()`（返回 128x128 RGBA），在文件末尾的 `BUILDINGS` 里登记。
画新建筑只需要：① 抄一个模板 ② 用 kit 的构件拼装 ③ 登记 ④ 跑校验。

    python gen_map_icons.py             # 生成默认建筑到 mapicons/
    python gen_map_icons.py ward --preview --small 40    # ASCII 校验
    python gen_map_icons.py ward --stats --sheet         # 指标 + 给人看的预览图
"""

from kit import *   # noqa: F401,F403  （色板 / 绘图原语 / 屋面构件 / 校验工具）

# 窗棂用脏砖红而非墨：细线在 40px 下会糊成一团黑，砖红糊了仍像窗棂
MULLION = VERM


# ==========================================================================
# 青楼 —— 重檐歇山顶楼阁 · 风月场
#   识别要点：二层大窗 + 胭脂纱帘半掩 + 倚窗女子剪影 + 双小红灯
#   亮度层级（实测）：窗火 203 > 纱帘 114 > 人影 72
# ==========================================================================
def render_qinglou():
    body, d = blank()
    shadow = ground_shadow()
    cx = 64.0

    # ---- 台基（石砖）----
    poly(d, [(32, 102), (96, 102), (100, 110), (28, 110)], fill=STONE_DK, width=1.4)

    # ---- 一层：石砖墙 + 双窗 + 朱匾 + 券门 ----
    rect(d, 40, 72, 88, 102, fill=STONE, width=1.4)
    band(d, 40, 95.5, 88, 102)                       # 墙脚水渍（风化）
    for x0, x1 in ((46, 56), (72, 82)):
        window_glow(d, x0, 82, x1, 93, width=1.1)
    rect(d, 56, 78, 72, 84, fill=VERM, width=1.1)    # 朱匾（低模：一块红板）
    rect(d, 56, 86, 72, 102, fill=GLOW, width=1.3, radius=5.0)   # 券门（内透灯火）
    for x0, x1 in ((40, 45), (83, 88)):              # 朱红角柱
        rect(d, x0, 72, x1, 102, fill=VERM, width=1.1)

    # ---- 二层：石砖墙 + 大窗 + 胭脂纱帘 + 倚窗女子 ----
    rect(d, 46, 48, 82, 72, fill=STONE, width=1.4)
    band(d, 46, 68.5, 82, 72)                        # 墙脚水渍
    window_glow(d, 50, 54, 78, 68, rose=4.5, width=1.3)          # 大窗 + 左右纱帘
    ellipse(d, 65, 56, 69, 60, fill=FIGURE, width=0.9)                          # 头
    poly(d, [(64, 59.5), (70, 59.5), (70.5, 68), (63.5, 68)], fill=FIGURE, width=0.9)  # 肩身
    seg(d, [(64.5, 61), (60, 62.6)], FIGURE, 1.2)                               # 手臂搭在窗沿

    # ---- 腰檐 + 主檐（歇山顶）----
    eave(d, cx, 34, 72, 5.0, 6.0)
    roof(d, cx, 40, 9, 30, 52, 40)

    # ---- 双小红灯（挂在下层檐角外）----
    lantern(d, cx - 32, 66)
    lantern(d, cx + 32, 66)

    return compose(shadow, body)


# ==========================================================================
# 教坊 —— 官/私乐舞教习之所（习曲舞、应宴演）
#   识别要点：殿宇 + 高台基，**台前乐舞场面**（双舞者扬袖 + 正中大鼓）
#   与青楼的区别：青楼是二层楼阁 + 沙帘 + 侬窗女子；教坊是单檐大殿 + 台上舞者
# ==========================================================================
def render_jiaofang():
    body, d = blank()
    shadow = ground_shadow(box=(24, 104, 104, 116))
    cx = 64.0

    # ---- 台基（官署台基高）+ 踏道 ----
    poly(d, [(26, 86), (102, 86), (106, 100), (22, 100)], fill=STONE, width=1.4)
    band(d, 22, 95, 106, 100, STONE_DK)                      # 台基下缘压暗（出体积）
    poly(d, [(56, 100), (72, 100), (74, 108), (54, 108)], fill=STONE_DK, width=1.2)

    # ---- 殿身：石砖墙 + 角柱 + **明间敞开** + 朱匾 ----
    rect(d, 42, 46, 86, 86, fill=STONE, width=1.4)
    band(d, 42, 80.5, 86, 86)                                # 墙脚水渍
    for x0, x1 in ((42, 46), (82, 86)):                      # 朱红角柱
        rect(d, x0, 46, x1, 86, fill=VERM, width=1.1)
    rect(d, 46, 64, 62, 86, fill=GLOW_DK, width=1.3)         # 左隔扇门（敞开）
    rect(d, 66, 64, 80, 86, fill=GLOW_DK, width=1.3)         # 右隔扇门
    rect(d, 62, 64, 66, 86, fill=VERM, width=1.1)            # 中门柱（破开大亮块）
    rect(d, 54, 52, 74, 58, fill=VERM, width=1.1)            # 朱匾

    # ---- 单檐歇山顶 ----
    roof(d, cx, 36, 9, 22, 50, 38, chiwei=True)

    # ---- 台前乐舞：左舞者扬袖 + 右大鼓（都压在亮底上）----
    figure(d, 55, 98, 18, pose="dance")
    drum(d, 75, 98, w=15, h=12)

    return compose(shadow, body)


# ==========================================================================
# 坊（ward）—— 牌坊（四柱三间），街区入口标志
#   识别要点：主楼高居中 + 两次间矮且外挑，中间露出柱身（否则三间糊成一坨）
# ==========================================================================
def render_ward():
    body, d = blank()
    shadow = ground_shadow(box=(24, 112, 104, 120))
    cx, ground = 64.0, 110

    for x in (30, 52, 76, 98):                       # 内柱高、外柱矮
        top = 40 if x in (52, 76) else 62
        rect(d, x - 3, top, x + 3, ground, fill=VERM, width=1.2)

    roof(d, cx, 26, 6, 24, 42, 34, ribs=(0.45,), chiwei=False)                # 主楼
    roof(d, 40, 16, 4, 48, 64, 56, ribs=(), ridge_bar=False, chiwei=False)    # 左次间
    roof(d, 88, 16, 4, 48, 64, 56, ribs=(), ridge_bar=False, chiwei=False)    # 右次间

    rect(d, 54, 52, 74, 60, fill=VERM, width=1.1)                             # 正间匾额
    for x in (52, 76):                                                        # 夜里挂灯
        lantern(d, x, 62, body_top=64, w=6.5, h=7.5)
    for x in (30, 52, 76, 98):                                                # 夹杆石
        rect(d, x - 5, ground - 6, x + 5, ground, fill=STONE_DK, width=1.0)
    return compose(shadow, body)


# ==========================================================================
# 宫 —— 重檐廑殿顶大殿 · 高台基 + 宽踏道
#   识别要点（与青楼/教坊的区别）：
#     · **重檐**（上下两层屋面）—— 教坊只有单檐
#     · **高台基 + 宽踏道**（官式最高规格）
#     · 无二层大窗、无徒子剪影、无舞者
#   用于「宫」组（锦香宫等门派驻地 / 宫观）
# ==========================================================================
def render_palace():
    body, d = blank()
    shadow = ground_shadow(box=(20, 104, 108, 116))
    cx = 64.0

    # ---- 台基 + 宽踏道（带踏步线）----
    poly(d, [(20, 86), (108, 86), (112, 100), (16, 100)], fill=STONE, width=1.4)
    band(d, 16, 95, 112, 100, STONE_DK)
    poly(d, [(52, 100), (76, 100), (78, 110), (50, 110)], fill=STONE_DK, width=1.2)
    for i, y in enumerate((103, 106)):
        shrink = (i + 1) * 1.2
        seg(d, [(52 + shrink, y), (76 - shrink, y)], INK, 0.9)

    # ---- 殿身：石砖墙 + 朱红角柱 + 明间灯火 + 朱匾 ----
    rect(d, 36, 58, 92, 86, fill=STONE, width=1.4)
    band(d, 36, 81, 92, 86)                                  # 墙脚水渍
    for x0, x1 in ((36, 41), (87, 92)):                      # 朱红角柱
        rect(d, x0, 58, x1, 86, fill=VERM, width=1.1)
    rect(d, 50, 66, 54, 86, fill=VERM, width=1.0)            # 次间柱
    rect(d, 74, 66, 78, 86, fill=VERM, width=1.0)
    window_glow(d, 56, 66, 72, 86, width=1.3)                # 明间（内透灯火）
    rect(d, 54, 60, 74, 66, fill=VERM, width=1.1)            # 朱匾

    # ---- 双宫灯（立杆，非悬挂）----
    for x in (25, 103):
        seg(d, [(x, 99), (x, 80)], INK, 1.4)
        ellipse(d, x - 5.5, 80, x + 5.5, 92, fill=LANTERN, width=1.1)

    # ---- 上层墙（下檐之上的上檐身）----
    rect(d, 48, 40, 80, 58, fill=STONE, width=1.3)
    band(d, 48, 52, 80, 58)
    for x0, x1 in ((48, 52), (76, 80)):
        rect(d, x0, 40, x1, 58, fill=VERM, width=1.0)

    # ---- 下檐（腰檐，比上檐宽）----
    eave(d, cx, 46, 58, 5.0, 6.5)

    # ---- 上檐（重檐廑殿顶）----
    roof(d, cx, 34, 11, 14, 40, 29, chiwei=True)

    return compose(shadow, body)


# ==========================================================================
# 登记表：key 必须与
#   trpg-map/draw_tiles/song_kinds.py 里的 icon= 值
#   trpg-client/public/mapicons/manifest.txt 的键名
# 一致（前端按 /mapicons/<key>.png 取图，缺图会退化成一个棕色圆点）
# ==========================================================================
BUILDINGS = {
    "qinglou": render_qinglou,
    "jiaofang": render_jiaofang,
    "ward": render_ward,
    "palace": render_palace,
}
