# -*- coding: utf-8 -*-
"""
world_threads.py
================
世界线程（live）：小模型推演的 **NPC 人物线程**。

存放：`游戏数据/世界线程.json`（经 state_manager 读写）
    ⇒ 因而自动进入「状态现拼」，大模型每轮都能看到最新线程；
    ⇒ 也自动进入开局快照，`放弃本轮` 时随玩家状态一起回滚。

结构：
    {
      "模拟游标": "1220-01-17",             # 世界推演已推到哪一天（bookkeeping，不注入）
      "人物线程": {
         "温夫人": { "地点":"君山",
                     "最新": {日期,地点,类型,顺利度,纳入上下文},
                     "流水": [ {日期,地点,类型,顺利度,纳入上下文}, ... ] }   # 上限截断
      }
    }

⚠️ **宏观时间线不在这里**：宏观事件是「只读剧本 + 按当前日期切窗口」，
   见 `tools/macro_timeline.py`（不拷贝、不记「已触发」）。

活跃人物：扫 `trpg-world/角色动态档案/活跃/*.md`（谁在那，就该被推演）。
"""

from __future__ import annotations

import datetime
from pathlib import Path

from tools.state_manager import state

STATE_KEY = "世界线程"

_ROOT = Path(__file__).resolve().parent.parent.parent
STATIC_DIR = _ROOT / "trpg-world" / "角色静态档案"
ACTIVE_DIR = _ROOT / "trpg-world" / "角色动态档案" / "活跃"
INACTIVE_DIR = _ROOT / "trpg-world" / "角色动态档案" / "不活跃"

# 每人保留的逐日流水上限
THREAD_LOG_LIMIT = 5


def default() -> dict:
    """一份全新的空世界线程（纯函数，不碰文件）。"""
    return {"模拟游标": "", "人物线程": {}}


def load() -> dict:
    data = state.load(STATE_KEY, {})
    if not isinstance(data, dict):
        data = {}
    for k, v in default().items():
        data.setdefault(k, v)
    return data


def save(data: dict):
    state.save(STATE_KEY, data)


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
      只影响 `threads_view()` 的注入裁剪，**不影响存储**（存档仍是全量）。
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

    state.update(STATE_KEY, _mutate)


def threads_view() -> dict:
    """给大模型的**注入视图**：只保留「纳入上下文」为真的流水条目。

    某人物若全被裁掉则不出现；**不注入 `模拟游标`**（bookkeeping）。
    存储始终全量（`世界线程.json` 不动）。
    """
    data = load()
    out = {}
    for name, th in (data.get("人物线程") or {}).items():
        if not isinstance(th, dict):
            continue
        log = [e for e in (th.get("流水") or []) if e.get("纳入上下文", True)]
        if not log:
            continue
        out[name] = {
            "地点": log[-1].get("地点", th.get("地点", "")),
            "最新": log[-1],
            "流水": log,
        }
    return out
