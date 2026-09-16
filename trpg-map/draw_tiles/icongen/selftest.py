# -*- coding: utf-8 -*-
"""
自检：确认工具箱可用、各建筑能渲染、README 里的代码块"复制即用"。
改完 kit.py / buildings.py / README.md 后跑一次：

    python selftest.py

检查项
  1. 每个登记建筑的输出尺寸 / 内容占比（应 ≈100/128，与既有图标一致）
  2. README.md 里所有**定义 render_* 的 python 代码块**能否原样执行并渲染
  3. mapicons/<key>.png 是否与当前代码渲染结果**逐字节一致**（防资产陈旧/被回滚）
"""

import hashlib
import os
import re
import traceback

from PIL import Image

import kit
from buildings import BUILDINGS


def check_buildings():
    print("== 1. 登记建筑渲染 ==")
    bad = 0
    for name, fn in sorted(BUILDINGS.items()):
        try:
            img = kit.fit_icon(fn())
            bbox = img.getchannel("A").getbbox()
            if bbox is None:
                print("  [FAIL] %-12s 全透明（什么都没画）" % name)
                bad += 1
                continue
            side = max(bbox[2] - bbox[0], bbox[3] - bbox[1])
            ratio = side / kit.BASE
            flag = "[ OK ]" if 0.70 <= ratio <= 0.90 else "[warn] 占比异常"
            print("  %-6s %-12s %s bbox=%s 内容占比 %.2f" % (flag, name, img.size, bbox, ratio))
        except Exception:
            bad += 1
            print("  [FAIL] %-12s 渲染异常:" % name)
            traceback.print_exc()
    return bad


def check_readme():
    print("== 2. README 代码块 ==")
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "README.md")
    md = open(path, encoding="utf-8").read()
    blocks = re.findall(r"```python\n(.*?)```", md, re.S)
    ns = dict(globals())
    ns.update({k: getattr(kit, k) for k in dir(kit) if not k.startswith("_")})
    for name, fn in BUILDINGS.items():
        ns["render_" + name] = fn
    bad = checked = 0
    for i, code in enumerate(blocks, 1):
        if "def render_" not in code:      # 只校验"定义建筑"的块；其余是 API 片段/公式
            continue
        checked += 1
        try:
            exec(compile(code, "<README#%d>" % i, "exec"), ns)
        except Exception:
            bad += 1
            print("  [FAIL] README 第 %d 块执行失败:" % i)
            traceback.print_exc()
            continue
        for name in re.findall(r"def (render_\w+)", code):
            if name in BUILDINGS:
                continue
            try:
                kit.fit_icon(ns[name]())
                print("  [ OK ] README 第 %d 块 %s() 渲染成功" % (i, name))
            except Exception:
                bad += 1
                print("  [FAIL] README 第 %d 块 %s() 渲染失败:" % (i, name))
                traceback.print_exc()
    print("  共校验 %d 个定义块" % checked)
    return bad


def check_assets():
    """资产与代码一致性（新结构：mapicons/<键>/{day,night}.png）。

    为何必须查：渲染是全确定性的（同代码多次渲染 md5 相同），所以**应逐字节相等**。
    实测发生过：桌面被 OneDrive 同步，已落盘的图被回滚成旧版本。
    """
    print("== 3. 资产 vs 代码一致性 ==")
    here = os.path.dirname(os.path.abspath(__file__))
    mapicons = os.path.normpath(os.path.join(here, "..", "..", "..",
                                             "trpg-client", "public", "mapicons"))
    original = os.path.join(here, "_original")
    bad = 0

    def digest(img):
        return hashlib.md5(img.convert("RGBA").tobytes()).hexdigest()

    def on_disk(path):
        return digest(Image.open(path)) if os.path.exists(path) else None

    # 3a) 有专属 render 的：日/夜 两面都要与代码一致
    for name, fn in sorted(BUILDINGS.items()):
        want = {"night": digest(kit.fit_icon(fn())),
                "day": digest(kit.fit_icon(kit.with_palette(kit.DAY_PALETTE, fn)))}
        for mode, w in want.items():
            got = on_disk(os.path.join(mapicons, name, mode + ".png"))
            if got is None:
                bad += 1
                print("  [MISS] %-12s %s 缺 → 跑 python make_icons.py %s" % (name, mode, name))
            elif got != w:
                bad += 1
                print("  [STALE] %-12s %s 与代码不一致 → 重跑 make_icons.py %s" % (name, mode, name))
        else:
            if all(on_disk(os.path.join(mapicons, name, m + ".png")) == w for m, w in want.items()):
                print("  [ OK ] %-12s 日夜两面均与代码一致" % name)

    # 3b) 原型库：每个键的日/夜两面都要与代码一致
    import archetypes
    n_ok = n_bad = 0
    for k in sorted(archetypes.SPECS):
        if k in BUILDINGS:
            continue
        fn = (lambda kk=k: archetypes.render(kk))
        want = {"night": digest(kit.fit_icon(fn())),
                "day": digest(kit.fit_icon(kit.with_palette(kit.DAY_PALETTE, fn)))}
        ok = True
        for mode, w in want.items():
            if on_disk(os.path.join(mapicons, k, mode + ".png")) != w:
                ok = False
                print("  [STALE] %-12s %s 与原型库不一致 → make_icons.py %s" % (k, mode, k))
        if ok:
            n_ok += 1
        else:
            n_bad += 1
    print("  原型库：%d 键一致，%d 键需重跑" % (n_ok, n_bad))
    bad += n_bad
    return bad


if __name__ == "__main__":
    bad = check_buildings() + check_readme() + check_assets()
    print("\n%s" % ("全部通过" if bad == 0 else "有 %d 项失败" % bad))
    raise SystemExit(1 if bad else 0)
