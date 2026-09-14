# -*- coding: utf-8 -*-
"""
battle.py
=========
战斗数值核心（**纯代码，不调用任何 LLM**）。设计见 `trpg-world/战斗系统.md`。

职责：
  - 网格（10×6，切比雪夫距离）+ 站位 / 移动 / 射程
  - 参战者构建（玩家读 `状态.json` / `属性.json` / `招式表.json`；NPC 由「梯度」推导）
  - 动作结算：移动 / 舞剑 / 防守 / 技能（五行）/ 交流 / 撤退
  - 命中 / 伤害 / 五行克制 / 位置（背袭·夹击）
  - Buff（流血 / 中毒 / … / 蓄力 / 穿甲）
  - 回合 · 阶段 bookkeeping、死亡与胜负判定
  - 结构化战斗日志（前端滚动用）+ JSON 序列化

分工（承总纲第 5 条「硬事实由代码裁决」）：
  AI 决策与「思路」修正判定在 `tools/battle_ai.py`；本模块只吃「动作 + 修正值(thought_mod)」，
  产出确定性的结算结果。**模型永远不会改这里的任何数字。**
"""

from __future__ import annotations

import copy
import json
import math
import random
from pathlib import Path

from tools.state_manager import state

# ------------------------------------------------------------
# 路径 / 常量
# ------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent.parent
_SKILL_TABLE_PATH = _ROOT / "trpg-world" / "招式表.json"

GRID_W, GRID_H = 10, 6
ALLIES_START_X = (0, 1)     # 友方起始列（左）
ENEMIES_START_X = (8, 9)    # 敌方起始列（右）

SIDES = ("友方", "敌方")

#: 五行相克：键克值
WUXING_KE = {"水": "火", "火": "金", "金": "木", "木": "土", "土": "水"}

#: 梯度 → 战力系数（T2 = 1.0）
TIER_COEF = {
    "T0": 2.00, "T1": 1.40, "T2": 1.00, "T3": 0.80,
    "T4": 0.60, "T5": 0.40, "T6": 0.25, "T7": 0.15,
}

#: 动作枚举
ACTIONS = ["移动", "舞剑", "防守", "技能", "交流", "撤退"]

#: AI 侧「移动」枚举（相对位移）
MOVE_ENUM = ["原地", "前进1", "后退1", "侧移1", "斜移1"]

#: 命中档位 → 伤害系数
def _hit_tier(最终: int):
    if 最终 < 20:
        return None, 0.0           # 未命中
    if 最终 < 60:
        return "命中", 0.8
    if 最终 < 90:
        return "命中", 1.0
    return "会心", 1.5

#: Buff 定义。效果键：
#:   命中(int, 加到命中判定) / 伤害(float, 攻方输出倍率增量) / 受伤(float, 守方承伤倍率增量)
#:   减伤(float, 0.3=减伤30%) / 每回合生命(int, DoT×层数) / 会心阈值(int)
#:   跳过回合(bool) / 内力回复(bool) / 技能伤害(float) / 治疗(float)
BUFF_DEFS = {
    "流血":   {"类型": "减益", "可叠层": True,  "持续": 3, "每回合生命": -3, "伤害": -0.10},
    "中毒":   {"类型": "减益", "可叠层": True,  "持续": 3, "每回合生命": -2, "治疗": 0.5},
    "内伤":   {"类型": "减益", "可叠层": False, "持续": 0, "内力回复": False, "技能伤害": -0.20},
    "破绽":   {"类型": "减益", "可叠层": False, "持续": 2, "受伤": 0.20},
    "眩晕":   {"类型": "减益", "可叠层": True,  "持续": 1, "跳过回合": True},
    "护体":   {"类型": "增益", "可叠层": False, "持续": 3, "减伤": 0.30},
    "士气":   {"类型": "增益", "可叠层": False, "持续": 2, "命中": 10, "伤害": 0.10},
    "动摇":   {"类型": "减益", "可叠层": False, "持续": 2, "命中": -10, "伤害": -0.10},
    "致盲":   {"类型": "减益", "可叠层": False, "持续": 2, "命中": -25},
    "洞察":   {"类型": "增益", "可叠层": False, "持续": 2, "命中": 30, "会心阈值": -15},
    # 特殊：蓄力为水行层数（永久，直到被伤害招式消耗）；穿甲为一次性（不入此表）
    "蓄力":   {"类型": "增益", "可叠层": True,  "持续": -1},
}

#: 五行系数
KE_ADV, KE_DIS = 1.3, 0.8

#: 位置系数
POS_BACK = {"命中": 15, "伤害": 1.30}   # 背袭
POS_FLANK = {"命中": 8, "伤害": 1.15}   # 夹击

#: 武器类型 → 伤害系数 / 命中附加 / 会心附加
#:   利器（剑/刀/暗器）：伤害高，命中即「流血」
#:   钝器（棍/锤/鞭）：伤害中，会心致「眩晕」
#:   徒手（拳掌）：伤害低，无附加
WEAPON_KINDS = {
    "利器": {"伤害": 1.25, "命中效果": "流血", "会心效果": None},
    "钝器": {"伤害": 1.00, "命中效果": None,   "会心效果": "眩晕"},
    "徒手": {"伤害": 0.90, "命中效果": None,   "会心效果": None},
}

#: 由「兵器」属性推导武器类型（未显式给「武器类型」时）
_WEAPON_BY_STAT = {"剑法": "利器", "暗器": "利器", "拳掌": "徒手"}

#: 流血最多叠到几层（利器每命中一次叠一层）
BLEED_MAX = 3


def weapon_kind(c: dict) -> str:
    """参战者的武器类型（利器/钝器/徒手）。"""
    k = c.get("武器类型")
    if k in WEAPON_KINDS:
        return k
    return _WEAPON_BY_STAT.get(c.get("兵器", ""), "徒手")


def _skill_table() -> dict:
    """读 `trpg-world/招式表.json`（带缓存）。失败返回空结构。"""
    cached = getattr(_skill_table, "_cache", None)
    try:
        mtime = _SKILL_TABLE_PATH.stat().st_mtime
    except OSError:
        return {"普通攻击": {}, "招式": {}}
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        data = json.loads(_SKILL_TABLE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, json.JSONDecodeError):
        data = {}
    data.setdefault("普通攻击", {})
    data.setdefault("招式", {})
    _skill_table._cache = (mtime, data)
    return data


def normal_attack() -> dict:
    """普通攻击（舞剑）定义。"""
    return _skill_table().get("普通攻击") or {}


def get_skill(name: str) -> dict | None:
    """按名取招式定义（补上「名称」）；没有返回 None。"""
    d = (_skill_table().get("招式") or {}).get(name)
    if d is None:
        return None
    return {**d, "名称": d.get("名称", name)}


# ------------------------------------------------------------
# 网格
# ------------------------------------------------------------
def in_board(x: int, y: int) -> bool:
    return 0 <= x < GRID_W and 0 <= y < GRID_H


def distance(a, b) -> int:
    """切比雪夫距离（8 向，斜走与直走同价）。a/b 为参战者 dict 或 (x,y)。"""
    ax, ay = _cell(a)
    bx, by = _cell(b)
    return max(abs(ax - bx), abs(ay - by))


def _cell(c):
    if isinstance(c, dict):
        return c["格"][0], c["格"][1]
    return c[0], c[1]


def move_range(combatant) -> int:
    """移动力 = 1 + floor(轻功/30)。"""
    return 1 + int(combatant["属性"].get("轻功", 0)) // 30


# ------------------------------------------------------------
# 参战者构建
# ------------------------------------------------------------
def _tier_coef(tier: str) -> float:
    return TIER_COEF.get((tier or "").strip(), 1.0)


def player_combatant(x: int = None, y: int = None) -> dict:
    """从 状态/属性/招式表 构建玩家的参战者（梁峰）。"""
    st = state.load("状态", {}) or {}
    ab = state.load("属性", {}) or {}
    basic = ab.get("基础属性", {}) or {}
    weapon = max(("剑法", "拳掌", "暗器"), key=lambda k: basic.get(k, 0) or 0)

    c = {
        "名字": (state.load("基本信息", {}) or {}).get("人物", {}).get("姓名", "梁峰"),
        "阵营": "友方",
        "是玩家": True,
        "格": [x if x is not None else ALLIES_START_X[0] + 1, y if y is not None else GRID_H // 2],
        "朝向": "右",
        "生命": int(st.get("生命值", 1)),
        "生命上限": int(st.get("生命上限", st.get("生命值", 1))),
        "内力": int(st.get("精力值", 0)),
        "内力上限": int(st.get("精力上限", 0)),
        "属性": {
            "剑法": int(basic.get("剑法", 0)),
            "拳掌": int(basic.get("拳掌", 0)),
            "暗器": int(basic.get("暗器", 0)),
            "轻功": int(basic.get("轻功", 0)),
        },
        "兵器": weapon,
        "武器类型": "利器",   # 五行剑 → 利器（伤害高、命中即流血）
        "梯度": (state.load("基本信息", {}) or {}).get("人物", {}).get("梯度", "T2"),
        "招式": _player_skills(ab),
        "buff": [],
        "已行动": False,
        "防守": False,
        "跳过回合": False,
        "约定撤退": False,
        "存活": True,
        "已撤离": False,
    }
    return c


def _player_skills(属性: dict) -> list[str]:
    """玩家可用的五行招式：熟练度 ≥ 30 的行，其招式且招式表里存在。"""
    out = []
    for 行, data in (属性.get("五行剑") or {}).items():
        if not isinstance(data, dict) or 行.startswith("_"):
            continue
        try:
            prof = int(data.get("熟练度", 0))
        except (TypeError, ValueError):
            prof = 0
        if prof < 30:
            continue
        for s in data.get("招式", []) or []:
            name = (s or {}).get("名称") if isinstance(s, dict) else None
            if name and get_skill(name):
                out.append(name)
    return out


def npc_combatant(名字: str, 阵营: str, 梯度: str = "T5", 兵器: str = "剑法",
                  五行: str = "", x: int = None, y: int = None,
                  生命: int = None, 招式: list = None, 武器类型: str = None) -> dict:
    """由「梯度」推导一个 NPC 参战者（可显式覆盖生命/兵器等）。"""
    k = _tier_coef(梯度)
    hp = int(生命 if 生命 is not None else round(60 * k + 25))
    stats = {
        "剑法": round(70 * k + 20) if 兵器 == "剑法" else round(30 * k + 10),
        "拳掌": round(70 * k + 20) if 兵器 == "拳掌" else round(30 * k + 10),
        "暗器": round(70 * k + 20) if 兵器 == "暗器" else round(20 * k + 5),
        "轻功": round(50 * k + 15),
    }
    if 阵营 == "友方":
        dx = ALLIES_START_X
    else:
        dx = ENEMIES_START_X
    c = {
        "名字": 名字, "阵营": 阵营, "是玩家": False,
        "格": [x if x is not None else dx[-1] if 阵营 == "友方" else dx[0],
               y if y is not None else GRID_H // 2],
        "朝向": "右" if 阵营 == "友方" else "左",
        "生命": hp, "生命上限": hp,
        "内力": round(70 * k + 30), "内力上限": round(70 * k + 30),
        "属性": stats, "兵器": 兵器, "武器类型": 武器类型, "五行": 五行, "梯度": 梯度,
        "招式": list(招式 or []), "buff": [],
        "已行动": False, "防守": False, "跳过回合": False,
        "约定撤退": False, "存活": True, "已撤离": False,
    }
    return c


# ------------------------------------------------------------
# Buff 计算
# ------------------------------------------------------------
def _buff_mod(c: dict, key: str) -> float:
    """累加某个数字型 buff 效果（不乘层数）。"""
    total = 0.0
    for b in c.get("buff", []):
        eff = BUFF_DEFS.get(b.get("名称"), {})
        v = eff.get(key)
        if isinstance(v, (int, float)):
            total += v
    return total


def _has_buff(c: dict, name: str) -> bool:
    return any(b.get("名称") == name for b in c.get("buff", []))


def apply_buff(c: dict, name: str, 层数: int = 1, 回合: int = None) -> bool:
    """施加 buff。可叠层的累加层数，其余取「刷新持续」。返回是否生效。"""
    d = BUFF_DEFS.get(name)
    if not d:
        return False
    dur = d.get("持续", 2) if 回合 is None else 回合
    for b in c.get("buff", []):
        if b.get("名称") == name:
            if d.get("可叠层"):
                b["层数"] = b.get("层数", 1) + 层数
            b["剩余回合"] = max(b.get("剩余回合", 0), dur)
            return True
    c.setdefault("buff", []).append({"名称": name, "层数": 层数, "剩余回合": dur})
    return True


def _dot_total(c: dict) -> int:
    total = 0
    for b in c.get("buff", []):
        v = BUFF_DEFS.get(b.get("名称"), {}).get("每回合生命")
        if isinstance(v, int):
            total += v * b.get("层数", 1)
    return total


# ------------------------------------------------------------
# 位置（背袭 / 夹击）
# ------------------------------------------------------------
def _facing_dx(c: dict) -> int:
    return 1 if c.get("阵营") == "友方" else -1


def _position_mod(attacker, defender, battle) -> dict:
    """返回 {"命中":int, "伤害":float, "类型":str}。"""
    ax, ay = attacker["格"]
    dx, dy = defender["格"]
    # 背袭：攻击者位于守方「背后」方向相邻
    back_x = dx - _facing_dx(defender)  # 守方背后那一格（朝向的反方向）
    if distance(attacker, defender) <= 1 and ax == back_x and abs(ay - dy) <= 1:
        return {"命中": POS_BACK["命中"], "伤害": POS_BACK["伤害"], "类型": "背袭"}
    # 夹击：守方另一侧（相对攻击者）有攻击者的队友且相邻
    for o in battle.alive():
        if o is attacker or o["阵营"] != attacker["阵营"]:
            continue
        if distance(o, defender) <= 1:
            ox, oy = o["格"]
            if (ox - dx) * (ax - dx) + (oy - dy) * (ay - dy) < 0:
                return {"命中": POS_FLANK["命中"], "伤害": POS_FLANK["伤害"], "类型": "夹击"}
    return {"命中": 0, "伤害": 1.0, "类型": "正面"}


# ------------------------------------------------------------
# 战斗
# ------------------------------------------------------------
class Battle:
    """一场 n vs n 战斗的完整状态与结算。"""

    def __init__(self, combatants: list, rng: random.Random = None):
        self.cs: list[dict] = combatants
        self.round = 0
        self.first_side = None
        self.current_side = None
        self.expected: dict = {}     # 大模型判定/小模型决策给出的修正(按参战者名)
        # 位置修正由 perform 参数传入（thought_mod）
        self.log: list[dict] = []
        self.ended = False
        self.winner = None
        self.result_reason = ""
        self.rng = rng or random.Random()

    def clone(self) -> "Battle":
        """深拷贝一份，用于「一回合前瞻」模拟：独立 rng、不写主日志。

        注意：模拟会推进克隆体的 rng，不影响真战场（各候选从同一 rng 状态起跑，比较公平）。
        """
        b = Battle.__new__(Battle)
        b.cs = copy.deepcopy(self.cs)
        b.round = self.round
        b.first_side = self.first_side
        b.current_side = self.current_side
        b.expected = {}
        b.log = []
        b.ended = self.ended
        b.winner = self.winner
        b.result_reason = self.result_reason
        b.rng = random.Random()
        b.rng.setstate(self.rng.getstate())
        return b

    # ---- 查询 ----
    def get(self, name: str) -> dict | None:
        for c in self.cs:
            if c["名字"] == name:
                return c
        return None

    def alive(self) -> list[dict]:
        return [c for c in self.cs if c.get("存活") and not c.get("已撤离")]

    def side_members(self, side: str) -> list[dict]:
        return [c for c in self.alive() if c["阵营"] == side]

    def cell_occupied(self, x: int, y: int):
        for c in self.alive():
            if c["格"] == [x, y]:
                return c
        return None

    def turn_order(self) -> list[dict]:
        return sorted(self.alive(), key=lambda c: c["属性"].get("轻功", 0), reverse=True)

    def _side_of(self, c) -> str:
        return c["阵营"]

    # ---- 回合 / 阶段 ----
    def decide_first_side(self):
        """两侧「轻功最高者 + d100」比大小定先手。"""
        best = {}
        for side in SIDES:
            members = self.side_members(side)
            if not members:
                continue
            top = max(members, key=lambda c: c["属性"].get("轻功", 0))
            best[side] = top["属性"].get("轻功", 0) + self.rng.randint(1, 100)
        if not best:
            self.first_side = None
            return
        self.first_side = max(best, key=best.get)
        self.append_log({"类型": "先手", "文本": f"先手方：{self.first_side}"})

    def begin_round(self):
        """回合开始：定先手、DoT、内力回复、重置本回合标记（含眩晕判定）。"""
        self.round += 1
        self.decide_first_side()
        for c in self.alive():
            c["已行动"] = False
            c["防守"] = False
            c["跳过回合"] = _has_buff(c, "眩晕")
            # DoT
            dot = _dot_total(c)
            if dot:
                self._damage(c, -dot, "dot")
            if not c["存活"]:
                continue
            # 内力回复（内伤：不回复）
            if not _has_buff(c, "内伤"):
                regen = round(c["内力上限"] * 0.05)
                c["内力"] = min(c["内力上限"], c["内力"] + regen)
        self._check_end()

    def end_round(self):
        """回合结束：buff 计时衰减与移除。"""
        for c in self.cs:
            kept = []
            for b in c.get("buff", []):
                if b.get("剩余回合", 0) > 0:
                    b["剩余回合"] -= 1
                if b.get("剩余回合", 0) != 0:
                    kept.append(b)
            c["buff"] = kept

    # ---- 行动 ----
    def perform(self, actor_name: str, action: dict, thought_mod: int = 0) -> list[dict]:
        """结算一个角色的一个动作，返回本次新增的日志条目。"""
        actor = self.get(actor_name)
        start = len(self.log)
        if actor is None or not actor.get("存活") or actor.get("已撤离"):
            return self._err(f"「{actor_name}」无法行动")
        if actor.get("已行动"):
            return self._err(f"「{actor_name}」本回合已行动")
        if self.ended:
            return self._err("战斗已结束")

        动作 = action.get("动作", "")
        actor["已行动"] = True
        if actor.get("跳过回合") and 动作 != "撤退":
            self.append_log({"类型": "眩晕", "行动者": actor_name,
                             "文本": f"{actor_name} 眩晕，无法行动。"})
            return self.log[start:]

        handler = {
            "移动": self._do_move, "舞剑": self._do_attack,
            "防守": self._do_defend, "技能": self._do_skill,
            "交流": self._do_talk, "撤退": self._do_retreat,
        }.get(动作)
        if handler is None:
            return self._err(f"未知动作「{动作}」")
        try:
            handler(actor, action, thought_mod or 0)
        except Exception as e:  # 单个动作出错不炸整场
            self._err(f"结算「{动作}」失败：{e}")
        self._check_end()
        return self.log[start:]

    # ---- 各动作实现 ----
    def _do_move(self, actor, action, tmod):
        cell = self._resolve_move(actor, action)
        if not cell:
            return self._fallback_defend(actor, "移动目标非法")
        x0 = actor["格"][0]
        actor["格"] = list(cell)
        actor["朝向"] = "右" if cell[0] >= x0 else "左"
        self.append_log({"类型": "移动", "行动者": actor["名字"],
                         "文本": f"{actor['名字']} 移动到 ({cell[0]},{cell[1]})。"})

    def _resolve_move(self, actor, action):
        x0, y0 = actor["格"]
        if action.get("目标格"):
            try:
                tx, ty = int(action["目标格"][0]), int(action["目标格"][1])
            except (TypeError, ValueError, IndexError):
                return None
        else:
            mv = action.get("移动", "原地")
            fwd = 1 if actor["阵营"] == "友方" else -1
            tx, ty = x0, y0
            if mv == "前进1":
                tx = x0 + fwd
            elif mv == "后退1":
                tx = x0 - fwd
            elif mv == "侧移1":
                ty = y0 + 1
            elif mv == "斜移1":
                tx, ty = x0 + fwd, y0 + 1
            elif mv == "原地":
                return (x0, y0)
        if not in_board(tx, ty):
            return None
        # 可达（切比雪夫 ≤ 移动力），且未被占
        if max(abs(tx - x0), abs(ty - y0)) > move_range(actor):
            return None
        occ = self.cell_occupied(tx, ty)
        if occ is not None and occ is not actor:
            return None
        return (tx, ty)

    def _do_attack(self, actor, action, tmod):
        """舞剑：普通攻击（不耗内力）。"""
        atk = normal_attack()
        target = self.get(action.get("目标", ""))
        err = self._check_target(actor, target, atk.get("射程", 1))
        if err:
            return self._fallback_defend(actor, err)
        self._resolve_attack(actor, target, atk, tmod)

    def _do_defend(self, actor, action, tmod):
        actor["防守"] = True
        gain = 10 if not _has_buff(actor, "内伤") else 0
        actor["内力"] = min(actor["内力上限"], actor["内力"] + gain)
        self.append_log({"类型": "防守", "行动者": actor["名字"],
                         "文本": f"{actor['名字']} 凝神防守（本回合减伤 40%，回复 {gain} 内力）。"})

    def _do_skill(self, actor, action, tmod):
        name = action.get("招式", "")
        skill = get_skill(name)
        if not skill:
            return self._fallback_defend(actor, f"招式「{name}」不在招式表")
        if name not in (actor.get("招式") or []):
            return self._fallback_defend(actor, f"「{name}」不可用（未习得/熟练度不足）")
        cost = int(skill.get("内力", 0))
        if cost > actor["内力"]:
            return self._fallback_defend(actor, f"内力不足（需 {cost}）")
        actor["内力"] -= cost

        五行 = skill.get("五行", "无")
        范围 = skill.get("范围", "单体")
        射程 = skill.get("射程", 1)
        targets = self._skill_targets(actor, action.get("目标"), 范围, 射程)
        if not targets and (skill.get("威力", 0) or 0) > 0:
            return self._fallback_defend(actor, "没有合法目标")

        self.append_log({"类型": "技能", "行动者": actor["名字"], "招式": name,
                         "文本": f"{actor['名字']} 催动「{name}」（耗内力 {cost}）。"})
        # 效果：增益给自身，减益给目标
        for eff in skill.get("效果", []) or []:
            d = BUFF_DEFS.get(eff)
            if not d:
                continue
            if eff == "蓄力":
                if self._stack(actor, "蓄力") < 3:
                    apply_buff(actor, "蓄力", 1, -1)  # 永久层数，直到被水行伤害招式消耗
                self.append_log({"类型": "效果", "行动者": actor["名字"],
                                 "文本": f"{actor['名字']} 蓄力 +1（共 {self._stack(actor,'蓄力')} 层）。"})
                continue
            if d["类型"] == "增益":
                apply_buff(actor, eff)
            else:
                for t in targets:
                    apply_buff(t, eff)
        # 伤害
        if int(skill.get("威力", 0)) > 0:
            for t in targets:
                self._resolve_attack(actor, t, skill, tmod)

    def _bleed(self, target: dict):
        """叠一层流血（上限 BLEED_MAX）。"""
        if self._stack(target, "流血") < BLEED_MAX:
            apply_buff(target, "流血", 1)

    def _apply_weapon_effects(self, actor, target, 档位):
        """命中后按武器类型施加附加效果。"""
        if not target.get("存活"):
            return
        wp = WEAPON_KINDS[weapon_kind(actor)]
        if wp.get("命中效果") == "流血":
            self._bleed(target)
            self.append_log({"类型": "效果", "行动者": actor["名字"], "目标": target["名字"],
                             "文本": f"{target['名字']} 被割伤，血流不止（流血×{self._stack(target,'流血')}）。"})
        if 档位 == "会心" and wp.get("会心效果"):
            apply_buff(target, wp["会心效果"], 1)
            self.append_log({"类型": "效果", "行动者": actor["名字"], "目标": target["名字"],
                             "文本": f"{target['名字']} 被震得头晕目眩（{wp['会心效果']}）。"})

    def _skill_targets(self, actor, target_name, 范围, 射程):
        enemies = [c for c in self.alive() if c["阵营"] != actor["阵营"]]
        if 范围 == "自身":
            return [actor]
        if str(范围).startswith("领域"):
            n = int(str(范围)[2:] or 1)
            return [c for c in enemies if distance(actor, c) <= n]
        if 范围 == "全场":
            return list(enemies)
        # 单体（扇形/直线暂按单体处理）
        t = self.get(target_name or "")
        if t is None or t["阵营"] == actor["阵营"]:
            return []
        if distance(actor, t) > int(射程 or 1):
            return []
        return [t]

    def _do_talk(self, actor, action, tmod):
        target = self.get(action.get("目标", ""))
        if target is None:
            return self._fallback_defend(actor, "交流目标不存在")
        dur = 2 + (1 if tmod >= 10 else (-1 if tmod <= -10 else 0))
        dur = max(1, dur)
        if target["阵营"] == actor["阵营"]:
            apply_buff(target, "士气", 回合=dur)
            if action.get("约定"):
                target["约定撤退"] = True
            self.append_log({"类型": "交流", "行动者": actor["名字"], "目标": target["名字"],
                             "文本": f"{actor['名字']} 对 {target['名字']} 喊话——{target['名字']} 士气大振。"})
        else:
            apply_buff(target, "动摇", 回合=dur)
            self.append_log({"类型": "交流", "行动者": actor["名字"], "目标": target["名字"],
                             "文本": f"{actor['名字']} 出言扰乱 {target['名字']} 心神。"})

    def _do_retreat(self, actor, action, tmod):
        roll = self.rng.randint(1, 100)
        mod = min(15, int(actor["属性"].get("轻功", 0)) // 10)
        最终 = roll + mod + (tmod or 0)
        if 最终 >= 60:
            actor["已撤离"] = True
            self.append_log({"类型": "撤退", "行动者": actor["名字"],
                             "文本": f"{actor['名字']} 施展轻功脱出战圈（掷 {roll}+{mod}）。"})
            if actor.get("是玩家"):
                self._end_battle(None, "玩家撤退")
        else:
            self.append_log({"类型": "撤退", "行动者": actor["名字"],
                             "文本": f"{actor['名字']} 想脱身却被缠住（掷 {roll}+{mod}）。"})

    # ---- 攻击结算 ----
    def _resolve_attack(self, actor, target, skill, tmod):
        if target is None or not target.get("存活") or target.get("已撤离"):
            return
        五行 = skill.get("五行", "无")
        兵器 = actor.get("兵器", "剑法")
        攻值 = int(actor["属性"].get(兵器, 0))
        # 命中
        净 = 攻值 - int(target["属性"].get("轻功", 0))
        命中修正 = max(-25, min(25, round(净 / 5)))
        攻buff命中 = _buff_mod(actor, "命中")
        pos = _position_mod(actor, target, self)
        最终 = self.rng.randint(1, 100) + 命中修正 + int(攻buff命中) + pos["命中"]
        档位, dmg_k = _hit_tier(最终)
        if 档位 is None:
            self.append_log({"类型": "攻击", "行动者": actor["名字"], "目标": target["名字"],
                             "招式": skill.get("名称", ""), "结果": {"命中": False, "掷骰": 最终},
                             "文本": f"{actor['名字']} 一招落空，被 {target['名字']} 避开。"})
            return
        # 伤害
        连击 = max(1, int(skill.get("连击", 1)) if int(skill.get("威力", 0)) > 0 else 1)
        for _ in range(连击):
            dmg = self._compute_damage(actor, target, skill, dmg_k, tmod, pos)
            self._damage(target, dmg, "attack")
            self.append_log({"类型": "攻击", "行动者": actor["名字"], "目标": target["名字"],
                             "招式": skill.get("名称", ""),
                             "结果": {"命中": True, "档位": 档位, "掷骰": 最终,
                                       "伤害": dmg, "五行": 五行, "位置": pos["类型"],
                                       "修正": tmod},
                             "文本": self._attack_text(actor, target, skill, 档位, dmg, pos, 五行)})
            if not target.get("存活"):
                break
        self._apply_weapon_effects(actor, target, 档位)

    def _compute_damage(self, actor, target, skill, dmg_k, tmod, pos) -> int:
        兵器 = actor.get("兵器", "剑法")
        攻值 = int(actor["属性"].get(兵器, 0))
        威力 = int(skill.get("威力", 0))
        base = 威力 * (攻值 / 100.0) * _tier_coef(actor.get("梯度"))
        base *= WEAPON_KINDS[weapon_kind(actor)]["伤害"]   # 利器 > 钝器 > 徒手
        # 五行克制
        ke = 1.0
        a5, d5 = skill.get("五行", "无"), target.get("五行", "")
        if a5 and a5 != "无" and d5:
            if WUXING_KE.get(a5) == d5:
                ke = KE_ADV
            elif WUXING_KE.get(d5) == a5:
                ke = KE_DIS
        base *= ke * pos["伤害"] * dmg_k
        # 蓄力（水行伤害招式消耗全部层数，每层 +33%）
        stack = self._stack(actor, "蓄力")
        if stack and a5 == "水":
            base *= (1 + 0.33 * stack)
            self._consume_stack(actor, "蓄力")
        # AI 修正（思路）→ 伤害倍率；buff 伤害
        base *= (1 + (tmod or 0) / 100.0)
        base *= (1 + _buff_mod(actor, "伤害"))
        if a5 and a5 != "无":
            base *= (1 + _buff_mod(actor, "技能伤害"))
        # 守方承伤
        base *= (1 + _buff_mod(target, "受伤"))
        减伤 = _buff_mod(target, "减伤") + (0.40 if target.get("防守") else 0.0)
        if "穿甲" in (skill.get("效果") or []):
            减伤 *= 0.5
        减伤 = min(0.80, max(0.0, 减伤))
        base *= (1 - 减伤)
        return max(1, int(base))

    def _attack_text(self, actor, target, skill, 档位, dmg, pos, 五行) -> str:
        s = f"{actor['名字']} 以「{skill.get('名称','攻击')}」攻向 {target['名字']}——{档位}"
        if 五行 and 五行 != "无":
            s += f"（{五行}）"
        if pos["类型"] != "正面":
            s += f"·{pos['类型']}"
        return s + f"，造成 {dmg} 点伤害。"

    # ---- 伤害/死亡 ----
    def _damage(self, c, amount, source):
        c["生命"] = max(0, c["生命"] - int(amount))
        if c["生命"] <= 0 and c.get("存活"):
            c["存活"] = False
            self.append_log({"类型": "倒下", "目标": c["名字"],
                             "文本": f"{c['名字']} 重伤倒下。"})

    def _stack(self, c, name) -> int:
        for b in c.get("buff", []):
            if b.get("名称") == name:
                return b.get("层数", 0)
        return 0

    def _consume_stack(self, c, name, n: int = None):
        for b in c.get("buff", []):
            if b.get("名称") == name:
                b["层数"] = 0 if n is None else max(0, b.get("层数", 0) - n)
        # 层数耗尽的层叠 buff 直接移除（如蓄力）
        c["buff"] = [b for b in c.get("buff", [])
                     if not (b.get("名称") == name and b.get("层数", 0) <= 0)]

    # ---- 目标校验 ----
    def _check_target(self, actor, target, 射程):
        if target is None:
            return "目标不存在"
        if not target.get("存活") or target.get("已撤离"):
            return "目标已倒下/离场"
        if target["阵营"] == actor["阵营"]:
            return "不能攻击队友"
        if distance(actor, target) > int(射程 or 1):
            return f"超出射程（{distance(actor, target)} > {射程}）"
        return None

    def _fallback_defend(self, actor, reason):
        actor["防守"] = True
        self.append_log({"类型": "防守", "行动者": actor["名字"],
                         "文本": f"{actor['名字']} 行动受阻（{reason}），转为防守。"})

    # ---- 结束判定 ----
    def _check_end(self):
        # 玩家是锚点：玩家倒下/撤离 → 战斗即结束（否则剩余队友会让驱动空转）
        p = next((c for c in self.cs if c.get("是玩家")), None)
        if p is not None:
            if not p.get("存活"):
                other = "敌方" if p["阵营"] == "友方" else "友方"
                self._end_battle(other, "玩家倒下")
                return
            if p.get("已撤离"):
                self._end_battle(None, "玩家撤离")
                return
        for side in SIDES:
            if not self.side_members(side):
                other = "敌方" if side == "友方" else "友方"
                self._end_battle(other, f"{side}全灭")
                return

    def _end_battle(self, winner, reason):
        if self.ended:
            return
        self.ended = True
        self.winner = winner
        self.result_reason = reason
        self.append_log({"类型": "结束", "文本": f"战斗结束：{reason}。" + (f"胜方：{winner}" if winner else "")})

    # ---- 日志 ----
    def append_log(self, entry: dict):
        entry.setdefault("回合", self.round)
        self.log.append(entry)

    def _err(self, msg: str) -> list[dict]:
        self.append_log({"类型": "无效", "文本": msg})
        return [self.log[-1]]

    # ---- 序列化 / 状态 ----
    def state(self) -> dict:
        return {
            "回合": self.round,
            "先手方": self.first_side,
            "宽度": GRID_W, "高度": GRID_H,
            "已结束": self.ended,
            "胜方": self.winner,
            "结束原因": self.result_reason,
            "参战者": [
                {
                    "名字": c["名字"], "阵营": c["阵营"], "是玩家": c.get("是玩家", False),
                    "格": c["格"], "朝向": c.get("朝向", ""),
                    "生命": c["生命"], "生命上限": c["生命上限"],
                    "内力": c["内力"], "内力上限": c["内力上限"],
                    "梯度": c.get("梯度", ""), "兵器": c.get("兵器", ""),
                    "武器类型": weapon_kind(c), "五行": c.get("五行", ""),
                    "轻功": c["属性"].get("轻功", 0), "移动力": move_range(c),
                    "buff": c.get("buff", []),
                    "招式": c.get("招式", []),
                    "存活": c.get("存活", True), "已撤离": c.get("已撤离", False),
                    "已行动": c.get("已行动", False), "防守": c.get("防守", False),
                    "约定撤退": c.get("约定撤退", False),
                }
                for c in self.cs
            ],
        }


# ------------------------------------------------------------
# 便捷构建
# ------------------------------------------------------------
def new_battle(enemies: list, allies: list = None, rng=None) -> Battle:
    """开一场战斗。玩家固定参战；`allies`/`enemies` 为 npc_combatant 结果列表。"""
    cs = [player_combatant()]
    cs.extend(allies or [])
    cs.extend(enemies or [])
    _auto_place(cs)
    return Battle(cs, rng=rng)


def _auto_place(cs: list):
    """按阵营自动布位：保留不冲突的位置，冲突者顺次填空格。"""
    used = set()
    for side, cols in (("友方", ALLIES_START_X), ("敌方", ENEMIES_START_X)):
        free = [(x, y) for x in cols for y in range(GRID_H)]
        for c in [c for c in cs if c["阵营"] == side]:
            g = tuple(c["格"])
            if in_board(*g) and g not in used:
                used.add(g)
                continue
            for s in free:
                if s not in used:
                    c["格"] = [s[0], s[1]]
                    used.add(s)
                    break
