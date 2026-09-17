# -*- coding: utf-8 -*-
"""
macro_timeline.py
=================
宏观时间线：**只读剧本**（`trpg-world/世界推演/宏观时间线.json`），按当前游戏日切「时间窗」。

设计（单一真相源）：
    - 剧本文件是**唯一真相源**——**不拷进 `游戏数据/`**、不记「已触发」；
    - 「哪些已发生」= `date <= 今天`；「哪些是预兆」= `今天 < date <= 今天+N月`；
    - 每次注入上下文时**现读现切**（文件几十 KB，无需缓存/无需状态）。
      因此「放弃本轮」回滚时，宏观视图随游戏时钟自动回退，**无需任何标记**。

条目字段：`date` / `text` / `辐射范围` / `具体影响` / `江湖反应` / `GM叙事参考`。
窗口月份可用 `TRPG_STATE_WINDOW_MONTHS` 调（默认 3）。
"""

from __future__ import annotations

import calendar
import datetime
import json
import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
TIMELINE_FILE = _ROOT / "trpg-world" / "世界推演" / "宏观时间线.json"

#: 注入给大模型的窗口：当前游戏日 前/后 各 N 个月
WINDOW_MONTHS = int(os.environ.get("TRPG_STATE_WINDOW_MONTHS", "3"))


def _parse(s):
    try:
        y, m, d = (int(x) for x in str(s).split("-"))
        return datetime.date(y, m, d)
    except (ValueError, TypeError):
        return None


def add_months(date: str, n: int) -> str:
    """日期加减 n 个月（日号超界时夹到当月最后一天；无法解析返回空串）。"""
    d = _parse(date)
    if d is None:
        return ""
    total = d.year * 12 + (d.month - 1) + n
    y, m = divmod(total, 12)
    m += 1
    last = calendar.monthrange(y, m)[1]
    return datetime.date(y, m, min(d.day, last)).strftime("%Y-%m-%d")


def load() -> list[dict]:
    """读整个剧本（无法解析返回空列表）。"""
    try:
        raw = json.loads(TIMELINE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [e for e in raw if isinstance(e, dict)] if isinstance(raw, list) else []


def view(today: str, window_months: int = None) -> dict:
    """按当前游戏日切窗口，返回 `{"宏观": [...], "预兆": [...]}`。

    - `宏观`：`[今天−N月, 今天]` 内**已发生**的大事；
    - `预兆`：`(今天, 今天+N月]` 内**将发生**的（仅供铺垫）。
    - `today` 为空 → 两边都返回空（宁可少给，不泄漏未来）。
    """
    n = WINDOW_MONTHS if window_months is None else int(window_months)
    if not today:
        return {"宏观": [], "预兆": []}
    lo, hi = add_months(today, -n), add_months(today, n)
    entries = load()
    macro, upcoming = [], []
    for e in entries:
        d = str(e.get("date", ""))
        if not d:
            continue
        if lo <= d <= today:
            macro.append(e)
        elif today < d <= hi:
            upcoming.append(e)
    return {"宏观": macro, "预兆": upcoming}
