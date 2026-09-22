import random

#: 本回合是否触发了「意外机制」（3% 行动失败）。由 main./action 每轮设置，
#: 供 use_facility 等后端逻辑读取（工具函数拿不到 session，用模块级标志即可——单机单局）。
_TURN_ACCIDENT = False


def set_turn(triggered: bool) -> None:
    """每轮 /action 开始时由后端调用，记录本轮是否触发意外。"""
    global _TURN_ACCIDENT
    _TURN_ACCIDENT = bool(triggered)


def turn_accident() -> bool:
    """本回合是否触发了意外。"""
    return _TURN_ACCIDENT


def accident():
    """以 3% 概率触发行动失败（d100 掷出 98–100）。"""
    return random.randint(1, 100) >= 98
