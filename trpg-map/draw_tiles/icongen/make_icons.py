# -*- coding: utf-8 -*-
"""
自动化管线：每个建筑图标键 → `day.png` + `night.png`
=====================================================

数据来源（三处合一）
  · `song_kinds.py` 的 KINDS      → 建筑介绍（kind / group / zone / note）
  · `public/mapicons/manifest.txt` → 实际布点数量（哪些键真被用到）
  · `_original/<key>.png`          → 用户手绘线稿（待衍生的底图）
  · `buildings.BUILDINGS`          → 已有专属 render 的建筑（优先，质量更高）

产物
  `public/mapicons/<key>/day.png`、`<key>/night.png`
  `icongen/catalog.json`、`icongen/catalog.md`（建筑目录，给下一个 AI 当设计简令）

用法
  python make_icons.py --report            # 只报告：每个键的来源 / 缺什么
  python make_icons.py --catalog           # 只导出 catalog.json / catalog.md
  python make_icons.py --all               # 生成全部键的 day + night
  python make_icons.py --all --only night  # 只生成夜图
  python make_icons.py qinglou             # 只生成一个键

日夜处理
  · 有专属 render 的建筑：`kit.with_palette(DAY_PALETTE, fn)` → 同一份绘图代码出日色
  · 手绘线稿：自动衍生 ——
      日：浅石渐变填充封闭区 + 墨线
      夜：暗暖渐变 + 琥珀背光 + **线条反白**（否则黑线在黑底上看不见）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import OrderedDict

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)                                   # kit / buildings
sys.path.insert(0, os.path.dirname(HERE))                  # song_kinds

import kit                                                  # noqa: E402
import buildings                                            # noqa: E402
import archetypes                                           # noqa: E402

try:
    from song_kinds import KINDS
except Exception:                                           # pragma: no cover
    KINDS = {}

MAPICONS = os.path.normpath(os.path.join(HERE, "..", "..", "..",
                                         "trpg-client", "public", "mapicons"))
ORIGINAL = os.path.join(HERE, "_original")
MANIFEST = os.path.join(MAPICONS, "manifest.txt")

# ---- 手绘线稿衍生的配色 ----
DAY_LINE = (44, 38, 34, 255)               # 白天：墨线（= 用户原稿）
NIGHT_LINE = (240, 218, 182, 255)          # 夜里：线条反白（黑线在暗底上看不见）
HALO = (232, 190, 120)                     # 夜里的琥珀背光

# 注：曾试过“对线稿封闭区填色”自动上色，但**用户线稿是散笔而非闭合轮廓**
#     （屋顶线 + 柱 + 底座，处处开口），floodfill 会漏成一片 → 已放弃。
#     现在夜图不填色，只做「琥珀背光 + 线条反白」，对任何线稿都稳。

# --------------------------------------------------------------------------
# 目录：把三处来源合成一张表
# --------------------------------------------------------------------------
def read_manifest():
    """返回 {key: 布点数量}。manifest 由 export_clickable.py 生成。"""
    out = {}
    if not os.path.exists(MANIFEST):
        return out
    for line in open(MANIFEST, encoding="utf-8"):
        # 新格式：ward/day.png + ward/night.png   (x165)
        m = re.match(r"\s*([\w-]+)/day\.png.*?\(x(\d+)\)", line)
        if not m:      # 兼容旧格式：ward.png   (x165)
            m = re.match(r"\s*([\w-]+)\.png\s*\(x(\d+)\)", line)
        if m:
            out[m.group(1)] = int(m.group(2))
    return out


def collect():
    """→ OrderedDict key -> 介绍信息（按布点数量降序）"""
    counts = read_manifest()
    keys = {}

    def slot(k):
        return keys.setdefault(k, {"icon": k, "kinds": [], "groups": [], "zones": [],
                                   "notes": [], "count": counts.get(k, 0)})

    for kind, info in KINDS.items():
        k = info.get("icon")
        if not k:
            continue
        s = slot(k)
        s["kinds"].append(kind)
        if info.get("group") not in s["groups"]:
            s["groups"].append(info.get("group"))
        if info.get("zone") not in s["zones"]:
            s["zones"].append(info.get("zone"))
        if info.get("note"):
            s["notes"].append("%s：%s" % (kind, info["note"]))

    for k in counts:                                       # 布点里有、KINDS 里没有的键（如 ward）
        slot(k)

    for k in archetypes.SPECS:                             # 原型库覆盖的键（含旧键）
        slot(k)

    for k, s in keys.items():
        if k in buildings.BUILDINGS:
            s["source"] = "bespoke"
        elif k in archetypes.SPECS:
            s["source"] = "archetype"
        else:
            s["source"] = "missing"
        s["group"] = "/".join(s["groups"]) or "—"
        s["zone"] = "/".join(s["zones"]) or "—"
    return OrderedDict(sorted(keys.items(), key=lambda kv: (-kv[1]["count"], kv[0])))


# --------------------------------------------------------------------------
# 手绘线稿 → 日/夜
# --------------------------------------------------------------------------
def _vgrad(size, top, bot):
    w, h = size
    g = Image.new("RGBA", (1, h))
    px = g.load()
    for y in range(h):
        t = y / max(1, h - 1)
        px[0, y] = tuple(round(top[i] + (bot[i] - top[i]) * t) for i in range(3)) + (255,)
    return g.resize((w, h), Image.BILINEAR)


def derive_from_original(src, night):
    """线稿 → 日/夜图标。

    白天 = **原稿原样**（墨线）—— 不改动用户的美术。
    夜里 = 线条反白（暖白）+ 琥珀背光，读作“屋里亮着灯”。
    不做封闭区填色（见上方注释：散笔线稿无法可靠填色）。
    """
    img = kit.fit_icon(src.convert("RGBA"))
    if not night:
        return img

    a = img.getchannel("A")
    halo = (a.point(lambda v: 255 if v > 40 else 0)
             .filter(ImageFilter.MaxFilter(7))
             .filter(ImageFilter.GaussianBlur(4.5))
             .point(lambda v: int(v * 0.62)))
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.paste(Image.new("RGBA", img.size, HALO + (255,)), mask=halo)
    line = Image.new("RGBA", img.size, NIGHT_LINE)
    line.putalpha(a)
    out.alpha_composite(line)
    return out


# --------------------------------------------------------------------------
# 生成
# --------------------------------------------------------------------------
def build(key, night, src_info):
    """有专属 render 用专属；否则走原型库。日图 = 换 DAY_PALETTE（只关灯）。"""
    if src_info.get("source") == "bespoke":
        fn = buildings.BUILDINGS[key]
    elif key in archetypes.SPECS:
        fn = (lambda k=key: archetypes.render(k))
    else:
        return None
    return kit.fit_icon(fn() if night else kit.with_palette(kit.DAY_PALETTE, fn))


def write_catalog(keys, out_json=None, out_md=None):
    out_json = out_json or os.path.join(HERE, "catalog.json")
    out_md = out_md or os.path.join(HERE, "catalog.md")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(keys, f, ensure_ascii=False, indent=1)

    total = sum(s["count"] for s in keys.values())
    lines = ["# 建筑图标目录（自动生成，勿手改）",
             "",
             "> 由 `make_icons.py --catalog` 从 `song_kinds.py` 的 KINDS + `manifest.txt` 布点数量汇总。",
             "> **画图标前先看这里**：每个 `icon` 键对应的场所名、功能大类、布点倾向、备注。",
             "",
             "| icon 键 | 布点数 | 来源 | 功能大类 | 布点 | 对应场所（KINDS） |",
             "|---|---|---|---|---|---|"]
    for k, s in keys.items():
        src = {"bespoke": "专属 render", "archetype": "原型库", "missing": "**缺**"}[s["source"]]
        lines.append("| `%s` | %d | %s | %s | %s | %s |"
                     % (k, s["count"], src, s["group"], s["zone"], "、".join(s["kinds"]) or "—"))
    lines += ["", "合计布点 %d 处，键 %d 个。" % (total, len(keys)), "",
              "## 各键备注（直接当设计简令）", ""]
    for k, s in keys.items():
        if not s["notes"]:
            continue
        lines.append("### `%s`（%d 处，%s）" % (k, s["count"], s["group"]))
        for n in s["notes"]:
            lines.append("- " + n)
        lines.append("")
    with open(out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return out_json, out_md


def report(keys):
    print("%-12s %6s  %-10s %s" % ("icon 键", "布点", "来源", "对应场所"))
    for k, s in keys.items():
        flag = {"bespoke": "专属 render", "archetype": "原型库", "missing": "缺!!"}[s["source"]]
        print("%-12s %6d  %-10s %s" % (k, s["count"], flag, "、".join(s["kinds"]) or "—"))
    miss = [k for k, s in keys.items() if s["source"] == "missing"]
    print("\n共 %d 键 / %d 处布点；缺图 %d 个%s"
          % (len(keys), sum(s["count"] for s in keys.values()), len(miss),
             ("：" + "、".join(miss)) if miss else ""))


def main():
    ap = argparse.ArgumentParser(description="建筑图标 day/night 自动化管线")
    ap.add_argument("key", nargs="?", help="只处理某个 icon 键")
    ap.add_argument("--all", action="store_true", help="处理全部键")
    ap.add_argument("--only", choices=["day", "night"], help="只出其中一张")
    ap.add_argument("--report", action="store_true", help="只报告来源与缺口")
    ap.add_argument("--catalog", action="store_true", help="只导出 catalog")
    a = ap.parse_args()

    keys = collect()
    if a.report:
        report(keys)
        return
    cat = write_catalog(keys)
    if a.catalog:
        print("目录 →", cat[0], "|", cat[1])
        return

    targets = [a.key] if a.key else (list(keys) if a.all else [])
    if not targets:
        ap.error("要指定 key，或用 --all / --report / --catalog")
    modes = [a.only] if a.only else ["day", "night"]

    made = skipped = 0
    for k in targets:
        if k not in keys:
            print("  ? 未知键 %s（不在 KINDS / manifest 里）" % k)
            continue
        for mode in modes:
            img = build(k, mode == "night", keys[k])
            if img is None:
                print("  !! %-12s %s 无底图（既无 render 也无 _original/%s.png）" % (k, mode, k))
                skipped += 1
                continue
            d = os.path.join(MAPICONS, k)
            os.makedirs(d, exist_ok=True)
            kit._safe_save(img, os.path.join(d, mode + ".png"))
            made += 1
        print("  ok %-12s (%s) ← %s" % (k, keys[k]["source"], "、".join(keys[k]["kinds"]) or "—"))
    print("\n生成 %d 张，跳过 %d 张" % (made, skipped))


if __name__ == "__main__":
    main()
