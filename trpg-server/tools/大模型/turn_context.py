# -*- coding: utf-8 -*-
"""turn_context.py
=================
「本轮上下文」标志：给**工具函数**读取（工具拿不到 session / 玩家输入）。

由 `main./action` 每轮设置一次：
    set_turn(raw, mode)

用途示例：
    - `modify_hunger` 正数（进食）时，检查玩家本轮是否真在「吃 / 喝」——
      点单 / 上菜 / 付钱不能加饥饿（防重复结算）。
"""

_current_action = ""
_current_mode = ""


def set_turn(action: str, mode: str = "action") -> None:
    global _current_action, _current_mode
    _current_action = action or ""
    _current_mode = mode or ""


def current_action() -> str:
    return _current_action


def current_mode() -> str:
    return _current_mode
