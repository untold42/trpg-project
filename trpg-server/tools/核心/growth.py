# -*- coding: utf-8 -*-
"""
growth.py
=========
养成管道：**所有成长在写入 `属性.json` 之前都经过这里**。

    A 类（点数）：`gain(目标, 点数, 来源)` —— 点数 × 生效加成 → 直接写 `属性.json`（即时、永久）；**点数可为小数**（如 0.25 / 0.5），存储保留两位。
    B 类（buff）：`add_buff(来源, 目标, 倍率, 天数)` —— 只写 `游戏数据/加成.json`，**不碰属性**
    跨日清理    ：`clear_expired(日期)` —— 由 `time_flow._on_new_day` 调用

设计：
    - 成长目标固定 **13 个**：基础属性 6 + 五行 5（值=熟练度）+ 学识 2；
    - buff **不叠加**：同目标后到覆盖先到（`add_buff` 内留了扩展位）；
    - buff 默认当天有效；跨日（子时）淘汰；
    - 体力/内力 改动后 `derived.sync()` → `状态.json` 的 生命/精力上限自动跟上；
    - 五行熟练度满 100（战斗里作伤害系数；**招式改由技能树点亮**，见 `tools/核心/skill_tree.py`）。

真相源：
    数值 = `游戏数据/属性.json`（唯一）；加成 = `游戏数据/加成.json`（临时，跨日清）。
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

from tools.核心.state_manager import state
from tools.核心 import derived

#: 加成文件（游戏数据/加成.json）
BUFF_FILE = "加成"

#: 合法成长目标（点分路径）。五行只到「行」，其值即 `熟练度`。
TARGETS = (
    "基础属性.体力", "基础属性.内力", "基础属性.剑法",
    "基础属性.拳掌", "基础属性.暗器", "基础属性.轻功",
    "五行.火", "五行.金", "五行.木", "五行.土", "五行.水",
    "学识.口舌", "学识.知识",
)
_TARGET_SET = frozenset(TARGETS)
WUXING = ("火", "金", "木", "土", "水")
#: 五行熟练度上限（战斗：<30 不可催动，见 战斗系统.md §5.3）
WUXING_MAX = 100

# 成长曲线配置（trpg-server/配置/成长.json）——热改免重启
CONFIG_FILE = Path(__file__).resolve().parent.parent.parent / "配置" / "成长.json"
_config_cache: dict = {}


def _config() -> dict:
    try:
        m = CONFIG_FILE.stat().st_mtime
    except OSError:
        return {}
    if _config_cache.get("m") == m:
        return _config_cache["v"]
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}
    _config_cache["m"], _config_cache["v"] = m, raw
    return raw


def curve_factor(target: str, cur) -> float:
    """成长曲线系数：当前值越大、单次收益越小（取『不超当前值的最大阈值』档）。"""
    tiers = (_config().get("曲线") or {}).get(
        "五行" if target.startswith("五行.") else "其它")
    if not isinstance(tiers, list):
        return 1.0
    try:
        v = float(cur)
    except (TypeError, ValueError):
        return 1.0
    fac, best = 1.0, None
    for item in tiers:
        try:
            th, f = float(item[0]), float(item[1])
        except (TypeError, ValueError, IndexError):
            continue
        if v >= th and (best is None or th >= best):
            best, fac = th, f
    return fac


def duration_factor(ke) -> float:
    """修行时长（刻）→ 收益系数（`成长.json.时长曲线`）。

    取『不超请求刻数的最大档』；低于最小档按最小档，超过最大档按最大档。
    最终点数 = 选项基准点数 × 本系数。
    """
    tiers = (_config().get("时长曲线") or {}).get("表") or []
    if not isinstance(tiers, list) or not tiers:
        return 1.0
    parsed = []
    for item in tiers:
        try:
            parsed.append((float(item[0]), float(item[1])))
        except (TypeError, ValueError, IndexError):
            continue
    if not parsed:
        return 1.0
    parsed.sort()
    try:
        v = float(ke)
    except (TypeError, ValueError):
        v = 0.0
    fac = parsed[0][1]
    for th, f in parsed:
        if v >= th:
            fac = f
        else:
            break
    return fac


def _today() -> str:
    from tools.核心.game_clock import clock
    try:
        return clock.civil().get("日期", "")
    except Exception:
        return ""


# ------------------------------------------------------------
# 属性读写（点分路径 → 属性.json）
# ------------------------------------------------------------
def _get(attr: dict, target: str):
    parts = target.split(".")
    node = attr
    for p in parts[:-1]:
        node = node.get(p) if isinstance(node, dict) else None
    if not isinstance(node, dict):
        return None
    if target.startswith("五行."):
        row = node.get(parts[-1])
        return row.get("熟练度") if isinstance(row, dict) else None
    return node.get(parts[-1])


def _set(attr: dict, target: str, value) -> bool:
    parts = target.split(".")
    node = attr
    for p in parts[:-1]:
        node = node.get(p) if isinstance(node, dict) else None
        if not isinstance(node, dict):
            return False
    if target.startswith("五行."):
        row = node.get(parts[-1])
        if not isinstance(row, dict):
            return False
        row["熟练度"] = value
        return True
    node[parts[-1]] = value
    return True


# ------------------------------------------------------------
# buff（加成.json）
# ------------------------------------------------------------
def _buffs() -> dict:
    data = state.load(BUFF_FILE, {}) or {}
    buffs = data.get("生效")
    return buffs if isinstance(buffs, dict) else {}


def _expired(b: dict, today: str = "") -> bool:
    today = today or _today()
    exp = str(b.get("到期", ""))
    return bool(exp) and bool(today) and exp <= today


def modifier(target: str) -> float:
    """该目标当前生效的加成倍率（无 / 已过期 → 1.0）。"""
    b = _buffs().get(target)
    if not isinstance(b, dict) or _expired(b):
        return 1.0
    try:
        return float(b.get("倍率", 1) or 1)
    except (TypeError, ValueError):
        return 1.0


def list_buffs() -> list:
    """当前生效的加成（供 `get_ability` / 工具返回 / 将来注入状态）。"""
    today = _today()
    return [
        {"目标": t, "来源": b.get("来源", ""), "倍率": b.get("倍率", 1), "到期": b.get("到期", "")}
        for t, b in _buffs().items()
        if isinstance(b, dict) and not _expired(b, today)
    ]


def add_buff(source: str, target: str, multiplier, days: int = 1) -> dict:
    """B 类：写加成。**不叠加**——同目标覆盖（将来要叠层，把 `生效` 的值改成列表即可）。"""
    if target not in _TARGET_SET:
        return {"success": False, "error": f"未知成长目标：{target}"}
    try:
        mult = float(multiplier)
    except (TypeError, ValueError):
        return {"success": False, "error": "倍率必须是数字"}
    if mult <= 0:
        return {"success": False, "error": "倍率必须为正"}
    try:
        n = max(1, int(days))
    except (TypeError, ValueError):
        n = 1
    today = _today()
    try:
        expiry = (datetime.date.fromisoformat(today) + datetime.timedelta(days=n)).isoformat()
    except ValueError:
        expiry = today
    data = state.load(BUFF_FILE, {}) or {}
    data.setdefault("生效", {})[target] = {"来源": source, "倍率": mult, "到期": expiry}
    state.save(BUFF_FILE, data)
    return {"success": True, "目标": target, "来源": source, "倍率": mult, "到期": expiry}


def clear_expired(today: str = "") -> list:
    """跨日清理到期加成，返回被清除的目标列表。"""
    today = today or _today()
    data = state.load(BUFF_FILE, {}) or {}
    buffs = data.get("生效")
    if not isinstance(buffs, dict) or not buffs:
        return []
    dead = [t for t, b in buffs.items() if not isinstance(b, dict) or _expired(b, today)]
    for t in dead:
        buffs.pop(t, None)
    if dead:
        try:
            state.save(BUFF_FILE, data)
        except OSError as e:
            print(f"[growth] 清理加成写盘失败：{e}")
    return dead


# ------------------------------------------------------------
# 点数（A 类）
# ------------------------------------------------------------
def gain(target: str, amount, source: str = "") -> dict:
    """A 类：点数过管道（×生效加成）→ 写 `属性.json`。**支持小数**（如 0.25 / 0.5）。"""
    if target not in _TARGET_SET:
        return {"success": False,
                "error": f"未知成长目标：{target}（合法：{'、'.join(TARGETS)}）"}
    try:
        base = float(amount)
    except (TypeError, ValueError):
        return {"success": False, "error": "点数必须是数字"}
    if base <= 0:
        return {"success": False, "error": "点数必须为正"}
    attr = state.load("属性", {}) or {}
    cur = _get(attr, target)
    if isinstance(cur, bool) or not isinstance(cur, (int, float)):
        return {"success": False, "error": f"属性里读不到目标：{target}"}

    mult = modifier(target)
    curve = curve_factor(target, cur)
    new = round(cur + base * mult * curve, 2)   # 保留两位小数，避免浮点噪声
    capped = False
    if target.startswith("五行.") and new > WUXING_MAX:
        new = WUXING_MAX
        capped = True

    _set(attr, target, new)
    state.save("属性", attr)
    if target in ("基础属性.体力", "基础属性.内力"):
        derived.sync()

    result = {
        "success": True, "目标": target, "来源": source,
        "基础增加": round(base, 3), "加成倍率": mult, "曲线系数": curve,
        "实际增加": round(new - cur, 2), "现值": new,
    }
    if capped:
        result["注"] = f"{target} 已达上限 {WUXING_MAX}"
    return result
