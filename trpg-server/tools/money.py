# -*- coding: utf-8 -*-
"""
money.py
========
金钱：**直接落账**。

    - `modify_money(...)` 直接改动 `游戏数据/金钱.json`；
    - 余额不足则整笔拒绝（不产生任何变动）。
"""

import threading

from tools.state_manager import state

_lock = threading.RLock()


def _load_money() -> int:
    return state.load("金钱", {"金钱": 0}).get("金钱", 0)


def modify_money(operation: str, amount: int, reason: str = "") -> dict:
    """**直接改钱**：增加 / 减少 amount 文。余额不足则整笔拒绝。"""
    if not isinstance(amount, int) or amount <= 0:
        return {"success": False, "error": "数额必须为正整数"}
    if operation not in ("增加", "减少"):
        return {"success": False, "error": "未知的金钱操作"}

    with _lock:
        current = _load_money()
        if operation == "减少" and amount > current:
            return {"success": False, "error": f"钱不够（当前 {current} 文，需 {amount} 文）"}
        current += amount if operation == "增加" else -amount
        state.save("金钱", {"金钱": current})

    verb = "收入" if operation == "增加" else "支出"
    return {
        "success": True,
        "message": f"已{verb}{amount}文（{reason or '未注明事由'}），当前余额 {current} 文。",
        "balance": current,
    }


def get_money() -> str:
    return f"玩家当前拥有{_load_money()}文"
