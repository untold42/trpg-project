# -*- coding: utf-8 -*-
"""
money.py
========
金钱：**直接落账** + 最近支出账本。

    - `modify_money(...)` 直接改动 `游戏数据/金钱.json`；
    - 余额不足则整笔拒绝（不产生任何变动）；
    - **账本**：每笔「减少」追加一条到 `最近支出`，只保留最近 `LEDGER_LIMIT` 条
      （新在前）。`金钱.json` 每轮随「状态现拼」注入，故 GM / 玩家都能看到最近扣费，
      用于**防止同一笔花销被重复扣**（见 `总纲` 规则 4）。

账本条目：`{时间, 金额, 余额, 事由?}`。时间取**游戏内时间**（刻级）。
"""

import threading

from tools.核心.state_manager import state

#: 串行化同一进程内的读-改-写
_lock = threading.RLock()

#: 账本只保留最近几条
LEDGER_LIMIT = 3


def _load_money_dict() -> dict:
    data = state.load("金钱", {"金钱": 0})
    if not isinstance(data, dict):
        data = {"金钱": 0}
    data.setdefault("金钱", 0)
    return data


def _game_time() -> str:
    """当前游戏内时间（刻级），失败则留空。"""
    try:
        from tools.核心.game_clock import clock
        return clock.render()
    except Exception:
        return ""


def _append_expense(data: dict, amount: int, balance: int, reason: str):
    ledger = data.get("最近支出")
    if not isinstance(ledger, list):
        ledger = []
    entry = {"时间": _game_time(), "金额": amount, "余额": balance}
    if reason:
        entry["事由"] = reason
    ledger.insert(0, entry)          # 新在前
    data["最近支出"] = ledger[:LEDGER_LIMIT]


def modify_money(operation: str, amount: int, reason: str = None) -> dict:
    """**直接改钱**：增加 / 减少 amount 文。余额不足则整笔拒绝。

    `reason`：这笔花费是什么（一句话，如「湘酒腊味」）——写入账本；仅「减少」时记录。
    """
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        return {"success": False, "error": "数额必须为正整数"}
    if operation not in ("增加", "减少"):
        return {"success": False, "error": "未知的金钱操作"}

    with _lock:
        data = _load_money_dict()
        current = data["金钱"]
        if operation == "减少" and amount > current:
            return {"success": False, "error": f"钱不够（当前 {current} 文，需 {amount} 文）"}
        current += amount if operation == "增加" else -amount
        data["金钱"] = current
        if operation == "减少":
            _append_expense(data, amount, current, (reason or "").strip())
        state.save("金钱", data)

    verb = "收入" if operation == "增加" else "支出"
    return {
        "success": True,
        "message": f"已{verb}{amount}文，当前余额 {current} 文。",
        "balance": current,
        "最近支出": data.get("最近支出", []),
    }


def get_money() -> str:
    return f"玩家当前拥有{_load_money_dict()['金钱']}文"
