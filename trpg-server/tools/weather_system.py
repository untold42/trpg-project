# -*- coding: utf-8 -*-
"""
weather_system.py
================
天气系统：根据日期（day_of_year）+ 区域（北/南/西/东）查天气数据表，
把结果写入 游戏数据/基本信息.json 的「天气」字段。

数据来源：tools/天气数据/*.json（每区 366 天，1220 闰年，索引 0=1月1日）。

"""

import datetime
import json
import os
import random

from tools.state_manager import state

WEATHER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "天气数据")

# 区域 → 分区（关键词匹配，命中即返回；默认东部城市）
ZONE_KEYWORDS = {
    "北部城市": ["开封", "大名", "太原", "蒙古", "河北", "山东", "中原", "淮河", "燕京", "金"],
    "南部城市": ["临安", "岳阳", "江南", "岭南", "荆湖", "杭州", "长沙", "洞庭", "建康"],
    "西部城市": ["成都", "利州", "四川", "蜀", "眉山", "青城", "峨眉"],
    "东部城市": ["扬州", "明州", "泉州", "福州", "沿海", "苏州", "海", "镇江", "楚州"],
}

# 极端天气具体类型（d100 加权）
EXTREME_TABLE = {
    "北部城市": [("暴雪", 40), ("沙暴", 20), ("冰雹", 40)],
    "南部城市": [("台风", 40), ("暴雨", 40), ("雷暴", 20)],
    "西部城市": [("暴雨", 50), ("冰雹", 20), ("山雾封路", 30)],
    "东部城市": [("台风", 50), ("暴雨", 30), ("海雾", 20)],
}

# 极端类型 → 描述与风力
EXTREME_DETAIL = {
    "暴雪": ("暴雪漫天", "大风"),
    "沙暴": ("沙尘蔽日", "狂风"),
    "冰雹": ("冰雹砸落", "大风"),
    "台风": ("台风过境", "狂风"),
    "暴雨": ("暴雨倾盆", "大风"),
    "雷暴": ("雷声滚滚", "大风"),
    "海雾": ("海雾锁港", "轻风"),
    "山雾封路": ("山雾封路", "轻风"),
}


def _zone_of(region):
    region = region or ""
    for zone, kws in ZONE_KEYWORDS.items():
        for kw in kws:
            if kw in region:
                return zone
    return "东部城市"


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
    # 东部城市（扬州）
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
    roll = random.randint(1, 100)
    acc = 0
    for name, weight in EXTREME_TABLE[zone]:
        acc += weight
        if roll <= acc:
            return name
    return EXTREME_TABLE[zone][0][0]


def get_weather(date=None, region=None):
    """查询天气并把结果写入 基本信息.json 的「天气」字段。"""
    base = state.load("基本信息", {})
    t = base.get("时间", {}) or {}
    pos = base.get("位置", {}) or {}

    date = date or t.get("日期")
    region = region or pos.get("区域")
    if not date:
        return {"success": False, "error": "没有可用的日期（基本信息.json 缺少 时间.日期）"}

    doy = _day_of_year(date)
    if doy is None or not (0 <= doy <= 365):
        return {"success": False, "error": f"日期格式错误：{date}"}

    zone = _zone_of(region)
    with open(os.path.join(WEATHER_DIR, f"{zone}.json"), "r", encoding="utf-8") as f:
        table = json.load(f)
    condition = table[doy] if 0 <= doy < len(table) else "晴"

    # 极端天气 → 掷 d100 定具体类型
    if condition == "极端":
        condition = _roll_extreme(zone)
        desc, wind = EXTREME_DETAIL.get(condition, ("极端天气", "狂风"))
    else:
        desc, wind = _desc_of(condition), _wind_of(condition)

    month = datetime.date(*[int(x) for x in str(date).split("-")]).month
    temperature = _temperature(month, zone)

    weather = {
        "状况": condition,
        "温度": temperature,
        "风力": wind,
        "描述": desc,
    }
    base["天气"] = weather
    state.save("基本信息", base)

    return {
        "success": True,
        "日期": date,
        "区域": region,
        "分区": zone,
        "day_of_year": doy,
        "天气": weather,
    }
