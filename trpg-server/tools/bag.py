import json

from tools.state_manager import state


def _load_bag():
    return state.load("背包", {"物品": {}})


def modify_item(name, quantity=None, description=None) -> str:
    """修改背包中已有物品"""
    data = _load_bag()
    if name not in data["物品"]:
        return f"{name}不存在！请重新检查背包。"
    if quantity is not None:
        data["物品"][name]["数量"] = quantity
    if description is not None:
        data["物品"][name]["描述"] = description
    state.save("背包", data)
    return f"成功修改背包物品：{name}"


def add_item(name, item_type, quantity, description) -> str:
    """添加新物品到背包"""
    data = _load_bag()
    if name in data["物品"]:
        return f"{name}已存在！如需修改请使用修改物品函数。"
    data["物品"][name] = {
        "类型": item_type,
        "数量": quantity,
        "描述": description,
        "随身携带": False,
    }
    state.save("背包", data)
    return f"成功添加{quantity}个{name}到背包。"


def remove_item(name) -> str:
    """删除背包中的物品"""
    data = _load_bag()
    if name not in data["物品"]:
        return f"{name}不存在于背包！"
    del data["物品"][name]
    state.save("背包", data)
    return f"成功删除{name}。"


def get_inventory() -> str:
    """查看背包"""
    return json.dumps(_load_bag(), ensure_ascii=False)
