# -*- coding: utf-8 -*-
"""
quest.py
========
任务系统的**数据与结算核心**（后端真相源）。

设计（见 `trpg-server/文档/设计-任务系统与保活机制.md`）：
    - 真相源：`游戏数据/任务.json`（单一文件，走 state_manager，原子写）。
    - 种子：`trpg-server/任务/*.json`（作者手写，开局并入；按 id 幂等）。
    - 时限：**绝对游戏秒**（挂连续时钟）；`时限时辰` 由任务裁定给，代码换算。
    - 奖励：完成时**静默发技能点**（`skill_tree.add_point`，GM 不知道）。
    - 隐藏字段：`失败后果` 只给 DDL 裁定用，**不进玩家视图、也不进 GM 视图**。

角色分工（后端）：
    add      = 旁路大模型（玩家点「任务化」触发）—— 见 `tools/大模型/quest_arbiter.py`
    update   = 小模型，仅对**被追踪**的任务 —— 见 `tools/小模型/quest_sim.py`
    complete = 同上
    expire   = 到时限后旁路大模型裁定一次 —— 见 `quest_arbiter.arbitrate_expiry`
    追踪      = 前端 localStorage 为真相源，每次 `/action` 上报 id 列表（本模块只做无状态过滤）
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from tools.核心.state_manager import state
from tools.核心.game_clock import (
    clock, SECONDS_PER_SHICHEN, civil_from_seconds, render_civil,
)

STATE_KEY = "任务"

SERVER_DIR = Path(__file__).resolve().parent.parent.parent
SEED_DIR = SERVER_DIR / "任务"
CONFIG_FILE = SERVER_DIR / "配置" / "任务.json"

DEFAULT_CONFIG = {"奖励": {"技能点": 1}, "里程碑扩展上限": 3}

STATUS_ACTIVE = "进行中"
STATUS_DONE = "已完成"
STATUS_EXPIRED = "已过期"

_config_cache: dict = {}


# ------------------------------------------------------------
# 配置 / 读写
# ------------------------------------------------------------
def config() -> dict:
    """读 `配置/任务.json`（按 mtime 缓存；缺失/损坏用默认）。热改免重启。"""
    try:
        m = CONFIG_FILE.stat().st_mtime
    except OSError:
        return dict(DEFAULT_CONFIG)
    if _config_cache.get("m") == m:
        return _config_cache["v"]
    cfg = dict(DEFAULT_CONFIG)
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            cfg.update(raw)
    except (OSError, json.JSONDecodeError):
        pass
    _config_cache["m"], _config_cache["v"] = m, cfg
    return cfg


def _load() -> dict:
    d = state.load(STATE_KEY, None)
    if not isinstance(d, dict) or not isinstance(d.get("任务"), list):
        d = {"任务": []}
    return d


def _save(d: dict) -> None:
    state.save(STATE_KEY, d)


def _all(d: dict | None = None) -> list[dict]:
    return (d or _load()).get("任务") or []


def get(task_id: str) -> dict | None:
    for t in _all():
        if t.get("id") == task_id:
            return t
    return None


def active() -> list[dict]:
    return [t for t in _all() if t.get("状态") == STATUS_ACTIVE]


def archived() -> list[dict]:
    return [t for t in _all() if t.get("状态") != STATUS_ACTIVE]


# ------------------------------------------------------------
# 种子
# ------------------------------------------------------------
def ensure_seeded() -> int:
    """把 `trpg-server/任务/*.json` 里的种子并入（按 id 幂等）。返回新增数。"""
    if not SEED_DIR.is_dir():
        return 0
    seeds = []
    for f in sorted(SEED_DIR.glob("*.json")):
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        items = raw.get("任务") if isinstance(raw, dict) else raw
        if isinstance(items, list):
            seeds.extend(x for x in items if isinstance(x, dict))
    if not seeds:
        return 0
    d = _load()
    have = {t.get("id") for t in _all(d)}
    added = 0
    for s in seeds:
        sid = str(s.get("id") or "").strip() or _new_id()
        if sid in have:
            continue
        s = dict(s)
        s["id"] = sid
        s.setdefault("状态", STATUS_ACTIVE)
        s.setdefault("可见", True)
        s.setdefault("来源", "种子")
        for ms in s.get("里程碑") or []:
            ms.setdefault("状态", "未完成")
        # 种子可用「时限时辰」（相对分钟）→ 开局时换算成绝对游戏秒
        if not isinstance((s.get("时限") or {}).get("游戏秒"), int):
            s["时限"] = _deadline(s.get("时限时辰", 24))
            if s.get("时限文本"):
                s["时限"]["文本"] = s["时限文本"]
        s.setdefault("创建于", _now_str())
        have.add(sid)
        d["任务"].append(s)
        added += 1
    if added:
        _save(d)
    return added


# ------------------------------------------------------------
# 增 / 改 / 结
# ------------------------------------------------------------
def _new_id() -> str:
    return "q_" + uuid.uuid4().hex[:8]


def _now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _deadline(时限时辰: int) -> dict:
    hours = max(1, int(时限时辰 or 1))
    secs = clock.seconds() + hours * SECONDS_PER_SHICHEN
    return {"类型": "绝对", "游戏秒": int(secs),
            "显示": render_civil(civil_from_seconds(secs)),
            "剩余时辰": hours}


def add(标题: str, 描述: str = "", 委托人: str = "",
        里程碑: list | None = None, 时限文本: str = "", 时限时辰: int = 1,
        类型: str = "支线", 来源: str = "任务裁定", 失败后果: str = "") -> dict:
    """新建一个任务（由 add 裁定 / 种子调用）。返回任务 dict。"""
    标题 = (标题 or "").strip()
    if not 标题:
        return {}
    tasks = []
    for m in (里程碑 or []):
        if isinstance(m, dict):
            tasks.append({"项": str(m.get("项") or m.get("里程碑") or "").strip(),
                          "状态": m.get("状态") or "未完成"})
        elif str(m).strip():
            tasks.append({"项": str(m).strip(), "状态": "未完成"})
    t = {
        "id": _new_id(),
        "标题": 标题,
        "类型": 类型 or "支线",
        "状态": STATUS_ACTIVE,
        "可见": True,
        "描述": (描述 or "").strip(),
        "委托人": (委托人 or "").strip(),
        "里程碑": tasks,
        "时限": _deadline(时限时辰),
        "失败后果": (失败后果 or "").strip(),
        "来源": 来源,
        "创建于": _now_str(),
        "更新于": _now_str(),
        "归档于": None,
        "结果": None,
    }
    if 时限文本:
        t["时限"]["文本"] = 时限文本.strip()
    d = _load()
    d["任务"].append(t)
    _save(d)
    return t


def update(task_id: str, 里程碑="") -> dict:
    """把匹配到的里程碑标为已完成（**可传一条或多条**；幂等）。

    返回 `{success, 任务, 命中, 里程碑, 全部完成}`——`全部完成=True` 时，调用方应触发
    旁路大模型裁定「是否需要补新里程碑」，而不是直接算完成。
    """
    d = _load()
    t = next((x for x in _all(d) if x.get("id") == task_id), None)
    if not t:
        return {"success": False, "error": f"没有该任务：{task_id}"}
    if t.get("状态") != STATUS_ACTIVE:
        return {"success": True, "任务": _player_card(t), "noop": "已了结", "全部完成": False}
    wanted = 里程碑 if isinstance(里程碑, (list, tuple)) else [里程碑]
    matched: list[str] = []
    for w in wanted:
        key = _match_milestone(t, w)
        if key and key not in matched:
            matched.append(key)
    hit = False
    for ms in t.get("里程碑") or []:
        if ms.get("项") in matched and ms.get("状态") != "已完成":
            ms["状态"] = "已完成"
            hit = True
    t["更新于"] = _now_str()
    _save(d)
    return {"success": True, "任务": _player_card(t), "命中": hit,
            "里程碑": matched, "全部完成": all_done(t)}


def all_done(t: dict) -> bool:
    """该任务的里程碑是否**全部**已完成（含至少一条）。"""
    ms = t.get("里程碑") or []
    return bool(ms) and all(m.get("状态") == "已完成" for m in ms)


def add_milestones(task_id: str, 列表) -> dict:
    """给任务**补新里程碑**（由旁路大模型裁定后调用）。去重；计扩展次数。"""
    d = _load()
    t = next((x for x in _all(d) if x.get("id") == task_id), None)
    if not t:
        return {"success": False, "error": f"没有该任务：{task_id}"}
    if t.get("状态") != STATUS_ACTIVE:
        return {"success": True, "新增": [], "noop": "已了结"}
    existing = {m.get("项") for m in (t.get("里程碑") or [])}
    added = []
    for x in (列表 or []):
        name = (x.get("项") if isinstance(x, dict) else str(x)).strip()
        if name and name not in existing:
            t.setdefault("里程碑", []).append({"项": name, "状态": "未完成"})
            existing.add(name)
            added.append(name)
    t["扩展次数"] = int(t.get("扩展次数", 0) or 0) + 1
    t["更新于"] = _now_str()
    _save(d)
    return {"success": True, "新增": added, "任务": _player_card(t)}


def _match_milestone(t: dict, text: str) -> str:
    """把模型给的里程碑文字匹配到任务里的里程碑（剥序号、取包含）。"""
    want = _clean_ms(text)
    if not want:
        return ""
    for ms in t.get("里程碑") or []:
        if ms.get("项") == want:
            return want
    for ms in t.get("里程碑") or []:
        a = _clean_ms(ms.get("项", ""))
        if a and (a in want or want in a):
            return ms.get("项")
    return ""


def _clean_ms(s: str) -> str:
    import re
    return re.sub(r"^\s*[\d一二三四五六七八九十]+[.、）)]\s*", "", str(s or "")).strip()


def complete(task_id: str, 结果: str = "") -> dict:
    """完成任务：静默发技能点（GM 不知道）+ 归档。"""
    d = _load()
    t = next((x for x in _all(d) if x.get("id") == task_id), None)
    if not t:
        return {"success": False, "error": f"没有该任务：{task_id}"}
    if t.get("状态") != STATUS_ACTIVE:
        return {"success": True, "任务": _player_card(t), "noop": "已了结"}
    for ms in t.get("里程碑") or []:
        ms["状态"] = "已完成"
    t["状态"] = STATUS_DONE
    t["结果"] = (结果 or "").strip() or t.get("结果")
    t["归档于"] = _now_str()
    t["更新于"] = t["归档于"]
    _save(d)
    reward = _grant_reward("任务完成")
    return {"success": True, "任务": _player_card(t), "奖励": reward}


def expire(task_id: str, 结果: str = "", 世界推进: str = "") -> dict:
    """过期归档（由 DDL 裁定调用）。"""
    d = _load()
    t = next((x for x in _all(d) if x.get("id") == task_id), None)
    if not t:
        return {"success": False, "error": f"没有该任务：{task_id}"}
    if t.get("状态") != STATUS_ACTIVE:
        return {"success": True, "任务": _player_card(t), "noop": "已了结"}
    t["状态"] = STATUS_EXPIRED
    t["结果"] = (结果 or "").strip()
    t["世界推进"] = (世界推进 or "").strip()
    t["归档于"] = _now_str()
    t["更新于"] = t["归档于"]
    _save(d)
    return {"success": True, "任务": _player_card(t)}


def _grant_reward(reason: str) -> dict:
    try:
        from tools.核心 import skill_tree
        n = int((config().get("奖励") or {}).get("技能点", 1))
        return skill_tree.add_point(n, reason) if n else {}
    except Exception as e:   # 奖励失败不影响任务了结
        return {"success": False, "error": str(e)}


# ------------------------------------------------------------
# 时限
# ------------------------------------------------------------
def due(now_sec: int | None = None) -> list[dict]:
    """已到时限、仍进行中的任务。"""
    now = clock.seconds() if now_sec is None else int(now_sec)
    out = []
    for t in active():
        dl = (t.get("时限") or {}).get("游戏秒")
        if isinstance(dl, int) and dl <= now:
            out.append(t)
    return out


def remaining_text(t: dict) -> str:
    """剩余时限的可读文本（给前端倒计时/提示）。"""
    dl = (t.get("时限") or {}).get("游戏秒")
    if not isinstance(dl, int):
        return ""
    left = dl - clock.seconds()
    if left <= 0:
        return "已到期"
    ke = max(0, left // (15 * 60))
    return f"约 {ke} 刻"


# ------------------------------------------------------------
# 视图（玩家 / GM）
# ------------------------------------------------------------
def _player_card(t: dict) -> dict:
    return {
        "id": t.get("id"),
        "标题": t.get("标题"),
        "类型": t.get("类型"),
        "状态": t.get("状态"),
        "描述": t.get("描述"),
        "委托人": t.get("委托人"),
        "里程碑": [{"项": m.get("项"), "状态": m.get("状态")} for m in (t.get("里程碑") or [])],
        "时限": {"显示": (t.get("时限") or {}).get("显示"),
                 "游戏秒": (t.get("时限") or {}).get("游戏秒"),
                 "文本": (t.get("时限") or {}).get("文本")},
        "结果": t.get("结果"),
        "创建于": t.get("创建于"),
        "归档于": t.get("归档于"),
    }


def player_view() -> dict:
    """给前端的完整视图：进行中 + 已了结（不含隐藏字段）。"""
    items = _all()
    return {
        "进行中": [_player_card(t) for t in items if t.get("状态") == STATUS_ACTIVE],
        "已了结": [_player_card(t) for t in items if t.get("状态") != STATUS_ACTIVE],
    }


def gm_view() -> list[dict]:
    """给 GM 的最小投影：只进行中的可见任务（不含失败后果等隐藏字段）。"""
    out = []
    for t in active():
        if not t.get("可见", True):
            continue
        out.append({
            "标题": t.get("标题"),
            "描述": t.get("描述"),
            "委托人": t.get("委托人"),
            "里程碑": [m.get("项") for m in (t.get("里程碑") or [])],
            "时限": (t.get("时限") or {}).get("显示"),
        })
    return out


def by_ids(ids) -> list[dict]:
    idset = {str(i) for i in (ids or [])}
    return [t for t in active() if t.get("id") in idset]


def card(t: dict) -> dict:
    """公开入口：单任务的玩家投影。"""
    return _player_card(t)


# ------------------------------------------------------------
# 过期提醒（给 GM 的下一轮叙事）
# ------------------------------------------------------------
def pending_notes() -> list[tuple]:
    """新过期、尚未告知 GM 的任务 → [(id, 文本)]。"""
    out = []
    for t in _all():
        if t.get("状态") == STATUS_EXPIRED and not t.get("已告知"):
            out.append((t.get("id"),
                        f"【任务过期】《{t.get('标题')}》：{t.get('结果') or '（已了结）'}"))
    return out


def mark_told(ids) -> None:
    """标记这些过期任务已注入给 GM（下一轮不再重复）。"""
    idset = {str(i) for i in (ids or [])}
    d = _load()
    hit = False
    for t in _all(d):
        if t.get("id") in idset and not t.get("已告知"):
            t["已告知"] = True
            hit = True
    if hit:
        _save(d)
