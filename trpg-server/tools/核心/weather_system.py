# -*- coding: utf-8 -*-
"""
weather_system.py
=================
天气系统（**纯代码，LLM 不参与**）。

    分区：按玩家**经纬度**和 `天气.json.分区` 判定，不再靠地名模糊匹配。
    数据：天气数据/{分区}.json（每区 366 天，1220 闰年，索引 0=1月1日）。
    规则：`天气.json.影响` 是唯一来源，代码生成结构化「影响」与派生「影响文本」。
    写回：游戏数据/基本信息.json 的「天气」字段。

对外：
    get_weather(date=None, lon=None, lat=None)  —— 查表并写回 基本信息.天气
    ensure_today()                              —— **惰性同步**：日期变了就重查
    update_weather(...)                         —— 见 time_weather.py（特殊剧情覆盖）
"""

import datetime
import json
import os
import random

from tools.核心 import weather_config
from tools.核心.state_manager import state

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEATHER_DIR = os.path.join(os.path.dirname(_HERE), "天气数据")

_EMPTY_EFFECT = {
    "判定修正": {},
    "效果倍率": {},
    "效果禁用": [],
    "禁止行动": [],
    "强制行动": [],
    "建议行动": [],
    "环境标签": [],
}


def effect_for(condition: str) -> dict:
    """返回稳定结构的天气规则影响；判定修正可直接加到 d100。"""
    configured = weather_config.load(copy_data=False)["影响"].get(condition, {})
    return {
        key: dict(configured.get(key, {})) if isinstance(default, dict)
        else list(configured.get(key, []))
        for key, default in _EMPTY_EFFECT.items()
    }


def effect_text(effect: dict) -> str:
    """由结构化规则生成供人阅读的说明，不反向解析文本。"""
    parts = []
    for name, modifier in effect.get("判定修正", {}).items():
        if modifier < 0:
            parts.append(f"{name}判定 +{-modifier:g} 难度")
        else:
            parts.append(f"{name}判定 {modifier:+g} 修正")
    for name, multiplier in effect.get("效果倍率", {}).items():
        parts.append(f"{name}效果减半" if multiplier == 0.5 else f"{name}效果 ×{multiplier:g}")
    parts.extend(f"{name}无效" for name in effect.get("效果禁用", []))

    action_text = {"出行": "禁止出行", "航行": "停航", "山路通行": "山路封阻"}
    parts.extend(action_text.get(name, f"禁止{name}") for name in effect.get("禁止行动", []))
    parts.extend(f"强制{name}" for name in effect.get("强制行动", []))
    parts.extend(effect.get("环境标签", []))
    parts.extend(f"尽量{name}" for name in effect.get("建议行动", []))
    return "；".join(parts)


def sync_effect(weather: dict) -> bool:
    """按状况刷新结构化影响和派生文本；有变化返回 True。"""
    effect = effect_for(str(weather.get("状况", "")))
    text = effect_text(effect)
    changed = weather.get("影响") != effect or weather.get("影响文本") != text
    weather["影响"] = effect
    weather["影响文本"] = text
    return changed


def _zone_of(lon=None, lat=None, region=""):
    """经纬度 → 气象分区。坐标缺失时退回地名关键词（仅兜底）。"""
    cfg = weather_config.load(copy_data=False)
    if isinstance(lon, (int, float)) and isinstance(lat, (int, float)):
        for zone in cfg["分区"]:
            if lat < zone.get("纬度下限", -90):
                continue
            if lat >= zone.get("纬度上限", 90):
                continue
            if lon < zone.get("经度下限", -180):
                continue
            if lon >= zone.get("经度上限", 180):
                continue
            return zone["名称"]
    region = region or ""
    for zone, keywords in cfg["分区关键词"].items():
        if any(keyword in region for keyword in keywords):
            return zone
    return cfg["默认分区"]


def _day_of_year(date_str):
    """'1220-01-15' -> 0-based day_of_year（1月1日=0）。"""
    try:
        y, m, d = (int(x) for x in str(date_str).split("-"))
        return datetime.date(y, m, d).timetuple().tm_yday - 1
    except (ValueError, TypeError):
        return None


def _temperature(month, zone):
    if zone == "北部城市":
        if month in (12, 1, 2):
            return "严寒"
        if month in (3, 4, 5):
            return "微凉"
        if month in (6, 7, 8):
            return "炎热"
        return "温暖"
    if zone == "南部城市":
        if month in (12, 1, 2):
            return "湿冷"
        if month in (3, 4, 5):
            return "温暖"
        if month in (6, 7, 8):
            return "炎热"
        return "温暖"
    if zone == "西部城市":
        if month in (12, 1, 2):
            return "阴冷"
        if month in (3, 4, 5):
            return "微凉"
        if month in (6, 7, 8):
            return "温暖"
        return "微凉"
    # 东部城市
    if month in (12, 1, 2):
        return "寒冷"
    if month in (3, 4, 5):
        return "微凉"
    if month in (6, 7, 8):
        return "炎热"
    return "温暖"


def _wind_of(condition):
    if condition == "风":
        return "强风"
    if condition in ("大雨", "雨", "雪"):
        return "大风"
    if condition == "小雨":
        return "微风"
    if condition == "晴":
        return "无风"
    return "轻风"


def _desc_of(condition):
    return {
        "晴": "天朗气清",
        "多云": "云层舒卷",
        "阴": "天色灰蒙",
        "风": "风起尘扬",
        "小雨": "细雨绵绵",
        "雨": "雨势渐密",
        "大雨": "雨幕密集",
        "雪": "雪落无声",
    }.get(condition, "")


def _roll_extreme(zone):
    """极端天气掷 d100 定具体类型。"""
    choices = weather_config.load(copy_data=False)["极端天气权重"][zone]
    roll = random.randint(1, 100)
    acc = 0
    for name, weight in choices.items():
        acc += weight
        if roll <= acc:
            return name
    raise RuntimeError(f"天气配置无效：{zone} 的极端天气权重未覆盖 d100")


def get_weather(date=None, lon=None, lat=None):
    """按「日期 + 玩家经纬度」查天气，写回 基本信息.json 的「天气」字段。"""
    base = state.load("基本信息", {})
    t = base.get("时间", {}) or {}
    pos = base.get("位置", {}) or {}

    date = date or t.get("日期")
    if lon is None:
        lon = pos.get("经度")
    if lat is None:
        lat = pos.get("纬度")
    if not date:
        return {"success": False, "error": "没有可用的日期（基本信息.json 缺少 时间.日期）"}

    doy = _day_of_year(date)
    if doy is None or not (0 <= doy <= 365):
        return {"success": False, "error": f"日期格式错误：{date}"}

    zone = _zone_of(lon, lat, pos.get("区域", ""))
    with open(os.path.join(WEATHER_DIR, f"{zone}.json"), "r", encoding="utf-8") as f:
        table = json.load(f)
    condition = table[doy] if 0 <= doy < len(table) else "晴"

    if condition == "极端":
        condition = _roll_extreme(zone)
        detail = weather_config.load(copy_data=False)["极端天气详情"][condition]
        desc, wind = detail["描述"], detail["风力"]
    else:
        desc, wind = _desc_of(condition), _wind_of(condition)

    month = datetime.date(*[int(x) for x in str(date).split("-")]).month
    temperature = _temperature(month, zone)

    weather = {
        "日期": date,                      # 这份天气属于哪一天（供 ensure_today 比对）
        "状况": condition,
        "温度": temperature,
        "风力": wind,
        "描述": desc,
    }
    sync_effect(weather)
    base["天气"] = weather
    state.save("基本信息", base)

    return {"success": True, "日期": date, "分区": zone,
            "day_of_year": doy, "天气": weather}


def ensure_today():
    """**惰性同步**：若 基本信息.天气 不对应当前日期，就重查一次。

    在 `engine.state_dict()` 里调用 → 每轮状态里的天气永远是最新的，
    GM 不必再自己调工具同步。失败静默（不影响玩）。
    """
    try:
        base = state.load("基本信息", {}) or {}
        date = (base.get("时间", {}) or {}).get("日期")
        if not date:
            return
        weather = base.get("天气", {}) or {}
        if weather.get("日期") == date:
            if sync_effect(weather):
                base["天气"] = weather
                state.save("基本信息", base)
            return
        get_weather(date=date)
    except RuntimeError:
        raise  # 配置缺失/非法必须明确暴露，不能继续使用旧文本或旧数值
    except Exception as e:      # noqa: BLE001 —— 单次天气数据读取失败不阻断主流程
        print(f"[weather] ensure_today 失败：{e}")
