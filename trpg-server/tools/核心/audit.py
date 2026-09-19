# -*- coding: utf-8 -*-
"""
audit.py
========
轻量审计日志：写到 `trpg-server/sessions/audit.log`（UTF-8），同时尽量打印到控制台。

用途：给「存档蒸馏」这种长时间、多轮的流程留下可事后查看的轨迹——
哪一轮 LLM、耗时多少、prompt 多大、执行了哪些工具、哪个工具卡住。

（`sessions/` 在 .gitignore 里，日志不会被提交。）
"""

from __future__ import annotations

import time
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent.parent / "sessions" / "audit.log"
_MAX = 1024 * 1024   # 超过 1MB 就清空重来


def log(msg: str, tag: str = "save") -> None:
    line = f"{time.strftime('%m-%d %H:%M:%S')} [{tag}] {msg}"
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        if LOG.exists() and LOG.stat().st_size > _MAX:
            LOG.write_text("", encoding="utf-8")
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    # 控制台：Windows 是 GBK，非 GBK 字符可能报错 → 兜底成 ASCII
    try:
        print(line)
    except Exception:
        try:
            print(line.encode("ascii", "replace").decode("ascii"))
        except Exception:
            pass


def read_tail(n: int = 100) -> list[str]:
    """末尾 n 行（供诊断脚本读）。"""
    try:
        lines = LOG.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return lines[-n:]
