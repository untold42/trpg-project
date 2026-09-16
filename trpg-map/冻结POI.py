# -*- coding: utf-8 -*-
"""
凍结POI.py —— 把 POI（category=custom）冻结成数据表，之后 build_world 只读它。

背景
    build_world.build_pois() 每次运行都**重新随机生成** POI
    （rng 采样位置 + rng.choice(名池) + 类别）。
    于是除 76 个固定锚点外，其余 ~1700 个 POI 的名字每次重跑都变，
    导致存档 / 足迹 / 地点见闻 / 世界状态里的地名全部对不上。

做法
    把某一份世界数据里的 POI 列表抽出来，写成 数据/<城市>_POI.json。
    build_world 之后**只读它**，不再随机生成 —— 名字与位置永久稳定。

    想恢复某一版的名字？用那一版的 <城市>_南宋世界.json 作为 --from 即可。

用法
    python 冻结POI.py --from _old.json --city 扬州     # 从旧世界冻结
    python 冻结POI.py --city 扬州                      # 从当前世界冻结
"""

import argparse
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "数据")

sys.path.insert(0, BASE)
from 城市 import DEFAULT_CITY  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", default=None,
                    help="从哪个世界 json 抽 POI（默认 数据/<城市>_南宋世界.json）")
    ap.add_argument("--city", default=DEFAULT_CITY)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    src = args.src or os.path.join(DATA, f"{args.city}_南宋世界.json")
    out = args.out or os.path.join(DATA, f"{args.city}_POI.json")

    objects = json.load(open(src, encoding="utf-8"))["objects"]

    pois = []
    for o in objects:
        if o.get("category") != "custom":
            continue
        g = o.get("geometry") or {}
        if g.get("type") != "Point":
            continue
        c = g.get("coordinates")
        if not c:
            continue
        pois.append({
            "name": o.get("name"),
            "kind": o.get("ancient_kind"),
            "lon": round(c[0], 7),
            "lat": round(c[1], 7),
        })

    data = {
        "comment": f"{args.city} POI 冻结表 —— build_world 只读它，不再随机生成",
        "city": args.city,
        "source": os.path.basename(src),
        "count": len(pois),
        "objects": pois,
    }

    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))

    kinds = {}
    for p in pois:
        kinds[p["kind"]] = kinds.get(p["kind"], 0) + 1

    print(f"来源：{src}")
    print(f"冻结：{len(pois)} 个 POI → {out}")
    print(f"类别：{len(kinds)} 种，前 8：",
          sorted(kinds.items(), key=lambda kv: -kv[1])[:8])


if __name__ == "__main__":
    main()
