# -*- coding: utf-8 -*-
"""
find_specific_character.py
==========================
读取人物的**静态档案**（给主持人演人用）。

正典：`trpg-world/角色静态档案/<人物名>.md`（55 个），带 YAML frontmatter。
对应 `主持人/总览.md` 铁律：「特定人物出场时先查人物设定」。

匹配规则：
    1. 文件名精确匹配（如「唐中翎」）；
    2. 否则退回"文件名包含 / 正文包含"（支持绰号，如「唐老魔」），
       唯一命中才采用；命中多个则报错要求用全名。

注：将来会升级为 `get_character(name)`，同时返回静态档案 +
`角色动态档案/活跃/<名>.md`（近记忆），见 ARCHITECTURE.md 第七节。
"""

from pathlib import Path

# 项目根：tools/ -> trpg-server/ -> trpg-project/（绝对路径，不依赖启动目录）
_ROOT = Path(__file__).resolve().parent.parent.parent
CHARACTER_DIR = _ROOT / "trpg-world" / "角色静态档案"


def _fuzzy_candidates(name: str) -> list[Path]:
    out = []
    for f in sorted(CHARACTER_DIR.glob("*.md")):
        if name in f.stem:
            out.append(f)
            continue
        try:
            if name in f.read_text(encoding="utf-8"):
                out.append(f)
        except OSError:
            continue
    return out


def _read(path: Path) -> dict:
    try:
        return {"success": True, "name": path.stem,
                "content": path.read_text(encoding="utf-8")}
    except OSError as e:
        return {"success": False, "error": f"读取档案失败：{e}"}


def find_specific_character(name: str) -> dict:
    """查看特定人物的人物档案。返回 {success, name, content}。"""
    if not CHARACTER_DIR.is_dir():
        return {"success": False, "error": f"人物档案目录不存在：{CHARACTER_DIR}"}
    if not name:
        return {"success": False, "error": "必须提供人物名"}

    exact = CHARACTER_DIR / f"{name}.md"
    if exact.is_file():
        return _read(exact)

    candidates = _fuzzy_candidates(name)
    if len(candidates) == 1:
        return _read(candidates[0])
    if len(candidates) > 1:
        names = "、".join(p.stem for p in candidates[:10])
        return {"success": False,
                "error": f"「{name}」匹配到多个人物：{names}；请用全名"}
    return {"success": False, "error": f"没有找到人物档案：{name}"}
