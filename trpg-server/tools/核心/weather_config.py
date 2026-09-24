# -*- coding: utf-8 -*-
"""`trpg-server/配置/天气.json` 的热读与严格校验。"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "配置" / "天气.json"
_cache: tuple[int, dict] | None = None

_REQUIRED = ("分区", "分区关键词", "默认分区", "极端天气权重", "极端天气详情", "影响")
_EFFECT_KEYS = {"判定修正", "效果倍率", "效果禁用", "禁止行动", "强制行动", "建议行动", "环境标签"}
_BASE_CONDITIONS = {"晴", "多云", "阴", "风", "小雨", "雨", "大雨", "雪"}


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _validate(data) -> dict:
    if not isinstance(data, dict):
        raise ValueError("根节点必须是对象")
    missing = [key for key in _REQUIRED if key not in data]
    if missing:
        raise ValueError(f"缺少区段：{'、'.join(missing)}")

    zones = data["分区"]
    if not isinstance(zones, list) or not zones:
        raise ValueError("分区必须是非空数组")
    zone_names = []
    for index, zone in enumerate(zones):
        if not isinstance(zone, dict) or not isinstance(zone.get("名称"), str) or not zone["名称"]:
            raise ValueError(f"分区[{index}] 缺少名称")
        zone_names.append(zone["名称"])
        for key in ("纬度下限", "纬度上限", "经度下限", "经度上限"):
            if key in zone and not _number(zone[key]):
                raise ValueError(f"分区.{zone['名称']}.{key} 必须是数字")
    if data["默认分区"] not in zone_names:
        raise ValueError("默认分区不在分区列表中")

    keywords = data["分区关键词"]
    if not isinstance(keywords, dict):
        raise ValueError("分区关键词必须是对象")
    for zone, values in keywords.items():
        if zone not in zone_names or not isinstance(values, list) or not all(isinstance(x, str) for x in values):
            raise ValueError(f"分区关键词.{zone} 无效")

    extreme = data["极端天气权重"]
    details = data["极端天气详情"]
    if not isinstance(extreme, dict) or not isinstance(details, dict):
        raise ValueError("极端天气权重与详情必须是对象")
    for zone in zone_names:
        choices = extreme.get(zone)
        if not isinstance(choices, dict) or not choices:
            raise ValueError(f"极端天气权重缺少分区：{zone}")
        if any(not _number(weight) or weight <= 0 for weight in choices.values()):
            raise ValueError(f"极端天气权重.{zone} 必须全部为正数")
        if sum(choices.values()) != 100:
            raise ValueError(f"极端天气权重.{zone} 合计必须为 100")
        for condition in choices:
            detail = details.get(condition)
            if not isinstance(detail, dict) or not all(key in detail for key in ("描述", "风力")):
                raise ValueError(f"极端天气详情缺少：{condition}")

    effects = data["影响"]
    if not isinstance(effects, dict) or not effects:
        raise ValueError("影响必须是非空对象")
    missing_effects = (_BASE_CONDITIONS | set(details)) - set(effects)
    if missing_effects:
        raise ValueError(f"影响缺少天气：{'、'.join(sorted(missing_effects))}")
    for condition, effect in effects.items():
        if not isinstance(effect, dict):
            raise ValueError(f"影响.{condition} 必须是对象")
        unknown = set(effect) - _EFFECT_KEYS
        if unknown:
            raise ValueError(f"影响.{condition} 含未知字段：{'、'.join(sorted(unknown))}")
        for key in ("判定修正", "效果倍率"):
            values = effect.get(key, {})
            if not isinstance(values, dict) or any(not isinstance(name, str) or not _number(value)
                                                   for name, value in values.items()):
                raise ValueError(f"影响.{condition}.{key} 必须是名称到数字的对象")
        for key in ("效果禁用", "禁止行动", "强制行动", "建议行动", "环境标签"):
            values = effect.get(key, [])
            if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
                raise ValueError(f"影响.{condition}.{key} 必须是字符串数组")
    return data


def load(*, copy_data: bool = True) -> dict:
    global _cache
    try:
        mtime = CONFIG_PATH.stat().st_mtime_ns
        if _cache and _cache[0] == mtime:
            return deepcopy(_cache[1]) if copy_data else _cache[1]
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        data = _validate(data)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as e:
        raise RuntimeError(f"天气配置无效：{CONFIG_PATH}：{e}") from e
    _cache = (mtime, data)
    return deepcopy(data) if copy_data else data
