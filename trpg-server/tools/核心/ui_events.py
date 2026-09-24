# -*- coding: utf-8 -*-
"""
ui_events.py
============
工具 → 前端的 UI 事件旁路。

背景：`collapse` 之后工具中间消息不会进入最终回复，工具做的「要给用户看的事」
（切背景、放音乐、开小游戏）传不出去。这里给工具一个统一的出口：

    from tools.核心.ui_events import ui_event

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

kind 清单（协议）：
    bg        data: {position: 场景名, time: 时辰}   切背景
    music     data: {track: 曲名}                    切/停背景音乐
    battle    data: {...}                            开战斗（战棋）
    mode      data: {mode: "explore"|"narrative"}     切换游戏模式（探索 / 叙事）
    minigame  data: {game, sessionId, ...}           开小游戏（可阻塞叙事，预留）
    quest     data: {动作: "新增"|"推进"|"完成"|"过期", 任务: {...}, ...}  任务栏刷新
"""

UI_EVENTS_KEY = "_ui_events"

#: 已定义的 UI 事件 kind（新增 kind 请同时改前端 types/gametype.ts）
KINDS = ("bg", "music", "battle", "mode", "minigame", "quest")


def ui_event(kind: str, **data) -> dict:
    """构造一条 UI 事件。kind 见 KINDS。"""
    return {"type": "ui", "kind": kind, "data": data}


def bg_event(position: str, time: str) -> dict:
    """切背景：position = 前端 背景/ 下的场景名；time = 十二时辰。"""
    return ui_event("bg", position=position, time=time)


def music_event(track: str) -> dict:
    """切背景音乐：track = 前端 音乐/ 下的曲名（不含扩展名）。"""
    return ui_event("music", track=track)


def mode_event(mode: str) -> dict:
    """切换游戏模式：mode = "explore"（大地图）| "narrative"（对话/立绘）。

    战斗不用本事件（走 `kind:"battle"`）。
    """
    return ui_event("mode", mode=mode)
