# -*- coding: utf-8 -*-
"""
two_gm.py
=========
双 GM 拆分（叙事 GM / 工具 GM）的**配置 + 工具意图日志**。

设计：`trpg-server/文档/设计-双GM拆分.md`。

三种模式（`配置/双GM.json`，热改免重启）：
    ┌ 启用=false, 记录工具意图=false  → 现状：单 GM、全 26 工具、照常落地（默认）
    ├ 启用=false, 记录工具意图=true   → **影子**：叙事GM 额外写 tool 意图并落日志，工具照常执行（评估用）
    └ 启用=true                      → 叙事GM 只用 6 个只读工具 + 写 tool 意图（需配合工具GM worker）

日志：`sessions/工具意图.jsonl`，一行一轮：`{ts, game_time, mode, intents:[...]}`
"""

from __future__ import annotations

import json
import time
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_FILE = SERVER_DIR / "配置" / "双GM.json"
LOG_FILE = SERVER_DIR / "sessions" / "工具意图.jsonl"

_DEFAULT = {
    "启用": False,
    "记录工具意图": False,
    "工具GM": {
        "base_url": "http://127.0.0.1:8317/v1",
        "api_key": "",
        "model": "gpt-6-luna",
        "reasoning_effort": "high",
    },
    "重试": 3,
}

_cache: dict = {}


def config() -> dict:
    """读 `配置/双GM.json`（按 mtime 缓存）。热改免重启。"""
    try:
        m = CONFIG_FILE.stat().st_mtime
    except OSError:
        return dict(_DEFAULT)
    if _cache.get("m") == m:
        return _cache["v"]
    cfg = dict(_DEFAULT)
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            for k in _DEFAULT:
                if k in raw:
                    cfg[k] = raw[k]
    except (OSError, json.JSONDecodeError):
        pass
    _cache["m"], _cache["v"] = m, cfg
    return cfg


def enabled() -> bool:
    """是否切到「叙事GM 只读」模式（启用=true）。"""
    return bool(config().get("启用"))


def recording() -> bool:
    """是否记录工具意图（启用=true 或 记录工具意图=true）。"""
    c = config()
    return bool(c.get("启用") or c.get("记录工具意图"))


def record_intents(mode: str, intents: list, game_time: str = "") -> None:
    """把一轮的 tool 意图追加进日志（intents 形如 `{"type":"tool","content":[...]}`）。"""
    lines: list[str] = []
    for it in intents or []:
        c = it.get("content") if isinstance(it, dict) else None
        if isinstance(c, list):
            lines.extend(str(x) for x in c if str(x).strip())
        elif isinstance(c, str) and c.strip():
            lines.append(c.strip())
    if not lines:
        return
    rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "game_time": game_time,
           "mode": mode, "intents": lines}
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def recent(n: int = 20) -> list[dict]:
    """读最近 n 条工具意图（供探针 / 日志面板）。"""
    try:
        lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for ln in lines[-n:]:
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out
