# -*- coding: utf-8 -*-
"""
world_state.py
==============
世界状态（live，结构化）：推演游标 + 宏观 + 定时线 + 人物线程。

存放：`游戏数据/世界状态.json`（经 state_manager 读写）
    ⇒ 因而自动进入「状态现拼」，大模型每轮都能看到最新世界状态；
    ⇒ 也自动进入开局快照，`放弃本轮` 时随玩家状态一起回滚。

活跃人物：扫 `trpg-world/角色动态档案/活跃/*.md`（谁在那，就该被推演）。

结构：
    {
      "模拟游标": "1220-01-16",           # 已推演到哪一天
      "宏观":    [ {date, entity, text} ], # 已发生的宏观事件
      "定时线":  [ {date, text, 已触发} ],  # 作者给定，代码按日期触发
      "人物线程": {
         "上官萤": { "地点":"福州",
                     "最新": {日期,类型,顺利度},
                     "流水": [ {日期,类型,顺利度}, ... ] }   # 上限截断
      }
    }
"""

import datetime
from pathlib import Path

from tools.state_manager import state

_ROOT = Path(__file__).resolve().parent.parent.parent
STATIC_DIR = _ROOT / "trpg-world" / "角色静态档案"
ACTIVE_DIR = _ROOT / "trpg-world" / "角色动态档案" / "活跃"
INACTIVE_DIR = _ROOT / "trpg-world" / "角色动态档案" / "不活跃"

# 每人保留的逐日流水上限
THREAD_LOG_LIMIT = 5


def default() -> dict:
    """一份全新的空世界状态（纯函数，不碰文件）。"""
    return {"模拟游标": "", "宏观": [], "定时线": [], "人物线程": {}}


def load() -> dict:
    data = state.load("世界状态", {})
    if not isinstance(data, dict):
        data = {}
    for k, v in default().items():
        data.setdefault(k, v)
    return data


def save(data: dict):
    state.save("世界状态", data)


def cursor() -> str:
    return load().get("模拟游标", "")


def set_cursor(date: str):
    data = load()
    data["模拟游标"] = date
    save(data)


def parse_date(s):
    try:
        y, m, d = (int(x) for x in str(s).split("-"))
        return datetime.date(y, m, d)
    except (ValueError, TypeError):
        return None


def days_between(start: str, end: str) -> int:
    """end - start 的天数（无法解析返回 0）。"""
    a, b = parse_date(start), parse_date(end)
    if a is None or b is None:
        return 0
    return (b - a).days


def day_after(date: str) -> str:
    d = parse_date(date)
    return (d + datetime.timedelta(days=1)).strftime("%Y-%m-%d") if d else date


def day_before(date: str, n: int = 1) -> str:
    d = parse_date(date)
    return (d - datetime.timedelta(days=n)).strftime("%Y-%m-%d") if d else date


def current_date() -> str:
    """玩家当前游戏内日期（读 基本信息.json）。"""
    t = (state.load("基本信息", {}) or {}).get("时间", {}) or {}
    return t.get("日期", "") or ""


def current_location() -> str:
    """玩家当前地点（读 基本信息.json）。"""
    p = (state.load("基本信息", {}) or {}).get("位置", {}) or {}
    return p.get("地点", "") or ""


def current_region() -> str:
    """玩家当前区域/城（读 基本信息.json 的位置.区域）。"""
    p = (state.load("基本信息", {}) or {}).get("位置", {}) or {}
    return p.get("区域", "") or ""


def active_characters() -> list[str]:
    """活跃人物名单：扫 角色动态档案/活跃/ 下的 md，取文件名（人物名）。"""
    if not ACTIVE_DIR.is_dir():
        return []
    return sorted(p.stem for p in ACTIVE_DIR.glob("*.md") if not p.stem.startswith("_"))


# ---- 活跃名单的写入（存档管线调用；见 save_pipeline.contacted_characters）----
def active_path(name: str) -> Path:
    return ACTIVE_DIR / f"{name}.md"


def inactive_path(name: str) -> Path:
    return INACTIVE_DIR / f"{name}.md"


def append_active_line(name: str, line: str):
    """给 活跃/<名>.md 追加一行近记忆（文件不存在则先建头）。"""
    ACTIVE_DIR.mkdir(parents=True, exist_ok=True)
    path = active_path(name)
    if not path.exists():
        path.write_text(f"# {name}（活跃）\n", encoding="utf-8")
    with open(path, "a", encoding="utf-8") as f:
        f.write(line if line.endswith("\n") else line + "\n")


def promote_active(name: str, date: str = "", note: str = "玩家接触",
                   memory_lines: list | None = None) -> bool:
    """把人物加入活跃名单（世界推演只扫这个目录）。

    - `活跃/<名>.md` 不存在 → 创建；若曾落到 `不活跃/` 则连同旧近记忆迁移回来。
      新建时把本局蒸馏出的近记忆（`memory_lines`：[{time, kind, content}]）写进文件。
    - 已存在 → 什么都不做（避免重复 / 覆盖）。

    返回 True 表示本次发生了变化（新建或迁移）。
    """
    if not name:
        return False
    ACTIVE_DIR.mkdir(parents=True, exist_ok=True)
    path = active_path(name)
    if path.exists():
        return False

    inactive = inactive_path(name)
    body = None
    if inactive.is_file():
        try:
            body = inactive.read_text(encoding="utf-8")
        except OSError:
            body = None
        try:
            inactive.unlink()
        except OSError:
            pass

    if body is None:
        lines = [f"# {name}（活跃）\n"]
        if note:
            lines.append(f"\n- {date} {note}".rstrip() + "\n")
        if memory_lines:
            lines.append("\n## 近记忆\n")
            for m in memory_lines:
                t = f"{m.get('time', '')} ".lstrip()
                kind = f"[{m['kind']}] " if m.get("kind") else ""
                lines.append(f"- {t}{kind}{m.get('content', '')}\n")
        path.write_text("".join(lines), encoding="utf-8")
    else:
        path.write_text(body, encoding="utf-8")
        if note:
            append_active_line(name, f"- {date} {note}".strip())
    return True


def character_thread(name: str) -> dict:
    return load().get("人物线程", {}).get(name, {})


def update_character(name: str, date: str, location: str, kind: str,
                     smoothness: str, note: str = "", include: bool = True):
    """写入某人物当天的推演结果（最新 + 流水，流水按上限截断）。

    - `include`：小模型给出的「是否纳入大模型上下文」（依据离玩家远近）。
      只影响 `context_view()` 的注入裁剪，**不影响存储**（存档仍是全量）。
    - 每条流水也记 `地点`（此前只存顶层最新地点，导致地点历史丢失）。
    """
    def _mutate(data):
        if not isinstance(data, dict):
            data = default()
        threads = data.setdefault("人物线程", {})
        th = threads.setdefault(name, {})
        th["地点"] = location
        entry = {"日期": date, "地点": location, "类型": kind,
                 "顺利度": smoothness, "纳入上下文": bool(include)}
        if note:
            entry["备注"] = note
        th["最新"] = entry
        log = th.setdefault("流水", [])
        log.append(entry)
        if len(log) > THREAD_LOG_LIMIT:
            del log[: len(log) - THREAD_LOG_LIMIT]
        return data

    state.update("世界状态", _mutate)


def context_view() -> dict:
    """给大模型的**裁剪视图**（只用于注入上下文，不改存储）。

    - `人物线程`：只保留「纳入上下文」为真的流水条目；某人物若全被裁掉则不出现。
    - `宏观` / `定时线` / `模拟游标`：不裁（一局至多一个游戏月，体量可控）。
    """
    data = load()
    threads = {}
    for name, th in (data.get("人物线程") or {}).items():
        if not isinstance(th, dict):
            continue
        log = [e for e in (th.get("流水") or []) if e.get("纳入上下文", True)]
        if not log:
            continue
        threads[name] = {
            "地点": log[-1].get("地点", th.get("地点", "")),
            "最新": log[-1],
            "流水": log,
        }
    return {
        "模拟游标": data.get("模拟游标", ""),
        "宏观": data.get("宏观", []),
        "定时线": data.get("定时线", []),
        "人物线程": threads,
    }
