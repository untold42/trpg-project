# -*- coding: utf-8 -*-
"""
push.py
=======
「后端主动发起的 GM 回合」的**推送达递队列**（新范式：server → GM push）。

背景：
    某些事情由**世界/后台**在玩家没输入时发生（最典型：异步生成的画作完成了）。
    后端这时要主动跑一个 GM 回合，把结果演给玩家看——但前端是**拉取式**的
    `/action` 请求-应答，没有推送通道。所以：push 回合的事件流先入本队列，
    前端轮询 `GET /pending` 取走。

与前端的契约：
    `GET /pending` → `{"events": [<统一事件流>], "作画中": [...]}`
    events 与 `/action` 返回**同构**（chat / narration / ui），前端按同一套渲染。
"""

import threading
from collections import deque

_queue: deque = deque(maxlen=64)
_lock = threading.Lock()


def push(events) -> None:
    """把一次 push 回合的完整事件流压入队列（线程安全）。"""
    evs = [e for e in (events or []) if isinstance(e, dict)]
    if not evs:
        return
    with _lock:
        _queue.append(evs)


def drain() -> list:
    """取走并清空所有待送事件（**展平**成一个统一事件流返回）。"""
    with _lock:
        out: list = []
        while _queue:
            out.extend(_queue.popleft())
    return out


def pending_count() -> int:
    with _lock:
        return len(_queue)


def clear() -> None:
    """丢弃所有待推送事件（放弃本轮/回溯时用）。"""
    with _lock:
        _queue.clear()
