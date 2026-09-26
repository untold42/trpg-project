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

import functools
import json
import re
import threading
import time
import uuid
from pathlib import Path

from tools.核心.state_manager import state
from tools.核心.game_clock import (
    clock, SECONDS_PER_SHICHEN, civil_from_seconds, render_civil,
)

STATE_KEY = "任务"

SERVER_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_FILE = SERVER_DIR / "配置" / "任务.json"

DEFAULT_CONFIG = {"奖励": {"技能点": 1}, "里程碑扩展上限": 3}

STATUS_ACTIVE = "进行中"
STATUS_DONE = "已完成"
STATUS_EXPIRED = "已过期"

_config_cache: dict = {}

# 读-改-写整体串行化：`quest_sim`（后台 worker）与 `quest_arbiter`（后台裁定）
# 会在不同线程同时改 任务.json；`state.load/save` 只各自加锁，中间会丢更新。
_lock = threading.RLock()


def _locked(fn):
    """让整个「读 → 改 → 写」持有同一把锁（RLock，可重入）。"""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with _lock:
            return fn(*args, **kwargs)
    return wrapper


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
@_locked
def materialize_deadlines() -> int:
    """给**手写在 `任务.json`** 里的任务补绝对时限：
    有 `时限时辰`（相对）而无 `时限.游戏秒`（绝对）→ 按当前时钟换算。

    幂等（换算过就不再变）；开局由 main 调一次。返回补了几条。
    """
    d = _load()
    n = 0
    for t in _all(d):
        dl = t.get("时限") if isinstance(t.get("时限"), dict) else {}
        if isinstance(dl.get("游戏秒"), int):
            continue
        hours = t.get("时限时辰") or dl.get("剩余时辰") or 24
        t["时限"] = _deadline(hours)
        if t.get("时限文本"):
            t["时限"]["文本"] = t["时限文本"]
        n += 1
    if n:
        _save(d)
    return n


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


@_locked
def add(标题: str, 描述: str = "", 委托人: str = "",
        里程碑: list | None = None, 时限文本: str = "", 时限时辰: int = 1,
        来源: str = "任务裁定", 失败后果: str = "",
        真相: str = "", 结局: str = "", 知情者: list | None = None,
        揭示节奏: str = "") -> dict:
    """新建一个任务（由 add 裁定 / 手写调用）。**不分主线支线**；大目标用里程碑。

    `真相` / `结局` / `知情者` / `揭示节奏`：**仅 GM 可见**的客观事实（在 add 那一刻定死），
    不进玩家视图。`结局` = 预定走向；`失败后果` = 未完成时世界怎么变（DDL 用）。
    """
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
        "状态": STATUS_ACTIVE,
        "可见": True,
        "描述": (描述 or "").strip(),
        "委托人": (委托人 or "").strip(),
        "里程碑": tasks,
        "时限": _deadline(时限时辰),
        "失败后果": (失败后果 or "").strip(),
        "真相": (真相 or "").strip(),
        "结局": (结局 or "").strip(),
        "知情者": [str(x).strip() for x in (知情者 or []) if str(x).strip()],
        "揭示节奏": (揭示节奏 or "").strip(),
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


@_locked
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


@_locked
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
    """把模型给的里程碑匹配到任务里的里程碑。

    模型常只回**序号**（"4" / "第 4 条" / "4."），也常回带序号的原文（"4.再访崔家…"）
    或纯原文——三种都要能接上（否则真做到了的里程碑会因格式不匹配而被丢掉）。
    """
    ms_list = t.get("里程碑") or []
    raw = str(text or "").strip()
    if not raw:
        return ""
    idx = _milestone_index(raw)
    if idx and 1 <= idx <= len(ms_list):
        return ms_list[idx - 1].get("项")
    want = _clean_ms(raw)
    if not want:
        return ""
    for ms in ms_list:
        if ms.get("项") == want:
            return want
    for ms in ms_list:
        a = _clean_ms(ms.get("项", ""))
        if a and (a in want or want in a):
            return ms.get("项")
    return ""


_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _cn_num(s: str) -> int:
    """中文数字（一~九十九）→ int；解析失败返回 0。"""
    if not s:
        return 0
    if "十" in s:
        a, _, b = s.partition("十")
        tens = _CN_DIGITS.get(a, 1) if a else 1
        ones = _CN_DIGITS.get(b, 0) if b else 0
        return tens * 10 + ones
    total = 0
    for ch in s:
        if ch not in _CN_DIGITS:
            return 0
        total = total * 10 + _CN_DIGITS[ch]
    return total


def _milestone_index(s: str) -> int:
    """字符串**整体**就是一个序号时（"4"/"第 4 条"/"4."/"④"）返回该序号，否则 0。"""
    s = str(s or "").strip()
    if len(s) == 1 and "\u2460" <= s <= "\u2473":   # ①~⑳
        return ord(s) - 0x2460 + 1
    m = re.fullmatch(
        r"(?:第\s*)?([0-9０-９]+|[一二三四五六七八九十两]+)\s*(?:条|项|个|、|\.|。|\)|）)?", s)
    if not m:
        return 0
    tok = m.group(1)
    if tok.isdigit():
        return int(tok)
    if all("０" <= c <= "９" for c in tok):
        return int("".join(str(ord(c) - ord("０")) for c in tok))
    return _cn_num(tok)


def _clean_ms(s: str) -> str:
    return re.sub(r"^\s*[\d一二三四五六七八九十]+[.、）)]\s*", "", str(s or "")).strip()


@_locked
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


@_locked
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


def truth_view(ids=None) -> list[dict]:
    """给 GM 的**事件真相块**：仅**进行中**任务；传 `ids` 时只取这些（= 玩家追踪的）。

    **永不发玩家**。字段：标题 / 真相 / 结局 / 知情者 / 揭示节奏。
    """
    tasks = by_ids(ids) if ids is not None else active()
    out = []
    for t in tasks:
        if not any(t.get(k) for k in ("真相", "结局", "知情者", "揭示节奏")):
            continue
        out.append({
            "标题": t.get("标题"),
            "真相": t.get("真相"),
            "结局": t.get("结局"),
            "知情者": t.get("知情者") or [],
            "揭示节奏": t.get("揭示节奏"),
        })
    return out


# ------------------------------------------------------------
# 过期提醒（给 GM 的下一轮叙事）
# ------------------------------------------------------------
def pending_notes() -> list[tuple]:
    """新了结（已完成 / 已过期）、尚未告知 GM 的任务 → [(id, 文本)]。

    文本写成**世界事实**（不暴露任务系统）——GM 只需知道世界变了 / 这事了了。
    """
    out = []
    for t in _all():
        st = t.get("状态")
        if st == STATUS_ACTIVE or t.get("已告知"):
            continue
        res = (t.get("结果") or "").strip()
        if st == STATUS_DONE:
            txt = f"【事情了结】《{t.get('标题')}》" + (f"：{res}" if res else "已了结。")
        else:
            txt = "【世界变动】" + (res or "有件事已无转机，不了了之。")
        out.append((t.get("id"), txt))
    return out


@_locked
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
