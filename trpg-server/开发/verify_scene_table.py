# -*- coding: utf-8 -*-
"""
verify_scene_table.py
=====================
【自检脚本，非正式模块】核对 `trpg-world/场景表.json` 与「美术图 / 流水线 / 地图 kind」是否对得上。

为什么要它：
    背景这条线有四个真相源，改一个很容易忘另一个——
      · `trpg-world/场景表.json`         场景说明 / 地点候选 / 兜底组 / 场景原型
      · `trpg-client/src/assets/背景_重构/`  实际有图（运行时 `scene_keys()` 只认这里）
      · `background-pipeline/config.json`    extra_kinds（待出图的结构/室内 kind）
      · 两城空间库 `ancient_kind`            玩家实际会踩到的地点类型
    人工核对很累，而且出错是**静默**的（图有了选不到、映射挂了没图、模型见名不知意）。

它查（✗ = 错误，会让脚本 exit 1；· = 提示，不影响退出码）：
    ① 候选/兜底里出现的场景，都在 `场景说明` 里有说明（否则小模型见名瞎猜）
    ② 被引用的场景，要么有图，要么在待出图清单里（否则映射到一个永远不存在的名字）
    ③ `背景_重构/` 里每个**有图目录**都至少被引用一次（否则画了永远选不到）
    ④ 两城地图 kind 并集 ⊆ `地点候选` 的 key（否则该 kind 掉兜底组）
    ⑤ `song_kinds` 的每个 kind 都有 `场景原型`（否则背景流水线出不了提示词）

只读，不改任何文件。运行：
    cd trpg-server
    python 开发/verify_scene_table.py
    python 开发/verify_scene_table.py -v      # 每类最多列 200 条（默认 40）
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# 允许 `python 开发/verify_scene_table.py` 直接跑：song_kinds 在 trpg-map/draw_tiles/
sys.path.insert(0, str(REPO / "trpg-map" / "draw_tiles"))

try:
    sys.stdout.reconfigure(encoding="utf-8")   # Windows 控制台默认 GBK
except Exception:
    pass

from song_kinds import KINDS as SONG_KINDS  # noqa: E402

SCENE_TABLE = REPO / "trpg-world" / "场景表.json"
SCENE_DIR = REPO / "trpg-client" / "src" / "assets" / "背景_重构"
PIPE_CONFIG = REPO / "trpg-client" / "scripts" / "background-pipeline" / "config.json"
DB_DIR = REPO / "trpg-map" / "draw_tiles" / "db"

PERIODS = ("白天", "黑夜", "黄昏")


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"[!] 读不了 {path}：{type(e).__name__}: {e}")
        return {}


def art_dirs() -> set[str]:
    """`背景_重构/<城内|城外|室内>/` 下**确实有图**的场景目录名。"""
    out: set[str] = set()
    for cat in ("城内", "城外", "室内"):
        d = SCENE_DIR / cat
        if not d.is_dir():
            continue
        for sub in d.iterdir():
            if sub.is_dir() and any((sub / f"{p}.png").is_file() for p in PERIODS):
                out.add(sub.name)
    return out


def map_kinds() -> dict[str, set[str]]:
    """每个城市空间库里的 `ancient_kind` 集合（一城一个 db，自动发现）。"""
    out: dict[str, set[str]] = {}
    for db in sorted(DB_DIR.glob("map_spatial_*.db")):
        city = db.stem[len("map_spatial_"):]
        try:
            conn = sqlite3.connect(str(db))
            rows = conn.execute(
                "SELECT DISTINCT ancient_kind FROM features "
                "WHERE ancient_kind IS NOT NULL AND ancient_kind != ''"
            ).fetchall()
            conn.close()
        except sqlite3.Error as e:
            print(f"[!] 读不了地图库 {db.name}：{e}")
            continue
        out[city] = {str(r[0]).strip() for r in rows if str(r[0]).strip()}
    return out


def _show(tag: str, items, limit: int) -> None:
    items = sorted(str(x) for x in items)
    if not items:
        print(f"  [✓] {tag}")
        return
    head = "、".join(items[:limit])
    more = f" ……（共 {len(items)} 个，只列前 {limit}）" if len(items) > limit else ""
    print(f"  [✗] {tag}（{len(items)}）：{head}{more}")


def main() -> int:
    ap = argparse.ArgumentParser(description="核对 场景表.json / 美术图 / 流水线 / 地图 kind")
    ap.add_argument("-v", "--verbose", action="store_true", help="每类最多列 200 条")
    args = ap.parse_args()
    limit = 200 if args.verbose else 40

    table = _load_json(SCENE_TABLE)
    if not table:
        return 1
    pipe = _load_json(PIPE_CONFIG)

    说明 = set(table.get("场景说明") or {})
    候选 = table.get("地点候选") or {}
    兜底 = table.get("兜底组") or {}
    原型 = table.get("场景原型") or {}

    引用: set[str] = set()
    for scenes in list(候选.values()) + list(兜底.values()):
        if isinstance(scenes, list):
            引用 |= {str(s).strip() for s in scenes if str(s).strip()}

    有图 = art_dirs()
    #: 流水线已登记的 kind（有提示词/计划，可能还没出图）= song_kinds + extra_kinds
    已登记 = set(SONG_KINDS) | set(pipe.get("extra_kinds") or {})
    缺图 = 已登记 - 有图
    城市kind = map_kinds()
    地图kind = set().union(*城市kind.values()) if 城市kind else set()

    print("[场景表自检]")
    print(f"  场景说明 {len(说明)} · 地点候选 {len(候选)} · 兜底组 {len(兜底)} · "
          f"引用场景 {len(引用)} · 有图 {len(有图)} · "
          f"已登记 kind {len(已登记)}（其中缺图 {len(缺图)}） · "
          f"地图 kind {len(地图kind)}（{len(城市kind)} 城）")
    print()
    print("检查：")

    errs = 0
    hits = 引用 - 说明
    _show("① 候选/兜底里的场景都有说明", hits, limit)
    errs += bool(hits)

    hits = 引用 - (有图 | 已登记)
    _show("② 被引用的场景都有图、或已登记（有出图计划）", hits, limit)
    errs += bool(hits)

    hits = 有图 - 引用
    _show("③ 有图目录都被某个候选集合引用", hits, limit)
    errs += bool(hits)

    hits = 地图kind - set(候选)
    _show("④ 两城地图 kind 都已映射（否则掉兜底）", hits, limit)
    errs += bool(hits)

    hits = set(SONG_KINDS) - set(原型)
    _show("⑤ song_kinds 都有场景原型（流水线能出提示词）", hits, limit)
    errs += bool(hits)

    # 提示（不算错误）
    notes = {
        "已登记但还没出图的 kind（要画的活）": 缺图,
        "候选里未被两城地图使用的 kind（其他城/未来用）": set(候选) - 地图kind,
        "场景说明中未被任何候选引用的场景（孤儿说明）": 说明 - 引用,
        "场景原型里不属于 song_kinds 的 kind（清单顺带映射）": set(原型) - set(SONG_KINDS),
    }
    if any(notes.values()):
        print()
        print("提示（不影响退出码）：")
        for tag, items in notes.items():
            extra = f"（≈ {len(items) * 2} 张：每 kind 白天+黑夜）" if "还没出图" in tag else ""
            print(f"  · {tag}：{len(items)} 个{extra}")
            if args.verbose and items:
                print("      " + "、".join(sorted(items)[:limit]))

    print()
    print(f"结果：{'✗ 有问题' if errs else '✓ 全部通过'}")
    return 1 if errs else 0


if __name__ == "__main__":
    raise SystemExit(main())
