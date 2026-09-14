# -*- coding: utf-8 -*-
"""
character_archive.py
====================
角色**动态档案**（近记忆 · 热）的写入工具 + LRU 淘汰。

设计（ARCHITECTURE.md 第三节）：
    热：`trpg-world/角色动态档案/活跃/<名>.md`（模板 §9–§13）——每局存档时更新
    冷：chroma `char_memory`——**只在动态档案溢出时**由 LRU 淘汰写入

存档专用：`update_character_archive(...)` 由存档蒸馏回合调用（见 存档流程.md），
把某 NPC 的里程碑 / 情感记忆 / 当前情绪 / 信息边界写进其动态档案；
首次登场可带 `static` 字段，顺带建一份静态档案（§1–§8）。

LRU：§10「情感记忆」表超过 `NEAR_MEMORY_LIMIT` 行 → 把最旧的溢出行写入
`char_memory[owner]`（淘汰即遗忘，遗忘即潜意识），写入成功才从档案移除。
"""

from __future__ import annotations

import re
from pathlib import Path

from tools.world_state import ACTIVE_DIR, INACTIVE_DIR, STATIC_DIR

#: §10 情感记忆每个角色保留的最大行数（超出淘汰最旧）
NEAR_MEMORY_LIMIT = 20


# ------------------------------------------------------------
# 模板脚手架
# ------------------------------------------------------------
def _dynamic_scaffold(name: str) -> str:
    return f"""# {name}（活跃）

## 9. 与梁峰关系

### 里程碑

| 时间 | 事件 |
|:----|:-----|

### 最近互动

（尚无）

### 态度

（尚无）

---

## 10. 情感记忆

| 日期·事件 | 她的感受 |
|-----------|---------|

---

## 11. 当前情绪状态

| 字段 | 值 |
|------|-----|
| 主要情绪 | （尚无） |
| 强度 | /10 |
| 触发源 | （尚无） |
| 距今 | （尚无） |

**行为表现：**

**想要什么：**

**挥发性：**

---

## 12. 信息边界

**已知：**

**不知：**

**态度：**

---

## 附 · 世界推演流水（可选 · 本项目机制）

"""


def _slug(name: str) -> str:
    return "char-" + re.sub(r"\s+", "-", name.strip())


def _ensure_static(name: str, fields: dict | None = None) -> Path:
    """静态档案不存在则新建（按静态模板 §1–§8 渲染；缺的填「待补」）。返回路径。"""
    path = STATIC_DIR / f"{name}.md"
    if path.exists():
        return path
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    f = fields or {}

    def g(*keys):
        for k in keys:
            if f.get(k):
                return str(f[k]).strip()
        return ""

    desc = g("身份", "description") or "（待补）"
    lines = [
        "---",
        f"name: {_slug(name)}",
        f"description: {name}——{desc}",
        "metadata:",
        "  node_type: memory",
        "  type: reference",
        "---",
        "",
        f"# {name}",
        "",
        "## 1. 基本档案",
        "",
    ]
    for label in ("全名", "年纪", "籍贯", "外貌", "身份"):
        lines.append(f"- **{label}**：{f.get(label) or '（待补）'}")
    for num, title, val in (
        ("2", "说话方式", g("说话方式", "声音底色")),
        ("3", "性格", g("性格")),
        ("4", "技能", g("技能")),
        ("5", "身世", g("身世")),
    ):
        lines += ["", f"## {num}. {title}", "", val or "（待补）"]
    lines += [
        "", "## 6. 内心（长期）", "",
        "### 长期想要什么", "", g("长期想要", "想要") or "（待补）", "",
        "### 长期怕什么", "", g("长期怕", "怕") or "（待补）",
    ]
    lines += ["", "## 7. 日常习惯", "", g("日常习惯", "习惯") or "（待补）"]
    lines += ["", "## 8. 关系网", "", g("关系网") or "（待补）"]
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


def ensure_static(name: str, fields: dict | None = None) -> str:
    """公开入口：确保某人物有静态档案（不存在则建）。返回路径字符串。"""
    return str(_ensure_static(name, fields))


def _ensure_dynamic(name: str) -> Path:
    for d in (ACTIVE_DIR, INACTIVE_DIR):
        p = d / f"{name}.md"
        if p.is_file():
            return p
    ACTIVE_DIR.mkdir(parents=True, exist_ok=True)
    path = ACTIVE_DIR / f"{name}.md"
    path.write_text(_dynamic_scaffold(name), encoding="utf-8")
    return path


# ------------------------------------------------------------
# markdown 分节工具
# ------------------------------------------------------------
def _split(text: str):
    """按 `## ` 二级标题切分：[(header, body)]，第 0 项 header 为 ''（前导）。"""
    parts = re.split(r"(?m)^(## .*)$", text)
    out = [("", parts[0])]
    for i in range(1, len(parts), 2):
        out.append((parts[i], parts[i + 1] if i + 1 < len(parts) else ""))
    return out


def _join(parts) -> str:
    return "".join(h + b for h, b in parts)


def _find(parts, prefix: str) -> int:
    for i, (h, _) in enumerate(parts):
        if h.startswith(prefix):
            return i
    return -1


def _empty_row(line: str) -> bool:
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return all(c == "" for c in cells)


def _table_append(body: str, row: str) -> str:
    """把 row 追加到 body 里最后一个表格末尾（占位空行则替换）。"""
    lines = body.rstrip("\n").split("\n")
    idx = [i for i, l in enumerate(lines) if l.strip().startswith("|")]
    if not idx:
        return body.rstrip("\n") + "\n\n" + row + "\n"
    last = idx[-1]
    if _empty_row(lines[last]):
        lines[last] = row
    else:
        lines.insert(last + 1, row)
    return "\n".join(lines) + "\n\n"


def _get_subsection(body: str, title: str) -> str:
    """取 `### title` 到下一个 `###`/`---`/结尾之间的文本。"""
    m = re.search(rf"(?ms)^###\s*{re.escape(title)}\s*$(.*?)(?=^###\s|^---|\Z)", body)
    return m.group(1).strip() if m else ""


def _set_subsection(body: str, title: str, new_text: str) -> str:
    pat = re.compile(rf"(?ms)(^###\s*{re.escape(title)}\s*$)(.*?)(?=^###\s|^---|\Z)")
    block = f"### {title}\n\n{new_text.strip()}\n\n"
    if pat.search(body):
        return pat.sub(lambda m: block, body, count=1)
    return body.rstrip("\n") + "\n\n" + block


# ------------------------------------------------------------
# 写入
# ------------------------------------------------------------
def update_character_archive(
    name: str,
    static: dict | None = None,
    milestone: dict | None = None,
    feeling: dict | None = None,
    recent: str | None = None,
    attitude: str | None = None,
    emotion: dict | None = None,
    behaviors: list | None = None,
    want: str | None = None,
    volatility: str | None = None,
    known: list | None = None,
    unknown: list | None = None,
    info_attitude: str | None = None,
) -> dict:
    """更新某 NPC 的动态档案（存档蒸馏专用）。所有字段可选，按需更新。

    **静态 / 动态的判定（先查静态档案）**：
      - 静态档案**已存在**（老角色）→ 只更新**动态**档案（静态正典不覆盖）；
      - 静态档案**不存在**（新角色）→ 用 `static` 字段建**静态**档案，并建**动态**档案。
    动态档案若不存在（如从未接触过的预设角色）也会按模板新建。

    - `static`：新角色的静态字段（§1–§8）；已有静态档案时忽略；
    - `milestone`：`{time, event}` → §9 里程碑追加一行；
    - `feeling`：`{time, event, feeling}` → §10 情感记忆追加一行（触发 LRU）；
    - `recent` / `attitude`：覆写 §9 的「最近互动」/「态度」；
    - `emotion`：`{主要情绪, 强度, 触发源, 距今}` + `behaviors` / `want` / `volatility` → 覆写 §11；
    - `known` / `unknown` / `info_attitude` → 覆写 §12。
    """
    name = (name or "").strip()
    if not name:
        return {"success": False, "error": "必须提供人物名"}

    # 先查静态档案：有 → 老角色，只更新动态；无 → 新角色，静态 + 动态都建
    static_file = STATIC_DIR / f"{name}.md"
    new_character = not static_file.is_file()
    static_path = _ensure_static(name, static) if new_character else static_file
    path = _ensure_dynamic(name)
    parts = _split(path.read_text(encoding="utf-8"))

    # §9
    i9 = _find(parts, "## 9.")
    if i9 >= 0:
        h, body = parts[i9]
        if milestone and (milestone.get("event") or milestone.get("time")):
            row = f"| {milestone.get('time', '')} | {milestone.get('event', '')} |"
            body = _table_append(body, row)
        if recent:
            prev = _get_subsection(body, "最近互动")
            new = recent.strip() if prev in ("", "（尚无）") else prev + "\n\n" + recent.strip()
            body = _set_subsection(body, "最近互动", new)
        if attitude:
            body = _set_subsection(body, "态度", attitude)
        parts[i9] = (h, body)

    # §10
    i10 = _find(parts, "## 10.")
    if i10 >= 0 and feeling:
        h, body = parts[i10]
        fe = (feeling.get("event") or "").strip()
        fd = (feeling.get("time") or "").strip()
        label = f"{fd}·{fe}".strip("·") if (fd or fe) else ""
        row = f"| {label} | {feeling.get('feeling', '')} |"
        body = _table_append(body, row)
        parts[i10] = (h, body)

    # §11
    i11 = _find(parts, "## 11.")
    if i11 >= 0 and (emotion or behaviors or want or volatility):
        h, body = parts[i11]
        em = emotion or {}
        header = (
            "\n\n| 字段 | 值 |\n|------|-----|\n"
            f"| 主要情绪 | {em.get('主要情绪', '（尚无）')} |\n"
            f"| 强度 | {em.get('强度', '')}/10 |\n"
            f"| 触发源 | {em.get('触发源', '（尚无）')} |\n"
            f"| 距今 | {em.get('距今', '（尚无）')} |\n\n"
        )
        if behaviors is not None:
            header += "**行为表现：**\n" + "".join(f"- {b}\n" for b in behaviors) + "\n"
        if want is not None:
            header += f"**想要什么：** {want}\n\n"
        if volatility is not None:
            header += f"**挥发性：** {volatility}\n\n"
        header += "---\n"
        parts[i11] = (h, header)

    # §12
    i12 = _find(parts, "## 12.")
    if i12 >= 0 and (known is not None or unknown is not None or info_attitude is not None):
        h, body = parts[i12]
        txt = "\n\n"
        txt += "**已知：** " + "；".join(known) + "\n\n" if known is not None else ""
        txt += "**不知：** " + "；".join(unknown) + "\n\n" if unknown is not None else ""
        txt += "**态度：** " + info_attitude + "\n\n" if info_attitude is not None else ""
        txt += "---\n"
        parts[i12] = (h, txt)

    path.write_text(_join(parts), encoding="utf-8")

    evicted = _evict_overflow(name, path)
    return {"success": True, "name": name, "path": str(path),
            "static": str(static_path), "new_character": new_character,
            "evicted": evicted}


# ------------------------------------------------------------
# LRU：§10 溢出 → char_memory
# ------------------------------------------------------------
def _feelings_rows(body: str) -> list[str]:
    rows = []
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("|") and not _empty_row(s) and set(s) - set("|-: "):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if cells and cells[0] not in ("日期·事件",):  # 跳过表头
                rows.append(s)
    return rows


def _evict_overflow(name: str, path: Path) -> int:
    """§10 情感记忆超过 NEAR_MEMORY_LIMIT → 最旧的写入 char_memory 后移除。"""
    parts = _split(path.read_text(encoding="utf-8"))
    i10 = _find(parts, "## 10.")
    if i10 < 0:
        return 0
    h, body = parts[i10]
    rows = _feelings_rows(body)
    if len(rows) <= NEAR_MEMORY_LIMIT:
        return 0

    overflow = rows[: len(rows) - NEAR_MEMORY_LIMIT]

    def cell(row, i):
        cells = [c.strip() for c in row.strip("|").split("|")]
        return cells[i] if i < len(cells) else ""

    written = []
    for row in overflow:
        try:
            from tools import DB
            from tools.mem_store import CHAR
            res = DB.DB_add_and_update_tool(
                operation="add", collection=CHAR,
                content=f"{name}（情感记忆）{cell(row, 0)}：{cell(row, 1)}",
                time=cell(row, 0)[:10] or None, owner=name, kind="feeling",
            )
            if isinstance(res, dict) and res.get("success"):
                written.append(row)
        except Exception:
            break  # chroma 不可用 → 不淘汰（宁可不删，不丢记忆）

    if not written:
        return 0
    # 从档案里移除已成功淘汰的行
    new_body = body
    for row in written:
        new_body = new_body.replace(row + "\n", "", 1)
    parts[i10] = (h, new_body)
    path.write_text(_join(parts), encoding="utf-8")
    return len(written)
