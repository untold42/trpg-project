# -*- coding: utf-8 -*-
"""
gen_event_icons.py —— 基础设施活动的「事件图」批量生成。

规格：128×128 PNG、透明底、**纯黑**、手绘（笔画抖动）、**不加外框**（直接放进按钮的左菱形宣纸槽）。
输出：trpg-client/public/eventicons/<key>.png
用法：python gen_event_icons.py [key...] [--ascii]
"""
from __future__ import annotations
import os
import random
import sys

from PIL import Image, ImageDraw

S = 4
BASE = 128
INK = (0, 0, 0, 255)
LW = 5.0                      # 基础笔画宽度（比之前粗，40px 下才看得清）

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(os.path.join(HERE, "..", "..", "..", "trpg-client", "public", "eventicons"))


def _sc(p):
    return (p[0] * S, p[1] * S)


def stroke(d, pts, w=LW, rng=None, a=0.8):
    rng = rng or random
    j = [(x + rng.uniform(-a, a), y + rng.uniform(-a, a)) for x, y in pts]
    d.line([_sc(q) for q in j], fill=INK, width=max(1, int(round(w * S))), joint="curve")


def outline(d, pts, w=LW, rng=None, a=0.8):
    stroke(d, list(pts) + [pts[0]], w, rng, a)


def fill(d, pts, rng=None, a=0.5):
    rng = rng or random
    d.polygon([_sc(q) for q in [(x + rng.uniform(-a, a), y + rng.uniform(-a, a)) for x, y in pts]], fill=INK)


def disc(d, cx, cy, r):
    d.ellipse([_sc((cx - r, cy - r))[0], _sc((cx - r, cy - r))[1],
               _sc((cx + r, cy + r))[0], _sc((cx + r, cy + r))[1]], fill=INK)


def ring(d, cx, cy, r, w=None):
    w = w or LW
    d.ellipse([(cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S],
              outline=INK, width=max(1, int(round(w * S))))


def rect_fill(d, x0, y0, x1, y1):
    d.rectangle([x0 * S, y0 * S, x1 * S, y1 * S], fill=INK)


def rect_out(d, x0, y0, x1, y1, w=None):
    w = w or LW
    d.rectangle([x0 * S, y0 * S, x1 * S, y1 * S], outline=INK, width=max(1, int(round(w * S))))


def arc(d, cx, cy, r, a0, a1, w=None):
    w = w or LW
    d.arc([(cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S], a0, a1,
          fill=INK, width=max(1, int(round(w * S))))


# ------------------------------------------------------------
# 符号（无外框，尽量中置、饱满）
# ------------------------------------------------------------
def k_free(d, rng):                         # 一支笔
    stroke(d, [(40, 104), (98, 34)], 9, rng, 0.7)          # 笔杆
    fill(d, [(98, 34), (108, 22), (100, 44)], rng, 0.4)    # 笔锋
    stroke(d, [(30, 78), (58, 86), (84, 76)], 3.4, rng, 1.2)


def k_ask(d, rng):                          # 对话气泡 + 三点
    outline(d, [(26, 34), (102, 34), (102, 82), (58, 82), (44, 100), (50, 82), (26, 82)], 5, rng, 0.8)
    for x in (48, 64, 80):
        disc(d, x, 58, 5.2)


def k_cultivate(d, rng):                    # 打坐
    disc(d, 64, 40, 12)
    fill(d, [(64, 50), (92, 100), (36, 100)], rng, 0.4)
    stroke(d, [(30, 104), (98, 104)], 5, rng, 0.6)


def k_arena_wrestle(d, rng):                # 两个力士对推
    disc(d, 42, 42, 11); disc(d, 86, 42, 11)
    fill(d, [(42, 52), (58, 104), (30, 104)], rng, 0.4)
    fill(d, [(86, 52), (98, 104), (70, 104)], rng, 0.4)
    stroke(d, [(50, 64), (78, 64)], 6, rng, 0.6)


def k_martial_sword(d, rng):                # 剑
    fill(d, [(64, 12), (74, 34), (74, 92), (54, 92), (54, 34)], rng, 0.4)   # 剑身
    rect_fill(d, 40, 92, 88, 100)                                            # 护手
    rect_fill(d, 58, 100, 70, 116)                                           # 柄


def k_martial_fist(d, rng):                 # 拳
    outline(d, [(34, 46), (76, 40), (92, 58), (92, 86), (76, 102), (44, 104), (32, 84)], 5, rng, 0.7)
    for y in (58, 70, 82):
        stroke(d, [(38, y), (86, y)], 3.2, rng, 0.6)


def _goban(d, rng, x0=38, y0=40, x1=90, y1=92):
    for i in range(4):
        x = x0 + (x1 - x0) * i / 3
        y = y0 + (y1 - y0) * i / 3
        stroke(d, [(x, y0), (x, y1)], 2.6, rng, 0.4)
        stroke(d, [(x0, y), (x1, y)], 2.6, rng, 0.4)


def k_go_practice(d, rng):
    _goban(d, rng); disc(d, 51, 57, 7); disc(d, 69, 75, 7)


def k_go_challenge(d, rng):
    _goban(d, rng, 36, 44, 82, 90)
    stroke(d, [(100, 30), (100, 70)], 4.4, rng, 0.5)
    fill(d, [(100, 30), (120, 38), (100, 46)], rng, 0.4)


def k_academy_lecture(d, rng):              # 摊开的书
    fill(d, [(22, 44), (62, 38), (62, 98), (22, 104)], rng, 0.5)
    fill(d, [(106, 44), (66, 38), (66, 98), (106, 104)], rng, 0.5)
    stroke(d, [(64, 36), (64, 100)], 4, rng, 0.5)


def k_academy_debate(d, rng):               # 两个气泡
    outline(d, [(20, 36), (62, 36), (62, 68), (44, 68), (34, 82), (38, 68), (20, 68)], 4.4, rng, 0.7)
    outline(d, [(64, 56), (108, 56), (108, 90), (92, 90), (98, 104), (80, 90), (64, 90)], 4.4, rng, 0.7)


def k_library_read(d, rng):                 # 叠书
    for y in (60, 76, 92):
        rect_fill(d, 28, y, 100, y + 11)
    stroke(d, [(44, 60), (44, 71)], 2.4, rng, 0.3)
    stroke(d, [(40, 76), (40, 87)], 2.4, rng, 0.3)
    stroke(d, [(50, 92), (50, 103)], 2.4, rng, 0.3)


def k_garden_stroll(d, rng):                # 树
    rect_fill(d, 58, 60, 70, 106)
    disc(d, 64, 48, 30)
    disc(d, 44, 62, 18); disc(d, 84, 62, 18)


def k_temple_fire(d, rng):
    _roof(d, rng)
    fill(d, [(64, 40), (46, 74), (64, 68), (52, 100), (84, 76), (70, 108), (92, 92)], rng, 0.7)


def k_temple_water(d, rng):
    _roof(d, rng)
    for y in (72, 86, 100):
        stroke(d, [(30, y), (44, y - 7), (58, y), (72, y - 7), (86, y), (98, y - 5)], 4, rng, 0.6)


def k_temple_wood(d, rng):
    _roof(d, rng)
    stroke(d, [(64, 106), (64, 70)], 4.4, rng, 0.5)
    fill(d, [(44, 74), (64, 52), (84, 74), (64, 96)], rng, 0.5)


def k_temple_metal(d, rng):
    _roof(d, rng)
    fill(d, [(38, 100), (90, 100), (78, 74), (50, 74)], rng, 0.5)
    stroke(d, [(50, 74), (78, 74)], 3, rng, 0.4)


def k_temple_earth(d, rng):
    _roof(d, rng)
    fill(d, [(26, 104), (54, 60), (72, 84), (86, 62), (104, 104)], rng, 0.7)


def _roof(d, rng, y=36, half=40):
    stroke(d, [(64 - half, y + 14), (30, y - 2), (64, y - 10), (98, y - 2), (64 + half, y + 14)], 5, rng, 0.7)
    stroke(d, [(42, y + 14), (86, y + 14)], 4, rng, 0.5)


def k_inn_stay(d, rng):                     # 床
    rect_fill(d, 24, 78, 104, 86)           # 床板
    rect_fill(d, 24, 86, 32, 108)           # 腿
    rect_fill(d, 96, 86, 104, 108)
    fill(d, [(36, 56), (60, 54), (60, 74), (36, 76)], rng, 0.4)   # 枕
    rect_fill(d, 64, 66, 96, 78)            # 被


def k_tavern_drink(d, rng):                 # 酒坛
    fill(d, [(40, 54), (78, 50), (88, 96), (30, 100)], rng, 0.6)
    rect_fill(d, 44, 42, 74, 54)
    stroke(d, [(92, 66), (112, 66)], 4, rng, 0.5)
    stroke(d, [(96, 60), (108, 60)], 3.4, rng, 0.4)


def k_tea_drink(d, rng):                    # 茶盏
    fill(d, [(34, 66), (94, 66), (82, 104), (46, 104)], rng, 0.5)
    rect_fill(d, 30, 60, 98, 68)
    for x in (52, 66, 80):
        stroke(d, [(x, 54), (x - 5, 40), (x, 28)], 3, rng, 0.8)


def k_qinglou_song(d, rng):                 # 音符（清楚）
    disc(d, 50, 92, 18)
    rect_fill(d, 64, 30, 73, 92)
    fill(d, [(73, 30), (106, 42), (106, 58), (73, 46)], rng, 0.4)


def k_gamble(d, rng):                       # 两枚骰子
    rect_out(d, 28, 54, 66, 92, 5)
    for (x, y) in ((37, 63), (57, 83), (47, 73)):
        disc(d, x, y, 4.4)
    rect_out(d, 66, 34, 104, 72, 5)
    disc(d, 75, 43, 4.4); disc(d, 95, 63, 4.4)


def k_med_visit(d, rng):                    # 药葫芦
    disc(d, 64, 44, 16)
    disc(d, 64, 84, 26)
    rect_fill(d, 58, 20, 70, 30)


def k_med_buy(d, rng):                      # 药包
    fill(d, [(30, 50), (98, 50), (98, 104), (30, 104)], rng, 0.5)
    stroke(d, [(64, 50), (64, 104)], 3.4, rng, 0.5)
    stroke(d, [(30, 77), (98, 77)], 3.4, rng, 0.5)


def k_smith(d, rng):                        # 铁砧 + 锤
    fill(d, [(26, 92), (102, 92), (88, 72), (40, 72)], rng, 0.5)
    rect_fill(d, 30, 92, 98, 100)
    stroke(d, [(80, 40), (46, 62)], 6, rng, 0.5)
    fill(d, [(74, 42), (92, 30), (102, 44), (84, 56)], rng, 0.5)


def k_ferry(d, rng):                        # 帆船
    fill(d, [(22, 84), (106, 84), (94, 102), (34, 102)], rng, 0.5)   # 船身
    stroke(d, [(64, 84), (64, 22)], 5, rng, 0.5)
    fill(d, [(70, 26), (70, 78), (104, 78)], rng, 0.5)              # 帆


def _gate(d, rng):
    stroke(d, [(34, 100), (34, 52), (50, 36), (78, 36), (94, 52), (94, 100)], 6, rng, 0.6)
    rect_fill(d, 26, 46, 102, 56)
    rect_out(d, 58, 68, 72, 100, 4)


def k_gate_out(d, rng):
    _gate(d, rng)
    stroke(d, [(56, 78), (104, 78)], 4, rng, 0.4)
    fill(d, [(112, 78), (96, 68), (96, 88)], rng, 0.3)


def k_gate_in(d, rng):
    _gate(d, rng)
    stroke(d, [(28, 78), (72, 78)], 4, rng, 0.4)
    fill(d, [(20, 78), (36, 68), (36, 88)], rng, 0.3)


def k_market(d, rng):                       # 摊位
    rect_fill(d, 24, 46, 104, 54)
    for i in range(4):
        x = 26 + i * 20
        stroke(d, [(x, 46), (x + 10, 30)], 4, rng, 0.5)
    rect_fill(d, 28, 54, 36, 96); rect_fill(d, 92, 54, 100, 96)
    ring(d, 52, 78, 9, 4); ring(d, 76, 78, 9, 4)


def _shrine(d, rng, k=1.0):
    stroke(d, [(64 - 30 * k, 46), (64, 26), (64 + 30 * k, 46)], 5, rng, 0.6)
    rect_fill(d, 64 - 24 * k, 46, 64 - 18 * k, 104)
    rect_fill(d, 64 + 18 * k, 46, 64 + 24 * k, 104)
    rect_fill(d, 64 - 24 * k, 70, 64 + 24 * k, 78)


def k_shrine_city(d, rng): _shrine(d, rng, 1.05)
def k_shrine_land(d, rng): _shrine(d, rng, 0.82)


def k_temple_buddhist(d, rng):              # 塔
    for i, y in enumerate((42, 64, 86)):
        w = 40 - i * 8
        stroke(d, [(64 - w, y), (64, y - 14), (64 + w, y)], 4.4, rng, 0.5)
        rect_fill(d, 64 - w * 0.5, y, 64 + w * 0.5, y + 8)
    rect_fill(d, 58, 20, 70, 28)


def k_temple_daoist(d, rng):                # 太极
    ring(d, 64, 64, 34, 5)
    arc(d, 64, 47, 17, 0, 180, 4.4)
    arc(d, 64, 81, 17, 180, 360, 4.4)
    disc(d, 64, 47, 5); disc(d, 64, 81, 5)


def k_shrine_ancestor(d, rng):              # 牌位 + 香
    fill(d, [(44, 40), (84, 40), (84, 104), (44, 104)], rng, 0.4)
    stroke(d, [(38, 50), (90, 50)], 3.4, rng, 0.4)
    stroke(d, [(64, 40), (64, 24)], 3, rng, 0.3)
    stroke(d, [(64, 24), (58, 14), (64, 6)], 2.6, rng, 0.6)


DRAW = {
    "free": k_free, "ask": k_ask, "cultivate": k_cultivate,
    "arena_wrestle": k_arena_wrestle,
    "martial_sword": k_martial_sword, "martial_fist": k_martial_fist,
    "go_practice": k_go_practice, "go_challenge": k_go_challenge,
    "academy_lecture": k_academy_lecture, "academy_debate": k_academy_debate,
    "library_read": k_library_read, "garden_stroll": k_garden_stroll,
    "temple_fire": k_temple_fire, "temple_water": k_temple_water,
    "temple_wood": k_temple_wood, "temple_metal": k_temple_metal,
    "temple_earth": k_temple_earth,
    "inn_stay": k_inn_stay, "tavern_drink": k_tavern_drink, "tea_drink": k_tea_drink,
    "qinglou_song": k_qinglou_song, "gamble": k_gamble,
    "med_visit": k_med_visit, "med_buy": k_med_buy, "smith": k_smith,
    "ferry": k_ferry, "gate_out": k_gate_out, "gate_in": k_gate_in,
    "market": k_market,
    "shrine_city": k_shrine_city, "shrine_land": k_shrine_land,
    "temple_buddhist": k_temple_buddhist, "temple_daoist": k_temple_daoist,
    "shrine_ancestor": k_shrine_ancestor,
}


def render(key: str) -> Image.Image:
    rng = random.Random(sum(ord(c) for c in key))
    img = Image.new("RGBA", (BASE * S, BASE * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    DRAW.get(key, k_free)(d, rng)
    return img.resize((BASE, BASE), Image.LANCZOS)


def ascii_view(img: Image.Image, w=40, h=20):
    a = img.split()[3].resize((w, h))
    chars = " .:-=+*#%@"
    return "\n".join("".join(chars[min(9, a.getpixel((x, y)) * 10 // 256)] for x in range(w))
                     for y in range(h))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    keys = args or sorted(DRAW)
    os.makedirs(OUT, exist_ok=True)
    for k in keys:
        render(k).save(os.path.join(OUT, f"{k}.png"))
    print("写出", len(keys), "张 →", OUT)
    if "--ascii" in sys.argv:
        for k in keys:
            print("=" * 42, k); print(ascii_view(render(k)))


if __name__ == "__main__":
    main()
