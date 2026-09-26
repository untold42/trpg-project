# -*- coding: utf-8 -*-
"""
quest_sim.py
============
任务**进度判定**小模型管线（只对**被追踪**的任务）。

链路：
    GM 产出本轮叙事（narration + chat）
      → 本模块拿「本轮文本 + 被追踪任务清单（描述/里程碑现状/幕后背景）」问 4B：
        **本轮新做到了哪些里程碑**（并列、可多条）
      → 代码标完成 + 产出 UI 事件（前端即时刷新任务栏）
      → 若某任务里程碑**全部完成** → 返回给调用方，交旁路大模型裁定「补新里程碑 / 算真正完成」
        （本模块**不判完成**；完成由 `tools/大模型/quest_arbiter.py` 决定）

    注：`真相 / 结局` 作为【幕后背景】一并给判定小模型（它不知道背景时只能硬对文本，判定随意）；
    但 system 硬性要求**只认本轮叙事里明确演出来的结果**，背景只用于理解里程碑的“及格线”。

为什么归小模型 & 为什么只跑追踪任务：
    - 判「这轮有没有推进某任务」是封闭选择，4B 的强项；
    - 玩家**没追踪**的任务完全不查 → 小模型不空转；
    - 未被追踪的任务不冻结：到 DDL 由旁路大模型裁定（见 quest_arbiter）。
    - 实测：add 100%、update/complete ~75-83%，且**从不误判**（该"否"的全"否"）——保守但安全。

开关：`TRPG_QUEST_SIM=0` 关闭。
"""

from __future__ import annotations

import os
import queue
import threading

from tools.核心 import quest
from tools.核心.ui_events import ui_event, push as push_ui_event
from tools.小模型 import remote_model, small_model

ENABLED = os.environ.get("TRPG_QUEST_SIM", "1") != "0"

CONTEXT_LIMIT = 1500

SYSTEM = (
    "你是南宋武侠游戏的「里程碑判定器」，只输出 JSON。"
    "给你若干**被追踪**的任务（含描述、里程碑及其现状，以及仅供你理解任务的【幕后背景】）与本轮叙事，"
    "指出本轮**哪些任务的哪些里程碑已经做到**。"
    "里程碑是**并列**的——一轮可以同时完成多条，全部列出。"
    "判定只有一条依据：【本轮叙事】里**明确演出来的结果**。"
    "凡「提到 / 计划 / 打算 / 打听了一半 / 对方含糊没真说出口」一律不算；"
    "【幕后背景】（真相 / 预定结局）只用来帮你理解里程碑**到底要求什么**，"
    "**它不是本轮发生的事**，绝不能因为背景里写了就判完成。"
    "只报**尚未完成**（○）且本轮确实做到的；没有就返回空数组。"
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
    """任务清单（给判定小模型）：描述 + 里程碑现状 + 幕后背景。

    背景（真相 / 预定结局）**只作理解用途**，system 已硬性禁止据此判完成；
    它的价值是让模型知道里程碑的“及格线”（例：「问出父母消息」是要问出**实情**，
    含糊一句“早没了”不算），而不是让它提前把结局当已发生。
    """
    lines = []
    for t in tasks:
        ms = " ".join(
            f"{i+1}.{'✓' if m.get('状态') == '已完成' else '○'}{m.get('项')}"
            for i, m in enumerate(t.get("里程碑") or [])
        )
        seg = f"- id={t.get('id')}｜《{t.get('标题')}》"
        if t.get("描述"):
            seg += f"｜描述：{t['描述']}"
        seg += f"\n  里程碑（✓=已完成，○=未完成）：{ms}"
        bg = []
        if t.get("真相"):
            bg.append("真相：" + str(t["真相"]))
        if t.get("结局"):
            bg.append("预定结局：" + str(t["结局"]))
        if bg:
            seg += "\n  幕后背景（仅帮你理解里程碑要求，**不是本轮发生的事**）：" + "；".join(bg)
        lines.append(seg)
    return "\n".join(lines)


def _judge(system: str, user: str, schema: dict):
    """里程碑判定：默认走**远端强模型**（`配置/小模型.json` 的 quest 段）；

    未启用远端 → 直接用本地 4B；远端失败 → 按 `失败回退本地` 决定是否退回 4B。
    """
    if remote_model.enabled("quest"):
        r = remote_model.ask_json("quest", system, user, schema)
        if r is not None:
            return r
        if not remote_model.config("quest").get("失败回退本地"):
            return None
    try:
        return small_model.ask_json(system, user, schema, max_tokens=200, timeout=10)
    except Exception:
        return None


# ------------------------------------------------------------
# 异步化：远端判定 2~7s，不能拖慢 /action 回合。
# 单工作线程 + FIFO 队列，结果走 ui_events 队列，由下一次 /action 或 /state 携回。
# ------------------------------------------------------------
_jobs: "queue.Queue" = queue.Queue(maxsize=16)
_worker_lock = threading.Lock()
_worker_on = False


def run_async(events: list, tracked_ids) -> None:
    """把一次判定丢给后台队列（不阻塞回合）。"""
    if not ENABLED:
        return
    global _worker_on
    with _worker_lock:
        if not _worker_on:
            threading.Thread(target=_worker, daemon=True, name="quest-sim").start()
            _worker_on = True
    try:
        _jobs.put_nowait((list(events or []), list(tracked_ids or [])))
    except queue.Full:
        print("[quest] quest_sim 队列已满，丢弃本轮")


def _worker() -> None:
    while True:
        events, tracked = _jobs.get()
        try:
            out, todo = run(events, tracked)
            for e in out:
                push_ui_event(e)
            for t in todo:
                # 里程碑全完成 → 交旁路大模型裁定「补新里程碑 / 算真完成」
                from tools.大模型 import quest_arbiter
                quest_arbiter.arbitrate_milestones_async(t)
        except Exception as e:
            print(f"[quest] quest_sim 失败：{type(e).__name__}: {e}")
        finally:
            _jobs.task_done()


def clear(wait: bool = True) -> None:
    """放弃本轮 / 回滚前：丢弃排队中的判定任务，等在跑的那个结束。"""
    while True:
        try:
            _jobs.get_nowait()
        except queue.Empty:
            break
        else:
            _jobs.task_done()
    if wait:
        _jobs.join()


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
            + "\n\n本轮**新做到**了哪些里程碑？（只列尚未完成 ○ 的；没有就空数组）")

    r = _judge(SYSTEM, user, schema)
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
