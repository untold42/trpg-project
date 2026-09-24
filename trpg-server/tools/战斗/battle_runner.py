# -*- coding: utf-8 -*-
"""
battle_runner.py
================
战斗**阶段驱动**：把 `tools/battle.py`（数值核心）与 `tools/battle_ai.py`（AI）接起来。

一回合（Round）的固定流程（见 `trpg-world/战斗系统.md` §3）：

    begin_round
      → 先手方阶段
          · 若该侧含玩家：**玩家先行动**（判「思路」修正）→ 友方 NPC 小模型一次决定
          · 若该侧无玩家：小模型**一次调用**决定该侧全体 NPC
      → 后手方阶段（同上，另一侧）
    end_round

对外接口（供 `/battle/*` 路由调用）：

    r = BattleRunner(battle)
    r.start()                 # 开局：推进到「等待玩家输入」或战斗结束
    r.pending                 # 是否在等玩家行动
    r.submit(action, thought) # 玩家提交一个动作 → 继续推进到下一次等待/结束
    r.state()                 # 给前端的完整状态（含战场 + 日志 + 最后判定）

AI 降级：小模型不可用时 `decide_side` 返回「全体防守」，`judge_thought` 返回「平平 0」，
战斗照常进行（不会卡死）。
"""

from __future__ import annotations

import os
import random

from tools.战斗 import battle as B
from tools.战斗 import battle_ai
from tools.战斗 import battle_tactics

#: NPC 决策走哪套：`code`（默认，战术层 Utility+前瞻）/ `model`（小模型）
USE_MODEL = os.environ.get("TRPG_BATTLE_AI", "code") == "model"


class BattleRunner:
    def __init__(self, battle: B.Battle, rng: random.Random = None):
        self.b = battle
        self.rng = rng or battle.rng
        self._phase = 0
        self._queue: list[dict] = []
        self._decided: dict = {}
        self.pending = False
        self.last_judge: dict = {}
        self._player = next((c for c in battle.cs if c.get("是玩家")), None)
        self.player_name = self._player["名字"] if self._player else ""
        self.player_side = self._player["阵营"] if self._player else "友方"

    # ---- 对外 ----
    def start(self) -> dict:
        """开局：第一回合 + 先手方阶段，推进到「等玩家」或结束。"""
        if self.b.round == 0 and not self.b.ended:
            self.b.begin_round()
            self._phase = 0
            self._begin_phase(0)
        return self.advance()

    def submit(self, action: dict, thought: str = "") -> dict:
        """玩家提交一个动作（+ 可选「思路」）→ 判定修正 → 结算 → 继续推进。"""
        if self.b.ended or not self.pending:
            return self.state()
        mod = battle_ai.judge_thought(
            self._snapshot_text(), action.get("动作", ""),
            action.get("目标", ""), thought,
        )
        self.last_judge = {"行动者": self.player_name, **mod}
        self.pending = False
        self.b.perform(self.player_name, action, thought_mod=mod.get("修正", 0))
        return self.advance()

    def state(self) -> dict:
        return {
            "战场": self.b.state(),
            "等待玩家": self.pending,
            "阶段": self.b.current_side,
            "先手方": self.b.first_side,
            "最后的思路判定": self.last_judge,
            "日志": self.b.log,
        }

    # ---- 内部：阶段驱动 ----
    def _sides(self) -> list[str]:
        first = self.b.first_side or "友方"
        return [first, "敌方" if first == "友方" else "友方"]

    def _begin_phase(self, i: int):
        side = self._sides()[i]
        self.b.current_side = side
        members = [c for c in self.b.turn_order() if c["阵营"] == side]
        if side == self.player_side:
            # 玩家同侧时，玩家先动（其后 NPC 才能对玩家的行动作出反应）
            members.sort(key=lambda c: (not c.get("是玩家"), -c["属性"].get("轻功", 0)))
        self._queue = members
        self._decided.pop(side, None)

    def advance(self) -> dict:
        """推进战斗，直到需要玩家输入或战斗结束。

        安全阀：最多自走 2 个整回合；否则说明玩家没被轮询到（异常），停下。
        """
        guard = 0
        rounds_done = 0
        while not self.b.ended:
            guard += 1
            if guard > 300:  # 保险：防死循环
                break
            if self._queue:
                actor = self._queue.pop(0)
                if (not actor.get("存活")) or actor.get("已撤离") or actor.get("已行动"):
                    continue
                if actor.get("是玩家"):
                    self.pending = True
                    return self.state()
                self._ensure_decisions(actor["阵营"])
                act = self._decisions().get(actor["名字"]) or {
                    "动作": "防守", "目标": "", "移动": "原地", "思路": "（兜底）"}
                act = self._sanitize(actor, act)
                self.b.perform(actor["名字"], act, thought_mod=0)
                continue
            # 本阶段结束 → 下一阶段 / 下一回合
            self._phase += 1
            if self._phase >= 2:
                rounds_done += 1
                if rounds_done >= 2:   # 跑了 2 个整回合还没轮到玩家 → 异常，停
                    break
                self.b.end_round()
                self.b.begin_round()
                self._phase = 0
                if self.b.ended:
                    break
            self._begin_phase(self._phase)
        self.pending = False
        return self.state()

    def _decisions(self) -> dict:
        return self._decided.get(self.b.current_side, {})

    def _ensure_decisions(self, side: str):
        """该侧 NPC 行动前决定全队行动（缓存）。

        默认走**代码战术层**（L2 Utility + L3 前瞻）；设 `TRPG_BATTLE_AI=model` 切回小模型。
        """
        if side in self._decided:
            return
        members = [c for c in self.b.alive() if c["阵营"] == side and not c.get("是玩家")]
        if not members:
            self._decided[side] = {}
            return
        if USE_MODEL:
            members_info = [{"名字": c["名字"], "简介": self._intro(c)} for c in members]
            targets = [c["名字"] for c in self.b.alive()]
            try:
                self._decided[side] = battle_ai.decide_side(
                    side, self._snapshot_text(), members_info, targets)
            except Exception:
                self._decided[side] = {}
            return
        try:
            self._decided[side] = battle_tactics.plan_side(self.b, side)
        except Exception:
            self._decided[side] = {}

    def _sanitize(self, actor: dict, act: dict) -> dict:
        """小模型幻觉/失误兜底：把执行不了的动作换成可行的。"""
        a = act.get("动作", "")
        if a == "技能" and not (actor.get("招式") or []):
            a = "舞剑"        # 没招式的角色不能施法
        if a == "移动":
            if self.b._resolve_move(actor, act) is None:
                return self._fallback(actor)
            return act
        if a in ("技能", "舞剑"):
            t = self.b.get(act.get("目标", ""))
            reach = 1
            if a == "技能":
                sk = B.get_skill(act.get("招式", ""))
                reach = int((sk or {}).get("射程", 1)) if sk else 1
            # 目标不存在 / 是自己或队友 / 超射程 → 兜底
            if t is None or t["阵营"] == actor["阵营"] or B.distance(actor, t) > reach:
                return self._fallback(actor)
            return {**act, "动作": a}
        if a == "交流":
            if self.b.get(act.get("目标", "")) is None:
                return self._fallback(actor)
        return act

    def _fallback(self, actor: dict) -> dict:
        """小模型幻觉兜底：邻近就打；否则朝最近敌人走一格；再不行才防守。"""
        e = self._nearest_enemy(actor, 1)
        if e:
            return {"动作": "舞剑", "目标": e["名字"]}
        e = self._nearest_enemy(actor)
        cell = self._step_toward(actor, e) if e else None
        if cell:
            return {"动作": "移动", "目标格": cell}
        return {"动作": "防守"}

    def _step_toward(self, actor: dict, enemy):
        """朝敌人方向走一格（优先斜向），返回合法空格；无则 None。"""
        if enemy is None:
            return None
        ax, ay = actor["格"]
        ex, ey = enemy["格"]
        dx = 0 if ex == ax else (1 if ex > ax else -1)
        dy = 0 if ey == ay else (1 if ey > ay else -1)
        for (tx, ty) in ((ax + dx, ay + dy), (ax + dx, ay), (ax, ay + dy)):
            if (tx, ty) == (ax, ay) or not B.in_board(tx, ty):
                continue
            if self.b.cell_occupied(tx, ty):
                continue
            if max(abs(tx - ax), abs(ty - ay)) > B.move_range(actor):
                continue
            return [tx, ty]
        return None

    def _nearest_enemy(self, actor: dict, within: int = None):
        es = [c for c in self.b.alive() if c["阵营"] != actor["阵营"]]
        if within is not None:
            es = [e for e in es if B.distance(actor, e) <= within]
        return min(es, key=lambda e: (B.distance(actor, e), e["生命"])) if es else None

    def _nearest_enemy_dist(self, c):
        ds = [B.distance(c, e) for e in self.b.alive() if e["阵营"] != c["阵营"]]
        return min(ds) if ds else None

    # ---- 内部：给 AI 看的战局快照 ----
    def _intro(self, c: dict) -> str:
        parts = [c.get("梯度", ""), c.get("兵器", "")]
        wk = B.weapon_kind(c)
        if wk:
            parts.append(wk)
        if c.get("五行"):
            parts.append(c["五行"] + "行")
        return "·".join(p for p in parts if p)

    def _snapshot_text(self) -> str:
        lines = [f"回合 {self.b.round} · 先手方 {self.b.first_side or '?'} · 当前 {self.b.current_side or '?'} 阶段"]
        for side in B.SIDES:
            lines.append(f"【{side}】")
            for c in self.b.cs:
                if c["阵营"] != side:
                    continue
                tag = "（玩家）" if c.get("是玩家") else ""
                pos = f"({c['格'][0]},{c['格'][1]})"
                state_txt = "倒下" if not c.get("存活") else (
                    "已撤离" if c.get("已撤离") else f"HP {c['生命']}/{c['生命上限']} 内力 {c['内力']}/{c['内力上限']}")
                buff = "".join(
                    f"{b['名称']}×{b.get('层数',1)}" for b in c.get("buff", []))
                d = self._nearest_enemy_dist(c)
                dist_txt = "" if d is None else (" 相邻" if d <= 1 else f" 近敌{d}格")
                lines.append(
                    f"- {c['名字']}{tag} {pos} {state_txt}{dist_txt}"
                    f"{' ' + self._intro(c) if self._intro(c) else ''}"
                    f"{' [' + buff + ']' if buff else ''}")
        return "\n".join(lines)


def new_runner(enemies: list, allies: list = None, rng=None) -> BattleRunner:
    """便捷：开一场战斗并返回驱动。"""
    b = B.new_battle(enemies=enemies, allies=allies, rng=rng)
    return BattleRunner(b, rng=rng)
