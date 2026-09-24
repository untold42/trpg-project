# -*- coding: utf-8 -*-
"""
context_dump.py
===============
把**真实发给大模型**的上下文原样落盘，供 `context_lens.py` 事后分析。

由 `llm.send_messages()` 在发请求**之前**调用。开关是环境变量 `TRPG_DUMP_CONTEXT=1`
（默认关）——不开就只是一次布尔判断，不影响游戏。

落盘：`trpg-server/sessions/context_dump/<序号>-<月日-时分秒>.json`
每个文件 = 那一轮**原样**的 `messages` + `tools`，不做任何增删。

约定：
  - 只读、只写自己的目录，**不碰游戏状态**；
  - 任何异常一律吞掉：分析工具绝不能弄坏游戏。
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

#: 开关：`TRPG_DUMP_CONTEXT=1` 才落盘（写 `.env` 或环境变量都行）
#: 每次调用现读，而不是 import 时定死——这样 `load_dotenv()` 之后才生效的 `.env` 也能用。
_FLAG = "TRPG_DUMP_CONTEXT"

DIR = Path(__file__).resolve().parent.parent.parent / "sessions" / "context_dump"

_lock = threading.Lock()
_seq = 0


def enabled() -> bool:
    return os.environ.get(_FLAG, "0").strip().lower() not in ("", "0", "false", "no")


def _chars(messages) -> int:
    """正文字符数（只数 role/content/tool_calls，不数 JSON 引号括号）。"""
    total = 0
    for m in messages or []:
        content = m.get("content")
        if isinstance(content, str):
            total += len(content)
        elif content:
            total += len(json.dumps(content, ensure_ascii=False, default=str))
        for call in m.get("tool_calls") or []:
            total += len(json.dumps(call, ensure_ascii=False, default=str))
    return total


def _dump_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def dump(messages, tools=None, model: str = "") -> None:
    """把这一轮的 messages / tools 原样写一份。失败静默（绝不影响游戏）。"""
    if not enabled():
        return
    global _seq
    try:
        with _lock:
            _seq += 1
            seq = _seq
        tools = list(tools or [])
        record = {
            "序号": seq,
            "时间": time.strftime("%Y-%m-%d %H:%M:%S"),
            "模型": model,
            "消息条数": len(messages or []),
            "正文字符数": _chars(messages),
            "工具": [(t.get("function") or {}).get("name") for t in tools],
            "工具字符数": len(_dump_json(tools)),
            "messages": messages,
            "tools": tools,
        }
        DIR.mkdir(parents=True, exist_ok=True)
        path = DIR / f"{seq:04d}-{time.strftime('%m%d-%H%M%S')}.json"
        path.write_text(_dump_json(record), encoding="utf-8")
    except Exception:
        pass
