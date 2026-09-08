from tools.state_manager import state


def _load_money():
    return state.load("金钱", {"金钱": 0}).get("金钱", 0)


def modify_money(operation: str, amount: int) -> str:
    """增加或减少玩家金钱"""
    current = _load_money()
    if amount <= 0:
        return "操作失败：数额必须为正整数"

    if operation == "增加":
        current += amount
        state.save("金钱", {"金钱": current})
        return f"成功增加{amount}文，当前余额{current}文"

    elif operation == "减少":
        if amount > current:
            return "玩家的钱不够！"
        current -= amount
        state.save("金钱", {"金钱": current})
        return f"成功减少{amount}文，当前余额{current}文"

    else:
        return "操作失败：未知的金钱操作"


def get_money() -> str:
    """查看玩家当前金钱"""
    return f"玩家当前拥有{_load_money()}文"
