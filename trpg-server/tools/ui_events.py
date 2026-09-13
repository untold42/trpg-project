# -*- coding: utf-8 -*-
"""
ui_events.py
============
工具 → 前端的 UI 事件旁路。

背景：`collapse` 之后工具中间消息不会进入最终回复，工具做的「要给用户看的事」
（切背景、放音乐、开小游戏）传不出去。这里给工具一个统一的出口：

    from tools.ui_events import ui_event

    def some_tool(...):
        return {
            "success": True,
            "message": "...",
            UI_EVENTS_KEY: [ui_event("music", track="市井")],
        }

引擎（engine.TurnRunner）会：
    1. 从工具结果里取出 UI_EVENTS_KEY 下的事件，收集成 UI 事件流；
    2. 把该字段从发给 LLM 的工具结果里剥离（LLM 不需要看到它）；
    3. 最终返回：UI 事件 + LLM 的叙事指令。

事件统一形状（与前端 types/gametype.ts 对齐）：
    {"type": "ui", "kind": <str>, "data": {...}}
"""

UI_EVENTS_KEY = "_ui_events"


def ui_event(kind: str, **data) -> dict:
    """构造一条 UI 事件。kind 例：bg / music / minigame / ..."""
    return {"type": "ui", "kind": kind, "data": data}
