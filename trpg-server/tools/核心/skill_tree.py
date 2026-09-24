# -*- coding: utf-8 -*-
"""
skill_tree.py
=============
技能树子系统（养成）。

真相源分工：
    正典   = `trpg-server/配置/技能树.json`（预制：全部可学招式 + 前置/要求/花费 + 数值）
    运行表 = `trpg-server/配置/招式表.json`（玩家当前可用招式；初始只有「普通攻击」）
    角色卡 = `游戏数据/属性.json`（`技能点` + `五行.<行>.招式[]` = 已学招式名/描述）

点亮 `learn(name)` 需同时满足：前置已点亮、熟练度/基础数值达标、技能点足够、未学过；
满足后扣技能点，并**同步写入** `属性.json` 与 `招式表.json`。

技能点获取以 `成长.json.技能点概率` 为唯一数值源（支持热改）：
    - `设施`：修行/练习（设施养成，A 类点数）
    - `战斗`：真实战斗结束（模拟战不算）
"""

from __future__ import annotations

import json
import os
import random
import threading
from pathlib import Path

from tools.核心.state_manager import state

_SERVER = Path(__file__).resolve().parent.parent.parent
_TREE_PATH = _SERVER / "配置" / "技能树.json"
_TABLE_PATH = _SERVER / "配置" / "招式表.json"

def _chance(key: str) -> float:
    """从 `成长.json` 读取概率；缺失或非法时明确报错，不使用第二套数值。"""
    from tools.核心 import growth

    value = (growth._config().get("技能点概率") or {}).get(key)
    try:
        chance = float(value)
    except (TypeError, ValueError) as e:
        raise RuntimeError(f"成长.json.技能点概率.{key} 必须是 0~1 的数字") from e
    if not 0 <= chance <= 1:
        raise RuntimeError(f"成长.json.技能点概率.{key} 超出 0~1：{chance}")
    return chance


def chance_facility() -> float:
    """修行/练习（设施 A 类）的技能点概率。"""
    return _chance("设施")


def chance_battle() -> float:
    """真实战斗结束的技能点概率。"""
    return _chance("战斗")

_lock = threading.RLock()
_tree_cache: dict = {}


# ------------------------------------------------------------ 技能树（正典）

def _tree() -> dict:
    try:
        m = _TREE_PATH.stat().st_mtime
    except OSError:
        return {"节点": {}}
    if _tree_cache.get("m") == m:
        return _tree_cache["v"]
    try:
        raw = json.loads(_TREE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    _tree_cache["m"], _tree_cache["v"] = m, raw
    return raw


def nodes() -> dict:
    n = _tree().get("节点")
    return n if isinstance(n, dict) else {}


def get_node(name: str):
    d = nodes().get(name)
    return d if isinstance(d, dict) else None


# ------------------------------------------------------------ 招式表（运行表）

def _read_table() -> dict:
    try:
        raw = json.loads(_TABLE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    raw.setdefault("普通攻击", {})
    raw.setdefault("招式", {})
    return raw


def _write_table(table: dict) -> None:
    tmp = _TABLE_PATH.with_name(_TABLE_PATH.name + ".tmp")
    tmp.write_text(json.dumps(table, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, _TABLE_PATH)


def skill_table() -> dict:
    """玩家可用招式表（读）。"""
    with _lock:
        return _read_table()


# ------------------------------------------------------------ 角色卡

def _attr() -> dict:
    a = state.load("属性", {}) or {}
    if "技能点" not in a:
        a["技能点"] = 0
    return a


def _lit_names(attr: dict) -> set:
    out = set()
    rows = attr.get("五行") or {}
    if isinstance(rows, dict):
        for k, row in rows.items():
            if str(k).startswith("_") or not isinstance(row, dict):
                continue
            for s in row.get("招式", []) or []:
                if isinstance(s, dict) and s.get("名称"):
                    out.add(s["名称"])
    return out


def add_point(n: int = 1, reason: str = "") -> dict:
    with _lock:
        a = _attr()
        a["技能点"] = int(a.get("技能点", 0) or 0) + int(n)
        state.save("属性", a)
    return {"success": True, "技能点": a["技能点"], "来源": reason}


def roll_point(chance: float, reason: str = "") -> dict:
    """按概率掷一次技能点（命中才写）。"""
    if random.random() < chance:
        r = add_point(1, reason)
        r["获得"] = True
        return r
    return {"success": True, "获得": False}


# ------------------------------------------------------------ 校验 / 点亮

def _req_ok(node: dict, attr: dict, lit: set):
    for pre in node.get("前置") or []:
        if pre not in lit:
            return False, f"前置未点亮：{pre}"
    req = node.get("要求") or {}
    row = node.get("五行")
    for k, need in req.items():
        try:
            need = float(need)
        except (TypeError, ValueError):
            continue
        if k == "熟练度":
            cur = ((attr.get("五行") or {}).get(row) or {}).get("熟练度", 0)
            label = f"{row}行熟练度"
        else:
            cur = (attr.get("基础属性") or {}).get(k, 0)
            label = k
        try:
            cur = float(cur)
        except (TypeError, ValueError):
            cur = 0
        if cur < need:
            return False, f"{label}不足：{cur:g}/{need:g}"
    return True, ""


def can_learn(name: str) -> dict:
    node = get_node(name)
    if not node:
        return {"success": False, "error": f"技能树里没有「{name}」"}
    attr = _attr()
    if name in _lit_names(attr):
        return {"success": False, "error": "已经学过"}
    ok, why = _req_ok(node, attr, _lit_names(attr))
    if not ok:
        return {"success": False, "error": why}
    cost = int(node.get("花费", 1))
    if int(attr.get("技能点", 0) or 0) < cost:
        return {"success": False, "error": f"技能点不足：{attr.get('技能点', 0)}/{cost}"}
    return {"success": True, "花费": cost}


def learn(name: str) -> dict:
    """点亮一个技能：校验 → 扣技能点 → 写 属性.json + 招式表.json。"""
    node = get_node(name)
    if not node:
        return {"success": False, "error": f"技能树里没有「{name}」"}
    with _lock:
        attr = _attr()
        lit = _lit_names(attr)
        if name in lit:
            return {"success": False, "error": "已经学过"}
        ok, why = _req_ok(node, attr, lit)
        if not ok:
            return {"success": False, "error": why}
        cost = int(node.get("花费", 1))
        if int(attr.get("技能点", 0) or 0) < cost:
            return {"success": False, "error": f"技能点不足：{attr.get('技能点', 0)}/{cost}"}

        row = node.get("五行")
        row_obj = (attr.get("五行") or {}).setdefault(row, {})
        row_obj.setdefault("招式", []).append({
            "名称": name, "描述": node.get("描述", ""), "状态": "已学",
        })
        attr["技能点"] = int(attr.get("技能点", 0) or 0) - cost
        state.save("属性", attr)

        table = _read_table()
        table.setdefault("招式", {})[name] = {
            "名称": name, "五行": row,
            "内力": node.get("内力", 0), "射程": node.get("射程", 1),
            "范围": node.get("范围", "单体"), "威力": node.get("威力", 0),
            "连击": node.get("连击", 1), "效果": node.get("效果", []),
            "描述": node.get("描述", ""),
        }
        _write_table(table)
    return {"success": True, "技能": name, "五行": row, "花费": cost,
            "剩余技能点": attr["技能点"]}


# ------------------------------------------------------------ 视图（接口）

def view() -> dict:
    """技能树全貌 + 玩家状态（技能点 / 每节点 已学·可学·锁定 + 原因）。"""
    attr = _attr()
    lit = _lit_names(attr)
    rows = attr.get("五行") or {}
    out = []
    for name, node in nodes().items():
        if name in lit:
            st, why = "已学", ""
        else:
            r = can_learn(name)
            st, why = ("可学", "") if r.get("success") else ("锁定", r.get("error", ""))
        out.append({
            "名称": name, "五行": node.get("五行"), "花费": node.get("花费", 1),
            "前置": node.get("前置", []), "要求": node.get("要求", {}),
            "状态": st, "原因": why,
            "内力": node.get("内力", 0), "射程": node.get("射程", 1),
            "范围": node.get("范围", "单体"), "威力": node.get("威力", 0),
            "连击": node.get("连击", 0), "效果": node.get("效果", []),
            "描述": node.get("描述", ""),
        })
    return {
        "success": True,
        "技能点": int(attr.get("技能点", 0) or 0),
        "五行熟练度": {k: v.get("熟练度", 0) for k, v in rows.items()
                   if not str(k).startswith("_") and isinstance(v, dict)},
        "基础属性": attr.get("基础属性", {}),
        "节点": out,
    }
