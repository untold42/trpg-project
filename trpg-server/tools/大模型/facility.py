# -*- coding: utf-8 -*-
"""
facility.py
===========
基础设施 → 养成结算（给大模型调用的工具）。

    use_facility(facility, option, target)  —— 玩家在设施里做了具体活动后，结算养成
    facility_detail(facility)               —— 给前端「详细」界面取选项（GET /facility）
    trigger_hit(text)                        —— 给时间门禁用（命中设施触发词 → 放行时间工具）

内容表：`trpg-server/facilities.json`（按地图 kind 做键，mtime 缓存，热改免重启）。
效果两类（见 growth.py）：
    点数 → 过管道（×生效加成）→ 直接写 属性.json；
    buff → 写 游戏数据/加成.json（不碰属性，跨日取消）。
"""

from __future__ import annotations

import json
from pathlib import Path

from tools.核心 import growth
from tools.核心.state_manager import state

#: 每日养成记录（一天一个属性只能练一次）
_DAILY_FILE = "养成记录"

# trpg-server/facilities.json
TABLE_PATH = Path(__file__).resolve().parent.parent.parent / "facilities.json"
_cache: dict = {}

#: 本轮是否已经由设施活动推进过时间（每轮 main./action 开始时 reset_turn 重置）。
#: 用途：1) 引擎据此拒绝 LLM 重复调 advance_time；2) 时间权威检查把设施耗时算作“已落库”。
_TIME_ADVANCED_IN_TURN = False


def reset_turn() -> None:
    """每轮 /action 开始时由后端调用。"""
    global _TIME_ADVANCED_IN_TURN
    _TIME_ADVANCED_IN_TURN = False


def time_advanced_this_turn() -> bool:
    """本轮设施活动是否已自动推进时间。"""
    return _TIME_ADVANCED_IN_TURN


def _trained_today(target: str) -> bool:
    """该属性今天是否已经练过（一天一个属性只能练一次）。"""
    today = growth._today()
    if not today:
        return False
    rec = (state.load(_DAILY_FILE, {}) or {}).get("记录") or {}
    return rec.get(target) == today


def _mark_trained(target: str) -> None:
    rec = state.load(_DAILY_FILE, {}) or {}
    m = rec.setdefault("记录", {})
    m[target] = growth._today()
    if len(m) > 60:      # 只留最近 60 条，防无限增长
        rec["记录"] = dict(sorted(m.items(), key=lambda kv: kv[1])[-60:])
    try:
        state.save(_DAILY_FILE, rec)
    except Exception:
        pass


def _advance_time_for(ke) -> dict:
    """按**本次实际修行刻数**由后端确定性推进时间（不经过 LLM）。"""
    global _TIME_ADVANCED_IN_TURN
    try:
        ke = int(ke or 0)
    except (TypeError, ValueError):
        ke = 0
    if ke <= 0:
        return {}
    try:
        from tools.大模型 import time_weather
        # LLM 本轮已自行推过时间（如先 advance_time 再结算）→ 不再重复推
        if time_weather.time_tool_used():
            _TIME_ADVANCED_IN_TURN = True
            return {"耗时": f"{ke} 刻", "时间推进": "跳过（本轮主持人已推进时间，防重复）"}
        t = time_weather.advance_time(ke=ke)
    except Exception as e:  # noqa: BLE001
        return {"耗时": f"{ke} 刻", "时间推进": f"失败：{e}"}
    _TIME_ADVANCED_IN_TURN = True
    out = {"耗时": f"{ke} 刻"}
    if isinstance(t, dict) and t.get("success"):
        out["时间"] = t.get("时间")
    else:
        out["时间推进"] = "失败"
    return out


def _table() -> dict:
    try:
        m = TABLE_PATH.stat().st_mtime
    except OSError:
        return {}
    if _cache.get("m") == m:
        return _cache["v"]
    try:
        raw = json.loads(TABLE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}
    _cache["m"], _cache["v"] = m, raw
    return raw


def _entries():
    for kind, entry in _table().items():
        if kind.startswith("_") or not isinstance(entry, dict):
            continue
        yield kind, entry


def _resolve(facility: str):
    """facility 可以是 kind（go）或中文名（棋馆）。返回 (kind, entry) 或 (None, None)。"""
    facility = (facility or "").strip()
    if not facility:
        return None, None
    t = _table()
    if isinstance(t.get(facility), dict):
        return facility, t[facility]
    for kind, entry in _entries():
        if entry.get("名称") == facility or facility in (entry.get("触发词") or []):
            return kind, entry
        if facility in (entry.get("别名") or []):
            return kind, entry
        # 具体 POI 名（如「祝融庙」）→ 命中神名对应，归到神庙
        for deity in (entry.get("神名对应") or {}):
            if deity and deity in facility:
                return kind, entry
    return None, None


def _options(entry: dict) -> list:
    return [o for o in (entry.get("选项") or []) if isinstance(o, dict)]


def _find_option(entry: dict, label: str):
    if label:
        for o in _options(entry):
            if o.get("标签") == label:
                return o
        return None
    real = [o for o in _options(entry) if o.get("标签") != "其他"]
    return real[0] if len(real) == 1 else None


def _infer_wuxing(name: str, entry: dict):
    if entry.get("行"):
        return entry["行"]
    for deity, row in (entry.get("神名对应") or {}).items():
        if deity in (name or ""):
            return row
    return None


def _resolve_ke(entry: dict, ke) -> int:
    """本次修行的刻数：玩家自选（ke）→ 否则用设施默认 `耗时刻` → 否则 2 刻（起步）。"""
    try:
        v = int(ke)
        if v > 0:
            return v
    except (TypeError, ValueError):
        pass
    try:
        v = int(entry.get("耗时刻") or 0)
        if v > 0:
            return v
    except (TypeError, ValueError):
        pass
    return 2


def use_facility(facility: str = "", option: str = "", target: str = "", ke=None):
    """结算一次设施活动。

    - `target` 仅当效果为 `五行.*` 时需要；
    - `ke` = **玩家自选的修行刻数**（1 时辰=8 刻）；不传则用设施默认。
      点数收益 = 选项基准点数 × 时长曲线系数（`成长.json.时长曲线`）。
    """
    kind, entry = _resolve(facility)
    if not entry:
        return {"success": False,
                "error": f"未知基础设施：{facility!r}（facilities.json 里没有这个 kind / 名称 / 触发词）"}
    name = entry.get("名称") or kind

    opt = _find_option(entry, option)
    if not opt:
        labels = [o.get("标签") for o in _options(entry)]
        return {"success": False, "error": f"「{name}」没有选项「{option}」。可选：{labels}"}

    # 意外机制：本回合行动失败 → 设施活动未成：不结算、不推时间，并告知 LLM
    from tools.大模型 import accident as _accident
    if _accident.turn_accident():
        return {
            "success": False,
            "意外": True,
            "error": (f"本回合触发了意外机制（梁峰行动失败）——「{name}·{opt.get('标签')}」未成，"
                      "**未结算、未推进时间**。请按失败叙述，不要再调 `advance_time`。"),
        }

    eff = opt.get("效果")
    if not isinstance(eff, dict):
        return {"success": False,
                "error": f"「{name}·{opt.get('标签')}」是**自由活动**（无固定收益）——不必调本工具，请交给叙事处理"}

    tgt = eff.get("目标")
    if tgt == "五行.*":
        row = target or _infer_wuxing(facility, entry)
        if row not in growth.WUXING:
            return {"success": False,
                    "error": f"「{name}」的效果需指定五行：target=火/金/木/土/水（或设施名含神名）"}
        tgt = f"五行.{row}"

    typ = eff.get("类型")
    used_ke = 0
    if typ == "点数":
        # 一天一个属性只能练一次
        if _trained_today(tgt):
            return {
                "success": False,
                "error": (f"「{tgt}」今天（{growth._today()}）已经练过了——**一天一个属性只能练一次**。"
                          "换个属性练，或等明天（过夜 / 次日）再来。"),
            }
        used_ke = _resolve_ke(entry, ke)
        fac = growth.duration_factor(used_ke)
        base = float(eff.get("点数", 0) or 0)
        r = growth.gain(tgt, base * fac, source=name)
    elif typ == "buff":
        used_ke = _resolve_ke(entry, ke)
        r = growth.add_buff(name, tgt, eff.get("倍率", 2), eff.get("天数", 1))
    else:
        return {"success": False, "error": f"未知效果类型：{typ}"}

    if isinstance(r, dict) and r.get("success"):
        r["设施"] = name
        r["选项"] = opt.get("标签")
        if used_ke > 0:
            r["修行刻数"] = used_ke
        # 修行/练习：概率得技能点（概率见 成长.json.技能点概率.设施）
        if typ == "点数":
            from tools.核心 import skill_tree
            pt = skill_tree.roll_point(skill_tree.chance_facility(), name)
            if pt.get("获得"):
                r["技能点"] = pt["技能点"]
        # 设施耗时由**后端**确定性推进（不经过 LLM）
        r.update(_advance_time_for(used_ke))
        if typ == "点数":
            _mark_trained(tgt)   # 记下「今天这个属性练过了」
    return r


def facility_detail(facility: str = "", name: str = ""):
    """给前端「详细」界面：名称 + 选项 + 耗时 + 触发词 + **背景**（全部确定性，不调模型）。

    `背景` 按 `kind`（缺则按请求名）查 `场景表.md`，用地点名做**稳定散列**取一个候选场景——
    同一地点每次相同，不同地点可能不同。**不要求设施在表里**（染坊 / 戏台之类也能给背景）。
    """
    kind, entry = _resolve(facility)
    place = (name or facility or "").strip()
    scene_kind = kind or (facility or "").strip()   # 表里没有时，facility 本身就是地图 kind
    if not entry:
        if not place:
            return {"success": False, "error": "缺少设施名"}
        return {
            "success": True,
            "kind": scene_kind,
            "名称": place,
            "背景": _scene_for(scene_kind, place),
            "选项": [{"标签": "进入", "意图": "", "类型": "自由",
                     "效果类型": "",
                     "介绍": "进入此处看看。", "图标": "free"}],
            "耗时刻": None,
            "触发词": [],
        }
    entry_name = entry.get("名称") or kind
    return {
        "success": True,
        "kind": kind,
        "名称": entry_name,
        "背景": _scene_for(scene_kind, place or entry_name),
        "选项": [{
            "标签": o.get("标签"),
            "意图": o.get("意图", ""),
            "类型": o.get("类型") or ("养成" if o.get("效果") else "自由"),
            "效果类型": (o.get("效果") or {}).get("类型", ""),   # 点数 / buff：前端据此决定是否显示「时长」选择
            "介绍": o.get("介绍", ""),
            "图标": o.get("图标", ""),
        } for o in _options(entry)],
        "耗时刻": entry.get("耗时刻"),
        "触发词": entry.get("触发词", []),
    }


def _scene_for(kind: str, place: str) -> str:
    """确定性背景：查 `场景表.md` + 按地点名稳定散列（不调模型、不查库）。"""
    try:
        from tools.小模型 import ui_sim
        return ui_sim.scene_for(kind, place)
    except Exception as e:
        print(f"[facility] 背景映射失败：{e}")
        return "城市大街"


def trigger_hit(text: str) -> bool:
    """玩家输入是否命中任一设施的触发词（时间门禁用）。"""
    text = text or ""
    for _kind, entry in _entries():
        for w in entry.get("触发词") or []:
            if w and w in text:
                return True
    return False
