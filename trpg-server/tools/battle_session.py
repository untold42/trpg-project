# -*- coding: utf-8 -*-
"""
battle_session.py
=================
服务端「当前战斗」的单例管理：工具 `start_battle` 开局、`/battle/*` 路由推进与收尾。

- 同一时刻只允许一场战斗（`_RUNNER`）。
- 战斗结束 → 写回 `状态.json`（生命 / 精力 / 伤势）→ 清空 → 返回**结果摘要**
  （由 `main.py` 注入给主持人叙事后效）。
- 战斗设置（思路判定模型）在 `tools/battle_settings.py`，本模块不管。

设计见 `trpg-world/战斗系统.md` §9。
"""

from __future__ import annotations

import re
import threading
from pathlib import Path

from tools import battle as B
from tools import battle_runner as R
from tools import ui_sim
from tools.state_manager import state as game_state
from tools.ui_events import UI_EVENTS_KEY, ui_event

_ROOT = Path(__file__).resolve().parent.parent.parent
_TIER_MD = _ROOT / "trpg-world" / "江湖势力" / "武力排名.md"

_lock = threading.RLock()
_RUNNER: R.BattleRunner | None = None
_META: dict = {}
_busy = False   # 防重入：一次只允许一个 submit 在算（否则并发 advance 会狂调小模型）
_LAST_MUSIC = ""  # 上一场战斗曲，用于避免重复


# ------------------------------------------------------------
# 敌我名单 → 参战者
# ------------------------------------------------------------
def _tier_map() -> dict:
    """解析 `武力排名.md` → {角色名: 梯度}（带缓存）。"""
    cached = getattr(_tier_map, "_cache", None)
    try:
        mtime = _TIER_MD.stat().st_mtime
    except OSError:
        return {}
    if cached and cached[0] == mtime:
        return cached[1]
    out, tier = {}, ""
    try:
        text = _TIER_MD.read_text(encoding="utf-8")
    except OSError:
        return {}
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"^##+\s*(T[0-7])", line)
        if m:
            tier = m.group(1)
            continue
        if line.startswith("|") and tier:
            cells = [c.strip() for c in line.strip("|").split("|")]
            name = cells[0] if cells else ""
            if not name or name == "角色" or set(name) <= {"-", " ", ":"}:
                continue
            name = re.sub(r"[（(].*?[)）]", "", name).strip()
            if name:
                out.setdefault(name, tier)
    _tier_map._cache = (mtime, out)
    return out


def _build(spec, side: str, tier_map: dict) -> list:
    out = []
    for e in spec or []:
        if isinstance(e, str):
            e = {"名字": e}
        name = (e.get("名字") or "").strip()
        if not name:
            continue
        tier = e.get("梯度") or tier_map.get(name) or "T5"
        五行 = e.get("五行", "")
        if 五行 == "无":
            五行 = ""
        out.append(B.npc_combatant(
            name, side, 梯度=tier, 兵器=e.get("兵器", "剑法"), 五行=五行,
            武器类型=e.get("武器类型"), 生命=e.get("生命"), 招式=e.get("招式"),
        ))
    return out


# ------------------------------------------------------------
# 生命周期
# ------------------------------------------------------------
def _wrap(st: dict) -> dict:
    st = dict(st)
    st["active"] = True
    st["缘由"] = _META.get("缘由", "")
    st["音乐"] = _META.get("音乐", "")
    st["模拟"] = bool(_META.get("模拟"))   # 供 main.py 判断：模拟战不得注入游戏叙事
    return st


def demo_terrain() -> dict:
    """模拟战斗的演示地形（目前仅视觉 + 房屋阻挡）：一条河 + 几栋房 + 几棵树。"""
    t = {}
    for x in range(3, 7):
        t[(x, 2)] = "河流"
    for xy in ((4, 0), (4, 1), (7, 3)):
        t[xy] = "房屋"
    for xy in ((0, 0), (0, 5), (9, 5)):
        t[xy] = "树"
    return t


def start(敌人, 友方=None, 缘由: str = "", 模拟: bool = False, 地形: dict = None) -> dict:
    """建立战斗并推进到「等玩家输入」或结束。`模拟=True` 时结束不回写玩家状态。"""
    global _RUNNER, _META, _LAST_MUSIC
    with _lock:
        tm = _tier_map()
        enemies = _build(敌人, "敌方", tm)
        allies = _build(友方, "友方", tm)
        if not enemies:
            return {"active": False, "error": "没有有效的敌人"}
        if 地形 is None and 模拟:
            地形 = demo_terrain()          # 模拟战斗默认带演示地形（视觉）
        b = B.new_battle(enemies=enemies, allies=allies, 地形=地形)
        r = R.BattleRunner(b)
        st = r.start()
        _RUNNER = r
        loc = (game_state.load("基本信息", {}) or {}).get("位置", {}).get("地点", "")
        names = [c["名字"] for c in enemies]
        context = ("敌方：" + "、".join(
                    c["名字"] + (f"({c.get('梯度','')})" if c.get("梯度") else "")
                    for c in enemies)
                   + f"；我方：梁峰等 {1 + len(allies)} 人；"
                     f"地点：{loc or '未知'}；缘由：{缘由 or '未注明'}。")
        music = ""
        try:
            music = ui_sim.battle_track_model(context, present=names,
                                              location=loc, avoid=_LAST_MUSIC)
        except Exception:
            music = ""
        if not music:   # 回退：代码选曲（boss 绑定优先 + 通用随机）
            music = ui_sim.battle_track_for(present=names, location=loc, avoid=_LAST_MUSIC)
        _LAST_MUSIC = music
        _META = {"缘由": 缘由 or "", "模拟": bool(模拟), "音乐": music}
        return _wrap(st)


def start_battle(敌人, 友方=None, 缘由: str = "", 地形: dict = None) -> dict:
    """LLM 工具：判定开战 → 建立战斗并产出 `kind:"battle"` UI 事件。"""
    st = start(敌人, 友方, 缘由, 地形=地形)
    if not st.get("active"):
        return {"success": False, "error": st.get("error", "开战失败")}
    return {
        "success": True,
        "message": "战斗已开始。请只叙述「杀机骤起 / 剑已出鞘」一两句即止，"
                   "不要替玩家决定回合内动作——玩家会在战斗界面里操作。",
        UI_EVENTS_KEY: [ui_event("battle", **st)],
    }


def active() -> bool:
    return _RUNNER is not None and not _RUNNER.b.ended


def roster() -> dict:
    """模拟战斗可选名单（来自 `武力排名.md`）。"""
    tm = _tier_map()
    items = sorted(tm.items(), key=lambda kv: (kv[1], kv[0]))
    return {"角色": [{"名字": n, "梯度": t} for n, t in items]}


def state() -> dict:
    if _RUNNER is None:
        return {"active": False}
    return _wrap(_RUNNER.state())


def submit(action: dict, thought: str = "") -> dict:
    """推进玩家一个动作；战斗结束时自动收尾并把「结果」附在返回值里。

    防重入：若上一次提交还在结算（小模型/代码），直接返回当前状态，不叠加。
    """
    global _busy
    if _RUNNER is None:
        return {"active": False}
    with _lock:
        if _busy:
            st = _wrap(_RUNNER.state())
            st["忙"] = True
            return st
        _busy = True
    try:
        st = _wrap(_RUNNER.submit(action, thought))
        if _RUNNER is not None and _RUNNER.b.ended:
            st["结果"] = _finalize()
        return st
    finally:
        _busy = False


def _finalize() -> dict:
    """战斗结束：写回玩家状态、汇总结果、清空当前战斗。"""
    global _RUNNER, _META
    r = _RUNNER
    if r is None:
        return {}
    b = r.b
    p = r._player
    if p is not None and not _META.get("模拟"):   # 模拟战斗不回写玩家状态
        st = game_state.load("状态", {}) or {}
        st["生命值"] = int(p["生命"])
        st["精力值"] = int(p["内力"])
        ratio = p["生命"] / max(1, p["生命上限"])
        st["伤势"] = ("濒死" if p["生命"] <= 0 else
                      "重伤" if ratio <= 0.3 else
                      "轻伤" if ratio < 1.0 else "无")
        game_state.save("状态", st)
    summary = {
        "胜方": b.winner,
        "原因": b.result_reason,
        "玩家": ({"生命": p["生命"], "生命上限": p["生命上限"],
                  "内力": p["内力"], "内力上限": p["内力上限"]} if p else None),
        "倒下": [c["名字"] for c in b.cs if not c.get("存活")],
        "撤离": [c["名字"] for c in b.cs if c.get("已撤离")],
        "约定撤退": [c["名字"] for c in b.cs if c.get("约定撤退")],
        "缘由": _META.get("缘由", ""),
    }
    _RUNNER = None
    _META = {}
    return summary


def clear():
    """放弃/重置时清空当前战斗（不写回状态）。"""
    global _RUNNER, _META
    with _lock:
        _RUNNER = None
        _META = {}
