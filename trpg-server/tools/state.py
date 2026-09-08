import json

from tools.state_manager import state


def _load_state():
    return state.load("状态", {})


def modify_hunger(hunger: str):
    data = _load_state()
    data["饥饿"] = hunger
    state.save("状态", data)
    return f"成功将饥饿度修改为{hunger}"


def modify_health(health: str):
    data = _load_state()
    data["健康"] = health
    state.save("状态", data)
    return f"成功将健康度修改为{health}"


def modify_injury(injury: str):
    data = _load_state()
    data["伤势"] = injury
    state.save("状态", data)
    return f"成功将伤势修改为{injury}"


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
