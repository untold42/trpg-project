# -*- coding: utf-8 -*-
"""
quest_sim.py
============
任务**进度判定**小模型管线（只对**被追踪**的任务）。

链路：
    GM 产出本轮叙事（narration + chat）
      → 本模块拿「本轮文本 + 被追踪任务清单」问 4B：**本轮做到了哪些里程碑**（并列、可多条）
      → 代码标完成 + 产出 UI 事件（前端即时刷新任务栏）
      → 若某任务里程碑**全部完成** → 返回给调用方，交旁路大模型裁定「补新里程碑 / 算真正完成」
        （本模块**不判完成**；完成由 `tools/大模型/quest_arbiter.py` 决定）

为什么归小模型 & 为什么只跑追踪任务：
    - 判「这轮有没有推进某任务」是封闭选择，4B 的强项；
    - 玩家**没追踪**的任务完全不查 → 小模型不空转；
    - 未被追踪的任务不冻结：到 DDL 由旁路大模型裁定（见 quest_arbiter）。
    - 实测：add 100%、update/complete ~75-83%，且**从不误判**（该"否"的全"否"）——保守但安全。

开关：`TRPG_QUEST_SIM=0` 关闭。
"""

from __future__ import annotations

import os

from tools.核心 import quest
from tools.核心.ui_events import ui_event
from tools.小模型 import small_model

ENABLED = os.environ.get("TRPG_QUEST_SIM", "1") != "0"

CONTEXT_LIMIT = 1500

SYSTEM = (
    "你是南宋武侠游戏的「里程碑判定器」，只输出 JSON。"
    "给你若干**被追踪**的任务（含各自的里程碑）与本轮叙事，指出本轮**哪些任务的哪些里程碑已经做到**。"
    "里程碑是**并列**的——一轮可以同时完成多条，全部列出。"
    "只认叙事里**明确做到**的；提到、计划、做了一半都不算。没有就返回空数组。"
    "禁止思考、禁止解释、禁止输出 JSON 以外的内容。/no_think"
)


def _turn_text(events: list) -> str:
    parts = []
    for e in events or []:
        if not isinstance(e, dict):
            continue
        t = e.get("type")
        if t == "narration":
            c = str(e.get("content") or "").strip()
            if c:
                parts.append(c)
        elif t == "chat":
            c = str(e.get("content") or "").strip()
            if c:
                parts.append(f"{e.get('speaker', '?')}：「{c}」")
    return "\n".join(parts)[:CONTEXT_LIMIT]


def _task_lines(tasks: list) -> str:
    lines = []
    for t in tasks:
        ms = " ".join(f"{i+1}.{m.get('项')}" for i, m in enumerate(t.get("里程碑") or []))
        lines.append(f"- id={t.get('id')}｜《{t.get('标题')}》｜里程碑：{ms}")
    return "\n".join(lines)


def _match_id(tasks: list, name: str) -> str:
    name = str(name or "").strip()
    if not name:
        return ""
    for t in tasks:
        if name == t.get("id") or name == t.get("标题"):
            return t.get("id")
    for t in tasks:
        ti = str(t.get("标题") or "")
        if ti and (ti in name or name in ti):
            return t.get("id")
    return ""


def run(events: list, tracked_ids) -> tuple:
    """对**追踪任务**判定「完成了哪些里程碑」，应用并返回 `(UI 事件, 需裁定的任务)`。

    返回的第二个值是**里程碑已全部完成**的任务——调用方应把它们交给
    `quest_arbiter.arbitrate_milestones_async` 去判「要不要补新里程碑 / 算不算真完成」。
    """
    if not ENABLED:
        return [], []
    tasks = quest.by_ids(tracked_ids)
    if not tasks:
        return [], []
    text = _turn_text(events)
    if not text.strip():
        return [], []

    schema = {
        "type": "object",
        "properties": {
            "完成里程碑": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"任务": {"type": "string"}, "里程碑": {"type": "string"}},
                    "required": ["任务", "里程碑"],
                },
                "description": "本轮做到的里程碑（任务标题 + 里程碑原文；没有就空数组）",
            },
        },
    }
    user = ("被追踪的任务：\n" + _task_lines(tasks)
            + "\n\n本轮叙事：\n" + text
            + "\n\n本轮做到了哪些里程碑？（没有就空数组）")

    try:
        r = small_model.ask_json(SYSTEM, user, schema, max_tokens=200, timeout=10)
    except Exception:
        return [], []
    if not isinstance(r, dict):
        return [], []

    # 按任务归组（同一任务可一轮完成多条）
    by_task: dict[str, list] = {}
    for item in (r.get("完成里程碑") or []):
        if not isinstance(item, dict):
            continue
        tid = _match_id(tasks, item.get("任务"))
        ms = str(item.get("里程碑") or "").strip()
        if tid and ms:
            by_task.setdefault(tid, []).append(ms)

    out: list = []
    todo: list = []
    for tid, ms_list in by_task.items():
        res = quest.update(tid, ms_list)
        if res.get("success") and res.get("命中"):
            out.append(ui_event("quest", 动作="推进", 任务=res.get("任务")))
        if res.get("全部完成"):
            t = quest.get(tid)
            if t:
                todo.append(t)
    return out, todo
