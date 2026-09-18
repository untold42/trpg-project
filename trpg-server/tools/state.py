import json

from tools.state_manager import state


def _load_state():
    return state.load("状态", {})


def modify_hunger(hunger: int):
    """修改饥饿度（**0~100 数值**）。正数=进食/增加，负数=减少。"""
    from tools import hunger as H
    data = H.sync()
    try:
        delta = int(hunger)
    except (TypeError, ValueError):
        return "饥饿修改量必须是整数（正=增加/进食，负=减少）。"
    new = H.clamp(H.coerce(data.get("饥饿", 50)) + delta)
    data["饥饿"] = H._store(new)
    data["饥饿挡位"] = H.level_of(new)
    state.save("状态", data)
    return f"成功修改饥饿度：{data['饥饿']}/100（{data['饥饿挡位']}）"


def modify_health(health: str):
    data = _load_state()
    data["健康"] = health
    state.save("状态", data)
    return f"成功将健康度修改为{health}"


def modify_hp(hp: int):
    data = _load_state()
    cur = data.get("生命值", 0)
    max_hp = data.get("生命上限", 0)
    if -hp > cur:
        return "受到的伤害大于玩家的当前生命值，梁峰濒死"
    data["生命值"] = min(cur + hp, max_hp)
    state.save("状态", data)
    return f"成功修改生命值，当前为{data['生命值']}"


def modify_tp(tp: int):
    data = _load_state()
    cur = data.get("精力值", 0)
    max_tp = data.get("精力上限", 0)
    if -tp > cur:
        return "减少的精力大于玩家的当前精力值，梁峰力竭倒下"
    data["精力值"] = min(cur + tp, max_tp)
    state.save("状态", data)
    return f"成功修改精力值，当前为{data['精力值']}"


def get_state():
    return json.dumps(_load_state(), ensure_ascii=False)
