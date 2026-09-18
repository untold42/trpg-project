# -*- coding: utf-8 -*-
"""
weather_system.py
=================
天气系统（**纯代码，LLM 不参与**）。

    分区：按玩家**经纬度**落在哪个盒子（见 WEATHER_ZONES），不再靠地名模糊匹配。
    数据：天气数据/{分区}.json（每区 366 天，1220 闰年，索引 0=1月1日）。
    写回：游戏数据/基本信息.json 的「天气」字段，含代码算好的「影响」。

对外：
    get_weather(date=None, lon=None, lat=None)  —— 查表并写回 基本信息.天气
    ensure_today()                              —— **惰性同步**：日期变了就重查
    update_weather(...)                         —— 见 time_weather.py（特殊剧情覆盖）
"""

import datetime
import json
import os
import random

from tools.state_manager import state

_HERE = os.path.dirname(os.path.abspath(__file__))
WEATHER_DIR = os.path.join(os.path.dirname(_HERE), "天气数据")

#: 气象分区：**按经纬度**判定，顺序=优先级，第一个命中的生效。
#:   北部 = 淮河以北（高纬）
#:   西部 = 剑阁以西 / 四川盆地（低经）
#:   东部 = 江淮 + 江南沿海（高经、非高纬）
#:   南部 = 兜底（荆湖、江南内陆等）
#: 加新城市**不用改这里**——坐标自动落区。
WEATHER_ZONES = [
    {"name": "北部城市", "lat_min": 32.8},
    {"name": "西部城市", "lon_max": 110.5},
    {"name": "东部城市", "lon_min": 118.5, "lat_max": 33.0},
    {"name": "南部城市"},
]

#: 坐标缺失时的**兜底**（旧的地名关键词匹配，只用于容错，正常不走这条路）
ZONE_KEYWORDS = {
    "北部城市": ["开封", "大名", "太原", "蒙古", "河北", "山东", "中原", "淮河", "燕京"],
    "南部城市": ["临安", "岳阳", "江南", "岭南", "荆湖", "杭州", "长沙", "洞庭", "建康"],
    "西部城市": ["成都", "利州", "四川", "蜀", "眉山", "青城", "峨眉"],
    "东部城市": ["扬州", "明州", "泉州", "福州", "沿海", "苏州", "镇江", "楚州"],
}

#: 极端天气具体类型（d100 加权）
EXTREME_TABLE = {
    "北部城市": [("暴雪", 40), ("沙暴", 20), ("冰雹", 40)],
    "南部城市": [("台风", 40), ("暴雨", 40), ("雷暴", 20)],
    "西部城市": [("暴雨", 50), ("冰雹", 20), ("山雾封路", 30)],
    "东部城市": [("台风", 50), ("暴雨", 30), ("海雾", 20)],
}

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

#: 天气的**规则影响**——由代码算好、写进 基本信息.天气.影响，供 GM 直接引用。
#: （总纲第 5 条：硬事实由代码裁决。GM 不再需要看天气规则表。）
EFFECTS = {
    "晴": "",
    "多云": "",
    "阴": "视野略暗",
    "风": "轻功判定 +5 难度；火系效果减半",
    "小雨": "地面湿滑，轻功判定 +3 难度",
    "雨": "轻功判定 +5 难度；火系效果减半；视野受限",
    "大雨": "轻功判定 +10 难度；火系无效；视野严重受限；声音传递困难",
    "雪": "轻功判定 +5 难度；地面痕迹可见；寒冷相关判定",
    "暴雪": "禁止出行；强制避雨",
    "台风": "禁止出行；强制避雨；停航",
    "暴雨": "轻功判定 +10 难度；火系无效；视野严重受限",
    "沙暴": "禁止出行；视野严重受限",
    "冰雹": "户外危险，尽量避雨",
    "雷暴": "户外危险，尽量避雨",
    "海雾": "视野严重受限；停航",
    "山雾封路": "山路封阻",
}


def _zone_of(lon=None, lat=None, region=""):
    """经纬度 → 气象分区。坐标缺失时退回地名关键词（仅兜底）。"""
    if isinstance(lon, (int, float)) and isinstance(lat, (int, float)):
        for z in WEATHER_ZONES:
            if lat < z.get("lat_min", -90):
                continue
            if lat >= z.get("lat_max", 90):
                continue
            if lon < z.get("lon_min", -180):
                continue
            if lon >= z.get("lon_max", 180):
                continue
            return z["name"]
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
    roll = random.randint(1, 100)
    acc = 0
    for name, weight in EXTREME_TABLE[zone]:
        acc += weight
        if roll <= acc:
            return name
    return EXTREME_TABLE[zone][0][0]


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
        desc, wind = EXTREME_DETAIL.get(condition, ("极端天气", "狂风"))
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
        "影响": EFFECTS.get(condition, ""),
    }
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
        if (base.get("天气", {}) or {}).get("日期") == date:
            return
        get_weather(date=date)
    except Exception as e:      # noqa: BLE001 —— 天气失败不该影响主流程
        print(f"[weather] ensure_today 失败：{e}")
