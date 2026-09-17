# -*- coding: utf-8 -*-
"""
get_character.py
================
NPC 登场时**一次读全**其档案：**静态（正典）+ 动态（近记忆）**。

    trpg-world/角色静态档案/<名>.md       正典：外貌/身份/性格/身世…（模板 §1–§8）
    trpg-world/角色动态档案/活跃/<名>.md    近记忆：与梁峰关系/情绪/信息边界（§9–§13）
    trpg-world/角色动态档案/不活跃/<名>.md  已淘汰者的动态档案（若仍在）

**不含长期深层记忆（chroma `char_memory`）**——那是 LLM 按需自行调用
`DB_query_tool`（collection=char_memory, owner=<人物名>）去取的，本工具不代劳。

触发时机：**特定人物登场时先调用**（替代旧的 `find_specific_character`）。

匹配规则：
    1. 文件名精确匹配（如「唐中翎」）；
    2. 否则退回模糊匹配（支持绰号，如「龙王刀」→上官隼）：
       文件名包含 > 身份标识（称号/绰号/frontmatter description）> 正文包含；
       唯一命中才采用，命中多个则报错要求用全名。

返回值：
    {
      "success": True,
      "name":    "唐中翎",          # 规范名（静态档案文件名）
      "status":  "活跃" | "不活跃" | "未入档",
      "static":  "…静态档案正文…",
      "dynamic": "…动态档案正文…"（无则给出占位说明）,
      "note":    "深层记忆请自行调用 DB_query_tool 查询。"
    }
"""

from pathlib import Path
import re

from tools.world_threads import ACTIVE_DIR, INACTIVE_DIR

# 项目根：tools/ -> trpg-server/ -> trpg-project/
_ROOT = Path(__file__).resolve().parent.parent.parent
CHARACTER_DIR = _ROOT / "trpg-world" / "角色静态档案"

_NO_DYNAMIC = "（尚无动态档案：本局尚未接触过，或接触后未存档。）"
_NOTE = (
    "以上为静态正典 + 动态近记忆。若需该角色更早/更深的长期记忆，"
    "请自行调用 DB_query_tool（collection=char_memory, owner=该角色名）按需检索。"
)


def _strip_frontmatter(text: str) -> str:
    """去掉 YAML frontmatter（Obsidian 元数据），只留给模型看的正文。"""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2].lstrip("\n")
    return text


# 档案里标识本人物身份的字段行（如 "- **称号**：龙王刀"）
_IDENTITY_FIELD = re.compile(r"\*\*\s*(称号|绰号|别名|别称|又称)\s*\*\*")


def _iter_files() -> list[Path]:
    if not CHARACTER_DIR.is_dir():
        return []
    return [f for f in sorted(CHARACTER_DIR.glob("*.md"))
            if not f.stem.startswith("_")]  # 跳过模板/内部文件


def _read_raw(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _identity_hit(text: str, name: str) -> bool:
    """name 是否在该档案的‘身份标识’里（frontmatter description 或 称号/绰号 字段行）。"""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            for line in parts[1].splitlines():
                if line.strip().startswith("description") and name in line:
                    return True
            text = parts[2]
    return any(name in line and _IDENTITY_FIELD.search(line)
               for line in text.splitlines())


def _ambiguous(name: str, paths: list[Path]) -> dict:
    names = "、".join(p.stem for p in paths[:10])
    return {"success": False,
            "error": f"「{name}」匹配到多个人物：{names}；请用全名"}


def _resolve_static(name: str):
    """把 name（全名或绰号）解析到静态档案 Path。返回 (Path, None) 或 (None, 错误 dict)。

    优先级：文件名精确 > 文件名包含 > 身份标识 > 正文包含。
    """
    if not CHARACTER_DIR.is_dir():
        return None, {"success": False, "error": f"人物档案目录不存在：{CHARACTER_DIR}"}

    exact = CHARACTER_DIR / f"{name}.md"
    if exact.is_file():
        return exact, None

    files = _iter_files()
    # 1) 文件名包含（优先于正文，避免“提到某人”造成的噪声）
    stem_hits = [f for f in files if name in f.stem]
    if len(stem_hits) == 1:
        return stem_hits[0], None
    if len(stem_hits) > 1:
        return None, _ambiguous(name, stem_hits)

    # 2) 正文包含：先看‘身份标识’（称号/绰号/description），再看普通提及
    id_hits, other_hits = [], []
    for f in files:
        text = _read_raw(f)
        if name not in text:
            continue
        (id_hits if _identity_hit(text, name) else other_hits).append(f)
    for group in (id_hits, other_hits):
        if len(group) == 1:
            return group[0], None
        if len(group) > 1:
            return None, _ambiguous(name, group)

    return None, {"success": False, "error": f"没有找到人物档案：{name}"}


def _read(path: Path) -> str:
    try:
        return _strip_frontmatter(path.read_text(encoding="utf-8"))
    except OSError:
        return ""


def _resolve_dynamic_only(name: str):
    """静态档案没有时，在动态档案（活跃 > 不活跃）里找。

    优先文件名精确，其次文件名包含（唯一命中）。返回 (Path, status) 或 (None, None)。
    """
    for d, status in ((ACTIVE_DIR, "活跃"), (INACTIVE_DIR, "不活跃")):
        if (d / f"{name}.md").is_file():
            return d / f"{name}.md", status
    for d, status in ((ACTIVE_DIR, "活跃"), (INACTIVE_DIR, "不活跃")):
        if not d.is_dir():
            continue
        hits = [f for f in sorted(d.glob("*.md"))
                if not f.stem.startswith("_") and name in f.stem]
        if len(hits) == 1:
            return hits[0], status
    return None, None


def get_character(name: str) -> dict:
    """NPC 登场时读全其档案：静态正典 + 动态近记忆（不含 chroma 深层记忆）。

    每个角色地位平等：一经建档（存档时自动创建静态档案）即与预设角色同等对待。
    """
    if not name:
        return {"success": False, "error": "必须提供人物名"}

    static_path, err = _resolve_static(name)
    if err:
        # 安全网：静态档案缺失时退回动态档案（正常每个人物都有静态档案）
        if str(err.get("error", "")).startswith("没有找到"):
            dyn_path, status = _resolve_dynamic_only(name)
            if dyn_path is not None:
                return {
                    "success": True,
                    "name": dyn_path.stem,
                    "status": status,
                    "static": "（静态档案待补。）",
                    "dynamic": _read(dyn_path) or _NO_DYNAMIC,
                    "note": _NOTE,
                }
        return err
    canonical = static_path.stem

    # 动态：优先活跃，其次不活跃（已淘汰者）
    active_path = ACTIVE_DIR / f"{canonical}.md"
    inactive_path = INACTIVE_DIR / f"{canonical}.md"
    if active_path.is_file():
        status, dynamic = "活跃", _read(active_path)
    elif inactive_path.is_file():
        status, dynamic = "不活跃", _read(inactive_path)
    else:
        status, dynamic = "未入档", _NO_DYNAMIC

    return {
        "success": True,
        "name": canonical,
        "status": status,
        "static": _read(static_path),
        "dynamic": dynamic or _NO_DYNAMIC,
        "note": _NOTE,
    }
