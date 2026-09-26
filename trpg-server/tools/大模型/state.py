import json

from tools.核心.state_manager import state

#: 正数饥饿结算的**进食动词**：玩家本轮的行动里得真出现这些，才允许加饥饿。
_EAT_WORDS = ("吃", "喝", "饮", "尝", "咬", "嚼", "吞", "咽",
              "进食", "进餐", "用饭", "用餐", "下肚", "吃喝")


def _load_state():
    return state.load("状态", {})


def modify_hunger(hunger: int):
    """修改饥饿度（**0~100 数值**）。正数=进食/增加，负数=减少。

    正数（进食）只在玩家本轮**真的在吃/喝**时才结算：
    点单 / 上菜 / 付钱不能加饥饿（否则上菜加一次、真吃又加一次 → 重复结算）。
    """
    from tools.核心 import hunger as H
    data = H.sync()
    try:
        delta = int(hunger)
    except (TypeError, ValueError):
        return "饥饿修改量必须是整数（正=增加/进食，负=减少）。"
    if delta > 0:
        from tools.大模型 import turn_context as _tc
        act = _tc.current_action()
        if act and not any(w in act for w in _EAT_WORDS):
            return ("未结算：玩家本轮**没有在吃 / 喝**（只是点单 / 上菜 / 付钱 / 看着）。"
                    "饥饿度只在玩家真的进食时才增加——等玩家发出「吃 / 喝」的行动再调本工具。")
    new = H.clamp(H.coerce(data.get("饥饿", 50)) + delta)
    data["饥饿"] = H._store(new)
    data.pop("饥饿挡位", None)
    state.save("状态", data)
    return f"成功修改饥饿度：{data['饥饿']}/100"


def modify_health(health):
    """修改健康度（**0~100 数值**，100 = 康健，越低越差）。直接给新值。"""
    data = _load_state()
    try:
        v = float(health)
    except (TypeError, ValueError):
        return "健康度必须是 0~100 的数值。"
    v = max(0.0, min(100.0, v))
    data["健康"] = int(v) if float(v).is_integer() else round(v, 1)
    state.save("状态", data)
    return f"成功将健康度修改为 {data['健康']}/100"


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
