#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""背景图 AI 重构：为每个 kind 生成「参考图 + 提示词」文件夹包。

本工作流**不调用任何生图 API**，只把素材和提示词整理成人可以直接喂给生图 AI 的文件夹。

用法：
    python trpg-client/scripts/background-pipeline/build_packs.py
    python trpg-client/scripts/background-pipeline/build_packs.py --kind 青楼
    python trpg-client/scripts/background-pipeline/build_packs.py --link copy --force

产出 packs/<kind>/：
    说明.md                 元信息、操作步骤、完整提示词
    白天/提示词.txt         可直接粘贴的提示词
    白天/01_<场景>.png      参考图（按文件名顺序即提交顺序）
    黑夜/提示词.txt
    黑夜/01_<场景>.png
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent


def find_repo_root(start: Path) -> Path:
    """向上寻找项目根，避免脚本所在的子目录层级变化后路径失效。"""
    for candidate in (start, *start.parents):
        if (candidate / "trpg-client").is_dir() and (candidate / "trpg-map").is_dir():
            return candidate
    raise RuntimeError(f"无法从 {start} 定位项目根目录")


REPO_ROOT = find_repo_root(SCRIPT_DIR)
DEFAULT_CONFIG = SCRIPT_DIR / "config.json"


def repo_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else REPO_ROOT / path


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def load_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_kinds(path: Path) -> dict[str, dict[str, str]]:
    """静态读取 song_kinds.py 的 KINDS，避免导入地图生成模块的其它依赖。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "KINDS" for t in node.targets):
            continue
        assert isinstance(node.value, ast.Dict)
        out: dict[str, dict[str, str]] = {}
        for key_node, value_node in zip(node.value.keys, node.value.values):
            if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
                continue
            values: dict[str, str] = {}
            if (
                isinstance(value_node, ast.Call)
                and isinstance(value_node.func, ast.Name)
                and value_node.func.id == "dict"
            ):
                for kw in value_node.keywords:
                    if kw.arg and isinstance(kw.value, ast.Constant):
                        values[kw.arg] = str(kw.value.value)
            out[key_node.value] = values
        return out
    raise RuntimeError(f"没有在 {path} 找到 KINDS")


def _split_table_row(line: str) -> list[str]:
    body = line.strip().strip("|")
    return [cell.strip() for cell in body.split("|")]


def load_scene_manifest(path: Path) -> dict[str, dict[str, str]]:
    """解析《背景场景重构清单》的表格 → {kind: {原型, 画面核心, 分组}}。

    清单是「场景原型 / 画面核心」的单一真相源，这里只做映射，不重复维护。
    """
    out: dict[str, dict[str, str]] = {}
    section = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        if not line.startswith("|"):
            continue
        cells = _split_table_row(line)
        if len(cells) < 3 or cells[0] in ("场景目录名", "场景名") or set(cells[0]) <= {"-", " "}:
            continue
        scene, kinds_cell, core = cells[0], cells[1], cells[2]
        for kind in kinds_cell.replace("、", ",").replace("，", ",").split(","):
            kind = kind.strip()
            if kind:
                out.setdefault(kind, {"原型": scene, "画面核心": core, "章节": section})
    return out


def reference_for_period(root: Path, scene: str, period: str) -> Path:
    """优先取同时间参考图；缺失时按 白天 → 黑夜 → 黄昏 回退。"""
    for name in dict.fromkeys([period, "白天", "黑夜", "黄昏"]):
        candidate = root / scene / f"{name}.png"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"参考场景没有可用图片：{scene}")


def resolve_reference_scenes(config: dict, kind: str, meta: dict[str, str]) -> list[str]:
    scenes = config["kind_reference_overrides"].get(kind) or config["group_profiles"].get(meta.get("group", ""))
    if not scenes:
        raise RuntimeError(f"{kind}: 分组 {meta.get('group')!r} 没有参考图池，也没有单独配置")
    scenes = list(dict.fromkeys(scenes))
    if len(scenes) < 3:
        raise RuntimeError(f"{kind}: 参考场景少于 3 个")
    return scenes[: int(config.get("reference_count", 4))]


def build_prompt(
    config: dict,
    kind: str,
    meta: dict[str, str],
    scene: dict[str, str],
    period: str,
    ref_files: list[str],
) -> str:
    zone = config["zone_text"].get(meta.get("zone", "general"), config["zone_text"]["general"])
    lines: list[str] = []
    lines.append("生成一张中国古代（南宋）场景背景插画，用于 TRPG 游戏的场景切换。")
    lines.append("")
    lines.append("【最高优先级 · 必须遵守】")
    lines.append(config["最高优先级"])
    lines.append("")
    lines.append(f"【场景】{kind}")
    if scene.get("原型"):
        lines.append(f"【场景原型】{scene['原型']}")
    core = config.get("kind_core_overrides", {}).get(kind) or scene.get("画面核心")
    if core:
        lines.append(f"【画面核心】{core}")
    focus = config.get("kind_scene_focus", {}).get(kind)
    if focus:
        lines.append("【场景建筑与陈设重点】")
        lines.append(focus)
    lines.append(f"【类别】{meta.get('group', '')}")
    if meta.get("note"):
        lines.append(f"【历史功能】{meta['note']}")
    lines.append(f"【位置】{zone}")
    lines.append(f"【时段】{period}")
    if meta.get("窄景"):
        lines.append("")
        lines.append("【构图 · 局部窄景（必须遵守）】")
        lines.append("- 近景 / 中近景：只取该空间的一角，视角收窄，不要大全景、不要多进纵深。")
        lines.append("- 元素从简：画面只保留 2~3 件核心物件，其余留白，不要堆满家具陈设。")
        lines.append("- 可用门框、窗棂、纱帐、梁柱作前景遮挡，强化「站在门内 / 角落」的视角。")
    lines.append("")
    lines.append("【画面要求】")
    for item in config["固定要求"]:
        if meta.get("窄景") and "中远景" in item:
            item = item.replace("横向中远景", "横向中近景（视角收窄）")
        lines.append(f"- {item}")
    lines.append("")
    lines.append("【美术风格】")
    lines.append(config["美术风格"])
    lines.append("")
    lines.append("【光照与材质】")
    lines.append(config["光照与材质"])
    lines.append(config["period_rules"][period])
    lines.append("")
    lines.append("【禁止项】")
    for item in config["禁止项"]:
        lines.append(f"- 禁止：{item}")
    lines.append("")
    lines.append("【参考图用法】")
    lines.append(config["参考图通用说明"])
    if period == "黑夜":
        lines.append(config["夜间构图继承提示"])
    lines.append(f"按文件名数字顺序一并提交，共 {len(ref_files)} 张：")
    roles = config["reference_roles"]
    for index, name in enumerate(ref_files):
        lines.append(f"{index + 1}. {name} —— {roles[index] if index < len(roles) else roles[-1]}")
    lines.append("")
    lines.append(f"【输出】1920×1080 横构图 PNG，画面中不要出现任何文字，也不要出现任何人物。")
    return "\n".join(lines)


def materialize(src: Path, dst: Path, link_mode: str) -> str:
    """把参考图放进包内。hardlink 几乎不占空间，copy 最稳妥。"""
    if dst.exists():
        return "exists"
    if link_mode == "hardlink":
        try:
            os.link(src, dst)
            return "hardlink"
        except OSError:
            pass
    if link_mode == "symlink":
        try:
            dst.symlink_to(src.resolve())
            return "symlink"
        except OSError:
            pass
    shutil.copy2(src, dst)
    return "copy"


def write_kind_pack(
    config: dict,
    kind: str,
    meta: dict[str, str],
    scene: dict[str, str],
    scenes: list[str],
    pack_dir: Path,
    link_mode: str,
    force: bool,
) -> None:
    ref_root = repo_path(config["reference_root"])

    for period in config["periods"]:
        folder = pack_dir / period
        folder.mkdir(parents=True, exist_ok=True)

        ref_files: list[str] = []
        for index, scene_name in enumerate(scenes, 1):
            src = reference_for_period(ref_root, scene_name, period)
            filename = f"{index:02d}_{scene_name}{src.suffix}"
            target = folder / filename
            if force and target.exists():
                target.unlink()
            materialize(src, target, link_mode)
            ref_files.append(filename)

        (folder / "提示词.txt").write_text(
            build_prompt(config, kind, meta, scene, period, ref_files) + "\n",
            encoding="utf-8",
        )

    steps = [
        f"# {kind}",
        "",
        f"- 类别：{meta.get('group', '')}",
        f"- 历史功能：{meta.get('note', '')}",
        f"- 场景原型：{scene.get('原型', '（清单里没有找到）')}",
        f"- 画面核心：{scene.get('画面核心', '')}",
        f"- 位置倾向：{meta.get('zone', '')}",
        "",
        "## 操作步骤",
        "",
        "1. 打开 `白天/`，把目录里的参考图和 `提示词.txt` 一起提交给生图 AI。",
        "2. 拿到白天成品图后，接着做 `黑夜/`：把**刚生成的白天图**当第一参考，再加 `黑夜/` 里的参考图和提示词，一起提交。",
        "3. 两张图直接输出即可，不需要保存、改名或搬运文件。",
        "",
        "## 目录内容",
        "",
        "- `白天/`：参考图 + `提示词.txt`",
        "- `黑夜/`：参考图 + `提示词.txt`（第一参考用你刚生成的白天图）",
        "",
        "## 提示词全文",
        "",
        "### 白天",
        "",
        "```text",
        (pack_dir / "白天" / "提示词.txt").read_text(encoding="utf-8").strip(),
        "```",
        "",
        "### 黑夜",
        "",
        "```text",
        (pack_dir / "黑夜" / "提示词.txt").read_text(encoding="utf-8").strip(),
        "```",
        "",
    ]
    (pack_dir / "说明.md").write_text("\n".join(steps), encoding="utf-8")


def load_priority(config: dict) -> dict[str, int]:
    """从《背景场景重构清单》的「推荐分批制作」解析 P0 / P1 场景名单 → {场景原型: 优先级}。"""
    lines = repo_path(config["scene_manifest"]).read_text(encoding="utf-8").splitlines()
    out: dict[str, int] = {}
    try:
        start = next(i for i, line in enumerate(lines) if line.startswith("## 推荐分批制作"))
    except StopIteration:
        return out
    current: int | None = None
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        if line.startswith("### "):
            title = line[4:].strip()
            current = {"P0": 0, "P1": 1, "P2": 2}.get(title[:2])
            continue
        if current in (0, 1) and line.strip():
            for name in line.replace("，", "、").replace(",", "、").split("、"):
                # 名单末尾常带句号（「…、私家园林。」），不去掉就匹配不上场景名
                name = name.strip().strip("。.．")
                if name:
                    out.setdefault(name, current)
    return out


def rank_of(priority: dict, kinds: dict, manifest: dict, kind: str) -> int:
    """kind 的批次：`extra_kinds` 里显式 `priority` 优先，否则按场景原型查 P0/P1 名单。"""
    p = kinds.get(kind, {}).get("priority")
    if isinstance(p, int):
        return p
    return priority.get(manifest.get(kind, {}).get("原型", ""), 2)


def ordered_kinds(
    config: dict, kinds: dict[str, dict[str, str]], manifest: dict[str, dict[str, str]]
) -> list[tuple[int, str]]:
    """按 P0 → P1 → P2 排序，同批内保持声明顺序。"""
    priority = load_priority(config)
    indexed = list(enumerate(kinds))
    indexed.sort(key=lambda item: (rank_of(priority, kinds, manifest, item[1]), item[0]))
    return [(rank, kind) for rank, (_, kind) in enumerate(indexed)]


CHECKLIST_NAME = "生成顺序.md"
_ITEM_RE = re.compile(r"^- \[([ x!])\] \d+\. (.+?)(?: —|$)")


def _read_checklist_state(path: Path) -> dict[str, str]:
    """读回已勾选状态，重新生成清单时不丢进度。"""
    if not path.is_file():
        return {}
    state: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _ITEM_RE.match(line)
        if match:
            state[match.group(2).strip()] = match.group(1)
    return state


def write_checklist(
    config: dict,
    kinds: dict[str, dict[str, str]],
    manifest: dict[str, dict[str, str]],
    packs_root: Path,
) -> Path:
    """写「生成顺序.md」：给执行生成的 AI 逐项勾选、不许停的作业清单。"""
    path = packs_root / CHECKLIST_NAME
    state = _read_checklist_state(path)
    periods = config["periods"]
    indexed = ordered_kinds(config, kinds, manifest)
    priority = load_priority(config)

    items: list[tuple[str, str, list[str]]] = []
    finished = set(config.get("已完成", []))
    for _, kind in indexed:
        if kind in finished:
            continue
        scenes = resolve_reference_scenes(config, kind, kinds[kind])
        for period in periods:
            refs = [f"{i:02d}_{s}.png" for i, s in enumerate(scenes, 1)]
            items.append((kind, period, refs))

    total = len(items)
    done = sum(1 for key, mark in state.items() if mark == "x")
    failed = sum(1 for key, mark in state.items() if mark == "!")

    head = [
        "# 背景图生成顺序",
        "",
        "> 给执行生成的 AI / Agent 的作业清单。读完直接开工，不要问，不要停。",
        "",
        "## 执行规则（必须遵守）",
        "",
        "1. 从本文件**第一行未勾选**的项开始，逐项往下做，不要跳号、不要重排。",
        "2. 每完成一项，立刻把那一行的 `- [ ]` 改成 `- [x]`，**然后不等指令、直接开始下一项**。",
        "3. **不要询问、不要请求确认、不要中途汇报、不要停下来等用户。** 一直做到最后一项为止。",
        "4. 单项失败：最多重试 2 次；仍失败就把 `- [ ]` 改成 `- [!]`，立刻继续下一项，不要卡住。",
        "5. 全部跑完后再输出一次简短汇总（完成数 / 失败数）。",
        "",
        "## 每一项怎么做",
        "",
        "拿到某一项 `<kind> / <时段>` 后：",
        "",
        "1. **读提示词**：`packs/<kind>/<时段>/提示词.txt`（原样使用，不要自己改写）。",
        "2. **参考图**：`packs/<kind>/<时段>/` 里的全部 png，按文件名数字顺序提交；每一项行尾已列出文件名。",
        "3. **出图**：1920×1080 横构图；必须是**无人空景**，不出现任何人物与活动物。",
        "4. **直接输出图片**，不要保存文件、不要改名、不要搬运到其它目录。",
        "5. **勾掉本行**，立刻开始下一项。",
        "",
        "> 黑夜项的额外第一参考：**你上一步刚为同一个 kind 生成的白天图**。先出白天图，再把它当第一张参考图叠上 `黑夜/` 里的参考图，以锁定构图。",
        "> 不需要把白天图存成文件，直接用你刚刚输出的那张。",
        "",
        "## 进度",
        "",
        f"- 总项数：{total}",
        f"- 已完成：{done}（失败标记：{failed}）",
        "- 每勾掉一项，顺手把上面的已完成数 +1。",
        *( [f"- 已从清单中移除（已完成）：{'、'.join(sorted(finished))}"] if finished else [] ),
        "",
        "## 清单",
        "",
    ]

    body: list[str] = []
    current_rank: int | None = None
    for number, (kind, period, refs) in enumerate(items, 1):
        rank = rank_of(priority, kinds, manifest, kind)
        if rank != current_rank:
            current_rank = rank
            if body:
                body.append("")
            title = {0: "第一批 P0 · 核心高频与高辨识度", 1: "第二批 P1 · 常用经营设施", 2: "第三批 P2 · 其余设施、城防与郊外"}[rank]
            body.append(f"### {title}")
            body.append("")
        mark = state.get(f"{kind} / {period}", " ")
        body.append(f"- [{mark}] {number:03d}. {kind} / {period} — " + "、".join(refs))
    body.append("")

    text = "\n".join(head + body)
    path.write_text(text, encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="生成背景图 AI 重构素材包（参考图 + 提示词）")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--kind", action="append", help="只生成指定 kind，可重复")
    parser.add_argument("--link", choices=["hardlink", "copy", "symlink"], default="hardlink",
                        help="参考图放入包内的方式（默认 hardlink：几乎不额外占空间）")
    parser.add_argument("--force", action="store_true", help="覆盖已有包内的参考图")
    args = parser.parse_args()

    config = load_config(args.config.resolve())
    kinds = load_kinds(repo_path(config["source_kinds"]))
    manifest = load_scene_manifest(repo_path(config["scene_manifest"]))
    # `config.extra_kinds`：地图直接生成、但不在 song_kinds.py 里的结构/地形 kind
    # （坊 / 官道 / 城墙 / 村 / 镇 / 殿 / 楼 / 廊 / 院墙 / 宫门 / 果园）。
    # 不塞进 song_kinds.py（那是 POI 布点表），只作流水线的补充来源。
    extra = config.get("extra_kinds") or {}
    for kind, info in extra.items():
        kinds.setdefault(kind, {k: info[k] for k in ("group", "icon", "zone", "note", "窄景", "priority") if k in info})
        if kind not in manifest and (info.get("原型") or info.get("画面核心")):
            manifest[kind] = {
                "原型": info.get("原型", ""),
                "画面核心": info.get("画面核心", ""),
                "章节": info.get("章节", "扩展"),
            }
    packs_root = repo_path(config["packs_root"])
    packs_root.mkdir(parents=True, exist_ok=True)

    selected = args.kind or list(kinds)
    unknown = [k for k in selected if k not in kinds]
    if unknown:
        raise RuntimeError("未知 kind：" + "、".join(unknown))

    unmapped: list[str] = []
    for kind in selected:
        meta = kinds[kind]
        scene = manifest.get(kind, {})
        if not scene:
            unmapped.append(kind)
        scenes = resolve_reference_scenes(config, kind, meta)
        write_kind_pack(config, kind, meta, scene, scenes, packs_root / kind, args.link, args.force)
        print(f"已生成 {kind}")

    checkpoint = write_checklist(config, kinds, manifest, packs_root)
    print(f"\n素材包目录：{rel(packs_root)}")
    print(f"生成顺序：{rel(checkpoint)}")
    if unmapped:
        print(f"警告：《{config['scene_manifest']}》里没有这些 kind 的场景原型：{'、'.join(unmapped)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
