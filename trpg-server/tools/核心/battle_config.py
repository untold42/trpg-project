# -*- coding: utf-8 -*-
"""战斗数值配置读取器。

`trpg-server/战斗数值.json` 是战斗全局数值的唯一策划源。
本模块不提供另一套默认值；配置缺失或损坏时直接报错，避免静默使用旧数值。
"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "战斗数值.json"
_cache: tuple[int, dict] | None = None

_REQUIRED_SECTIONS = (
    "棋盘", "梯度系数", "NPC推导", "移动力", "命中", "五行", "位置",
    "武器类型", "Buff", "流血叠层上限", "回合", "防守", "穿甲", "蓄力",
    "交流", "撤退", "伤害", "战术AI", "思路评价",
)


def _validate(data) -> dict:
    if not isinstance(data, dict):
        raise ValueError("根节点必须是对象")
    missing = [key for key in _REQUIRED_SECTIONS if key not in data]
    if missing:
        raise ValueError(f"缺少区段：{'、'.join(missing)}")

    board = data["棋盘"]
    if not isinstance(board, dict) or int(board.get("宽", 0)) <= 0 or int(board.get("高", 0)) <= 0:
        raise ValueError("棋盘宽高必须为正整数")
    for key in ("友方起始列", "敌方起始列"):
        cols = board.get(key)
        if not isinstance(cols, list) or not cols:
            raise ValueError(f"棋盘.{key} 必须是非空数组")
        if any(isinstance(col, bool) or not isinstance(col, int) or not 0 <= col < int(board["宽"])
               for col in cols):
            raise ValueError(f"棋盘.{key} 必须是棋盘宽度内的整数列")

    tiers = data["梯度系数"]
    if not isinstance(tiers, dict) or not tiers:
        raise ValueError("梯度系数必须是非空对象")
    for key, value in tiers.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(f"梯度系数.{key} 必须是正数")

    required_keys = {
        "NPC推导": ("生命", "内力", "主兵器", "副剑拳", "副暗器", "轻功"),
        "移动力": ("基础", "每档轻功"),
        "命中": ("未命中线", "标准命中线", "会心线", "擦中伤害倍率", "普通伤害倍率",
                 "会心伤害倍率", "属性差除数", "属性修正下限", "属性修正上限"),
        "五行": ("优势倍率", "劣势倍率", "熟练度每点增伤"),
        "位置": ("背袭", "夹击"),
        "回合": ("内力回复比例",),
        "防守": ("回复内力", "减伤", "总减伤上限"),
        "穿甲": ("减伤保留倍率",),
        "蓄力": ("叠层上限", "每层增伤"),
        "交流": ("基础持续回合", "思路修正阈值", "最短持续回合"),
        "撤退": ("成功线", "轻功除数", "轻功加成上限"),
        "伤害": ("兵器属性基准", "思路修正基准", "最低伤害"),
        "战术AI": ("位置权重", "前瞻权重", "内力代价权重", "撤退血线",
                   "首次进入近战加分", "每接近一格加分", "夹击背袭每个加分", "被围每人扣分",
                   "低血撤退加分", "非低血撤退扣分", "交流扣分", "前瞻掷骰次数", "单位价值"),
    }
    for section, keys in required_keys.items():
        value = data[section]
        if not isinstance(value, dict):
            raise ValueError(f"{section} 必须是对象")
        absent = [key for key in keys if key not in value]
        if absent:
            raise ValueError(f"{section} 缺少字段：{'、'.join(absent)}")

    for name in ("生命", "内力", "主兵器", "副剑拳", "副暗器", "轻功"):
        rule = data["NPC推导"][name]
        if not isinstance(rule, dict) or "系数" not in rule or "基础" not in rule:
            raise ValueError(f"NPC推导.{name} 必须包含系数与基础")

    for name in ("背袭", "夹击"):
        rule = data["位置"][name]
        if not isinstance(rule, dict) or "命中" not in rule or "伤害" not in rule:
            raise ValueError(f"位置.{name} 必须包含命中与伤害")

    unit_value = data["战术AI"]["单位价值"]
    unit_keys = ("兵器系数", "内力系数", "有招式加分", "单个增益加分", "单个减益扣分")
    if not isinstance(unit_value, dict) or any(key not in unit_value for key in unit_keys):
        raise ValueError(f"战术AI.单位价值 必须包含：{'、'.join(unit_keys)}")

    positive_values = (
        ("移动力.每档轻功", data["移动力"]["每档轻功"]),
        ("命中.属性差除数", data["命中"]["属性差除数"]),
        ("撤退.轻功除数", data["撤退"]["轻功除数"]),
        ("伤害.兵器属性基准", data["伤害"]["兵器属性基准"]),
        ("伤害.思路修正基准", data["伤害"]["思路修正基准"]),
        ("战术AI.前瞻掷骰次数", data["战术AI"]["前瞻掷骰次数"]),
    )
    for path, value in positive_values:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(f"{path} 必须是正数")

    hit = data["命中"]
    if not hit["未命中线"] < hit["标准命中线"] < hit["会心线"]:
        raise ValueError("命中三条阈值必须依次递增")

    if not isinstance(data["Buff"], dict) or not data["Buff"]:
        raise ValueError("Buff 必须是非空对象")
    for name, rule in data["Buff"].items():
        if not isinstance(rule, dict) or "持续" not in rule or "可叠层" not in rule:
            raise ValueError(f"Buff.{name} 必须包含持续与可叠层")
    if not isinstance(data["武器类型"], dict) or not data["武器类型"]:
        raise ValueError("武器类型必须是非空对象")
    for name, rule in data["武器类型"].items():
        if not isinstance(rule, dict) or "伤害" not in rule:
            raise ValueError(f"武器类型.{name} 必须包含伤害")

    scores = data["思路评价"]
    if not isinstance(scores, dict) or "平平" not in scores:
        raise ValueError("思路评价必须包含“平平”")
    return data


def load(*, copy_data: bool = True) -> dict:
    """按文件修改时间读取并校验配置；未变化时走内存缓存。"""
    global _cache
    try:
        mtime = CONFIG_PATH.stat().st_mtime_ns
        if _cache and _cache[0] == mtime:
            return deepcopy(_cache[1]) if copy_data else _cache[1]
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        data = _validate(data)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as e:
        raise RuntimeError(f"战斗数值配置无效：{CONFIG_PATH}：{e}") from e
    _cache = (mtime, data)
    return deepcopy(data) if copy_data else data


def section(name: str, *, copy_data: bool = True) -> dict:
    value = load(copy_data=copy_data).get(name)
    if not isinstance(value, dict):
        raise RuntimeError(f"战斗数值配置区段不是对象：{name}")
    return value
