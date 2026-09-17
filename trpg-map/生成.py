# -*- coding: utf-8 -*-
"""
生成.py —— 一键跑完整链路：原料 PBF → 数据库 + 瓦片

    PBF
     │  pbf_to_json.py --city <城市>      按「城市画框」裁剪
     ▼
    数据/<城市>_OSM精简.json              ← build_world 的输入
     │  draw_tiles/build_world.py         世界生成（保留地理 + 算法生成城区）
     ▼
    数据/<城市>_南宋世界.json              ← 下游唯一输入
     ├─ export_clickable.py   → trpg-client/public/data/clickable.geojson
     ├─ db/create_spatial_db.py → draw_tiles/db/map_spatial.db
     │      └─ export_walkable.py → trpg-client/public/data/walkable.geojson（碰撞层）
     └─ tilegen/generate_tiles.py → draw_tiles/tiles/{z}/{x}/{y}.png
                                        └─ 拷到 trpg-client/public/tiles/

用法：
    python 生成.py                      # 扬州，全跑
    python 生成.py --city 岳阳
    python 生成.py --only tiles         # 只重生成瓦片
    python 生成.py --no-sync            # 不拷到前端
    python 生成.py --list               # 看有哪些步骤
"""

import argparse
import os
import shutil
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))          # trpg-map/
DRAW = os.path.join(BASE, "draw_tiles")
PROJECT = os.path.dirname(BASE)                            # trpg-project/
FRONTEND_PUBLIC = os.path.join(PROJECT, "trpg-client", "public")

PY = sys.executable

# Windows 控制台默认 GBK，撑不住中文/符号 → 强制 UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE_ENV = dict(os.environ, PYTHONIOENCODING="utf-8")

sys.path.insert(0, BASE)
from 城市 import CITIES, frame_bbox, map_id, DEFAULT_CITY  # noqa: E402


# ============================================================
# 步骤定义
# ============================================================

STEPS = [
    ("pbf", "PBF → 按画框裁剪 → OSM精简"),
    ("world", "世界生成 → 南宋世界"),
    ("clickable", "导出前端点击层"),
    ("db", "重建空间库 map_spatial.db"),
    ("walkable", "导出前端碰撞层（水域/城墙/城门/桥/路）"),
    ("tiles", "生成瓦片"),
    ("sync", "同步瓦片到前端 public/tiles"),
]


def run(cmd, cwd, env=None):
    print("$", " ".join(str(c) for c in cmd))
    t = time.time()
    p = subprocess.run(cmd, cwd=cwd, env=env or BASE_ENV)
    if p.returncode != 0:
        print(f"\n!! 步骤失败（exit {p.returncode}）")
        sys.exit(p.returncode)
    print(f"   -> 用时 {time.time() - t:.1f}s")


# ============================================================
# 各步骤
# ============================================================

def step_pbf(city):
    # 源 PBF 可与城市名不同（如岳阳用 湖南.pbf 全量，才能拿到完整洞庭湖）
    stem = CITIES[city].get("pbf", city)
    pbf = os.path.join(BASE, "数据", "源pbf", f"{stem}.pbf")
    if not os.path.exists(pbf):
        print(f"!! 找不到 {pbf}")
        print(f"   请先把 OSM 的 .pbf 放到 数据/源pbf/{stem}.pbf")
        sys.exit(1)
    run([PY, "pbf_to_json.py", os.path.join("数据", "源pbf", f"{stem}.pbf"),
         "--city", city,
         "-o", os.path.join("数据", f"{city}_OSM精简.json"),
         "--name", f"{city}地图"], cwd=BASE)


def step_world(city):
    # 城市布局参数在 draw_tiles/build_world.py 的 CITY_CONFIGS；不支持的城市会自行报错退出
    run([PY, "build_world.py"], cwd=DRAW, env=dict(BASE_ENV, TRPG_CITY=city))


def step_clickable(city):
    run([PY, "export_clickable.py"], cwd=DRAW, env=dict(BASE_ENV, TRPG_CITY=city))


def step_db(city):
    run([PY, os.path.join("db", "create_spatial_db.py")], cwd=DRAW,
        env=dict(BASE_ENV, TRPG_CITY=city))


def step_walkable(city):
    # 读 db/map_spatial.db，故必须在 db 之后
    run([PY, "export_walkable.py"], cwd=DRAW, env=dict(BASE_ENV, TRPG_CITY=city))


def step_tiles(city):
    env = dict(BASE_ENV, TRPG_CITY=city)
    print("$ TRPG_CITY=%s python tilegen/generate_tiles.py" % city)
    t = time.time()
    p = subprocess.run([PY, os.path.join("tilegen", "generate_tiles.py")],
                       cwd=DRAW, env=env)
    if p.returncode != 0:
        print("\n!! 瓦片生成失败")
        sys.exit(p.returncode)
    print(f"   -> 用时 {time.time() - t:.1f}s")


def step_sync(city):
    src = os.path.join(DRAW, "tiles", map_id(city))
    # 一城市一个目录：public/tiles/<map_id>/（绝不删别的城市）
    dst = os.path.join(FRONTEND_PUBLIC, "tiles", map_id(city))
    if not os.path.isdir(src):
        print("!! 没有瓦片可同步:", src)
        sys.exit(1)
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    n = sum(len(fs) for _, _, fs in os.walk(dst))
    size = sum(os.path.getsize(os.path.join(r, f))
               for r, _, fs in os.walk(dst) for f in fs) / 1048576
    print(f"   已同步 {n} 张 / {size:.0f} MB → {dst}")


HANDLERS = {
    "pbf": step_pbf,
    "world": step_world,
    "clickable": step_clickable,
    "db": step_db,
    "walkable": step_walkable,
    "tiles": step_tiles,
    "sync": step_sync,
}


# ============================================================
# main
# ============================================================

def main():
    ap = argparse.ArgumentParser(
        description="一键跑完整链路：PBF → 数据 → 数据库 + 瓦片",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--city", default=DEFAULT_CITY, choices=list(CITIES),
                    help="城市（默认 %s）" % DEFAULT_CITY)
    ap.add_argument("--only", default=None,
                    help="只跑某一步: " + "/".join(k for k, _ in STEPS))
    ap.add_argument("--no-sync", action="store_true", help="不拷瓦片到前端")
    ap.add_argument("--list", action="store_true", help="列出步骤")
    args = ap.parse_args()

    if args.list:
        for i, (k, desc) in enumerate(STEPS, 1):
            print(f"  {i}. {k:10s} {desc}")
        return

    city = args.city
    steps = [k for k, _ in STEPS]
    if args.only:
        if args.only not in steps:
            print("未知步骤:", args.only); sys.exit(1)
        steps = [args.only]
    if args.no_sync and "sync" in steps:
        steps.remove("sync")

    print("=" * 64)
    print(f"地图生成链路 —— {city}")
    print("=" * 64)
    print("画框：", tuple(round(v, 6) for v in frame_bbox(city)))
    print()

    t0 = time.time()
    for i, key in enumerate(steps, 1):
        desc = dict(STEPS)[key]
        print()
        print(f"--- [{i}/{len(steps)}] {key}：{desc} ---")
        HANDLERS[key](city)

    print()
    print("=" * 64)
    print(f"全部完成，用时 {time.time() - t0:.1f}s")
    print("=" * 64)


if __name__ == "__main__":
    main()
