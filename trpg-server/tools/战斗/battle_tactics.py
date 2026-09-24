# -*- coding: utf-8 -*-
"""
battle_tactics.py
=================
战斗战术层（**纯代码，确定性，不调用任何 LLM**）：
  - **L2 Utility**：`enumerate_actions` 枚举合法动作 → `score_action` 打分 → 取最高分。
  - **L3 前瞻**：`score_action` 会 `battle.clone()` 克隆战场、`perform` 一步，用
    「模拟后的阵地差」再修正分数（因此会计入伤害/击杀/被反击）。

为什么不让小模型选招：4B 不会算战术（实测会把目标填成自己）。**战术全归代码，
模型只在别处负责叙事/判定。** 设计见 `trpg-world/战斗系统.md`。

分数 = 位置启发(靠近/进近战/夹击/避围) + 前瞻阵地差 + 少量动作偏好(内力/撤退/交流)。
权重都在下面常量里，可调。
"""

from __future__ import annotations

from tools.战斗 import battle as B
from tools.核心 import battle_config

# 战术评分数值只从 `战斗数值.json.战术AI` 读取。
def _refresh_ai_config() -> None:
    global _AI, _UNIT_VALUE, W_POS, W_EVAL, W_COST, RETREAT_HP, NEAR_SCORE, LOOKAHEAD_K
    _AI = battle_config.section("战术AI", copy_data=False)
    _UNIT_VALUE = _AI["单位价值"]
    W_POS = float(_AI["位置权重"])
    W_EVAL = float(_AI["前瞻权重"])
    W_COST = float(_AI["内力代价权重"])
    RETREAT_HP = float(_AI["撤退血线"])
    NEAR_SCORE = float(_AI["首次进入近战加分"])
    LOOKAHEAD_K = int(_AI["前瞻掷骰次数"])


_refresh_ai_config()


# ------------------------------------------------------------
# L2：候选枚举
# ------------------------------------------------------------
def enumerate_actions(battle: "B.Battle", actor: dict) -> list[dict]:
    """枚举该角色本回合所有**合法**动作。"""
    out: list[dict] = []
    seen = set()

    def add(a: dict):
        key = (a["动作"], a.get("目标", ""), a.get("招式", ""),
               tuple(a.get("目标格") or ()))
        if key not in seen:
            seen.add(key)
            out.append(a)

    ax, ay = actor["格"]
    mr = B.move_range(actor)
    for dy in range(-mr, mr + 1):                # 移动：可达空格
        for dx in range(-mr, mr + 1):
            if dx == 0 and dy == 0:
                continue
            x, y = ax + dx, ay + dy
            if B.in_board(x, y) and not battle.cell_occupied(x, y) and not battle.blocked(x, y):
                add({"动作": "移动", "目标格": [x, y]})

    enemies = [c for c in battle.alive() if c["阵营"] != actor["阵营"]]

    for e in enemies:                            # 舞剑（近战射程 1）
        if B.distance(actor, e) <= 1:
            add({"动作": "舞剑", "目标": e["名字"]})

    for name in actor.get("招式") or []:         # 技能（五行）
        sk = B.get_skill(name)
        if not sk or int(sk.get("内力", 0)) > actor["内力"]:
            continue
        范围 = str(sk.get("范围", "单体"))
        射程 = int(sk.get("射程", 1) or 1)
        if 范围 == "自身":
            add({"动作": "技能", "招式": name, "目标": ""})
            continue
        if 范围 == "全场":
            add({"动作": "技能", "招式": name, "目标": ""})
            continue
        if battle._is_aoe(范围):                 # AOE：以「格」为中心（枚举各敌方格 + 自身格）
            for cell in [[e["格"][0], e["格"][1]] for e in enemies] + \
                        [[actor["格"][0], actor["格"][1]]]:
                if B.distance(actor, cell) <= 射程:
                    add({"动作": "技能", "招式": name, "目标格": cell})
            continue
        for e in enemies:                        # 单体：选人
            if B.distance(actor, e) <= 射程:
                add({"动作": "技能", "招式": name, "目标": e["名字"]})

    add({"动作": "防守"})
    for t in battle.alive():                     # 交流（队友 / 对手）—— 已持相应 buff 的不重复
        if t is actor:
            continue
        if t["阵营"] == actor["阵营"]:
            if not B._has_buff(t, "士气"):
                add({"动作": "交流", "目标": t["名字"]})
        elif not B._has_buff(t, "动摇"):
            add({"动作": "交流", "目标": t["名字"]})
    add({"动作": "撤退"})
    return out


# ------------------------------------------------------------
# L2：位置启发
# ------------------------------------------------------------
def _cheb(a, b) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def _result_cell(battle: "B.Battle", actor: dict, action: dict):
    """该动作结算后角色所在的格（不移动则为原地）。"""
    if action.get("动作") == "移动":
        return battle._resolve_move(actor, action)
    return tuple(actor["格"])


def _flank_count(battle: "B.Battle", actor: dict, cell, enemies: list) -> int:
    """在 cell 落位后，能形成「夹击 / 背袭」的敌人数。"""
    allies = [c for c in battle.alive()
              if c["阵营"] == actor["阵营"] and c is not actor]
    n = 0
    for e in enemies:
        ex, ey = e["格"]
        if _cheb(cell, e["格"]) > 1:
            continue
        if cell[0] == ex - (1 if e["阵营"] == "友方" else -1) and abs(cell[1] - ey) <= 1:
            n += 1                               # 背袭
            continue
        for a in allies:
            if _cheb(a["格"], e["格"]) <= 1 and \
                    (cell[0] - ex) * (a["格"][0] - ex) + (cell[1] - ey) * (a["格"][1] - ey) < 0:
                n += 1                           # 夹击
                break
    return n


def _positional(battle: "B.Battle", actor: dict, action: dict) -> float:
    """位置启发（**增量式**）：只有「移动」才评分——越接近越正、首次进近战加分、
    夹击加分、被围扣分。不位移的动作位置不变，归 0（效果交给前瞻评估）。"""
    if action.get("动作") == "撤退":
        return 0.0
    if action.get("动作") != "移动":
        return 0.0
    cell = _result_cell(battle, actor, action)
    if cell is None:
        return -999.0
    enemies = [c for c in battle.alive() if c["阵营"] != actor["阵营"]]
    if not enemies:
        return 0.0
    a = (actor["格"][0], actor["格"][1])
    old_d = min(_cheb(a, e["格"]) for e in enemies)
    new_d = min(_cheb(cell, e["格"]) for e in enemies)
    s = float(_AI["每接近一格加分"]) * (old_d - new_d)
    if new_d <= 1 < old_d:
        s += NEAR_SCORE                          # 首次进近战
    s += float(_AI["夹击背袭每个加分"]) * _flank_count(battle, actor, cell, enemies)
    adj = sum(1 for e in enemies if _cheb(cell, e["格"]) <= 1)
    s -= float(_AI["被围每人扣分"]) * max(0, adj - 1)
    return s


# ------------------------------------------------------------
# L3：阵地评估（前瞻用）
# ------------------------------------------------------------
def _unit_value(c: dict) -> float:
    atk = c["属性"].get(c.get("兵器", "剑法"), 0)
    增益 = sum(float(_UNIT_VALUE["单个增益加分"]) for b in c.get("buff", [])
               if b.get("名称") in ("护体", "士气", "洞察"))
    减益 = sum(float(_UNIT_VALUE["单个减益扣分"]) for b in c.get("buff", [])
               if b.get("名称") in ("流血", "中毒", "破绽", "动摇", "致盲"))
    return (c["生命"] + float(_UNIT_VALUE["兵器系数"]) * atk
            + float(_UNIT_VALUE["内力系数"]) * c["内力"]
            + (float(_UNIT_VALUE["有招式加分"]) if c.get("招式") else 0)
            + 增益 - 减益)


def eval_position(battle: "B.Battle", side: str) -> float:
    """阵地分：我方单位价值合计 − 敌方单位价值合计（越大越好）。"""
    ours = sum(_unit_value(c) for c in battle.cs
               if c["阵营"] == side and c.get("存活") and not c.get("已撤离"))
    theirs = sum(_unit_value(c) for c in battle.cs
                 if c["阵营"] != side and c.get("存活") and not c.get("已撤离"))
    return ours - theirs


# ------------------------------------------------------------
# L2+L3：打分
# ------------------------------------------------------------
#: 前瞻取 K 次不同掷骰的平均（消除单次命中/未命中的随机噪声）


def _lookahead_delta(battle: "B.Battle", actor: dict, action: dict,
                     k: int | None = None) -> float:
    """L3 前瞻：克隆战场跑 K 次该动作，取平均的「阵地分增量」。"""
    k = LOOKAHEAD_K if k is None else k
    before = eval_position(battle, actor["阵营"])
    total = 0.0
    for i in range(k):
        try:
            c = battle.clone()
            c.rng.seed(i)                        # 固定几个掷骰场景
            c.perform(actor["名字"], dict(action), thought_mod=0)
            total += eval_position(c, actor["阵营"]) - before
        except Exception:
            pass
    return total / max(1, k)


def score_action(battle: "B.Battle", actor: dict, action: dict,
                 lookahead: bool = True) -> float:
    B.refresh_config()
    _refresh_ai_config()
    s = W_POS * _positional(battle, actor, action)

    动作 = action.get("动作")
    if 动作 == "技能":
        sk = B.get_skill(action.get("招式", ""))
        s -= W_COST * int((sk or {}).get("内力", 0))
    elif 动作 == "撤退":
        ratio = actor["生命"] / max(1, actor["生命上限"])
        s += (float(_AI["低血撤退加分"]) if ratio < RETREAT_HP
              else -float(_AI["非低血撤退扣分"]))
        lookahead = False                # 撤退不做前瞻（离场会被误判为损失价值）
    elif 动作 == "交流":
        s -= float(_AI["交流扣分"])

    if lookahead:
        s += W_EVAL * _lookahead_delta(battle, actor, action)
    return s


def rank_actions(battle: "B.Battle", actor: dict, lookahead: bool = True) -> list:
    """按分数从高到低返回 [(动作, 分数), ...]。"""
    B.refresh_config()
    _refresh_ai_config()
    cands = enumerate_actions(battle, actor)
    scored = [(a, score_action(battle, actor, a, lookahead)) for a in cands]
    scored.sort(key=lambda kv: kv[1], reverse=True)
    return scored


# ------------------------------------------------------------
# 一侧决策
# ------------------------------------------------------------
def plan_side(battle: "B.Battle", side: str, lookahead: bool = True) -> dict:
    """该侧每个 NPC 各自选最高分动作。返回 {名字: 动作(+理由)}。"""
    out: dict = {}
    for c in [x for x in battle.alive() if x["阵营"] == side and not x.get("是玩家")]:
        ranked = rank_actions(battle, c, lookahead)
        if not ranked:
            out[c["名字"]] = {"动作": "防守", "理由": "无可用动作"}
            continue
        best, sc = ranked[0]
        out[c["名字"]] = {**best, "理由": f"战术评分 {sc:.0f}"}
    return out
