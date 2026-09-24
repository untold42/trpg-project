# -*- coding: utf-8 -*-
"""
quest_arbiter.py
================
「任务裁定」——**旁路大模型**（DeepSeek）。两个职责：

    add    玩家点「任务化」→ 读会话记录 → 调 `add_quest` 建任务（此刻它是导演）。
    expire 任务到 DDL → 读任务 + 现状 → 一次性给出结局（世界照常运转，不等梁峰）。

为什么是"旁路"：不占用 GM 那一轮、不阻塞叙事；玩家主动触发 / 时钟触发。
为什么用 DeepSeek 而非 GLM 导演：能力更强，且此处它临时充当导演。

注意：`add_quest` **不进 GM 工具集**（`registry.ALL_TOOLS`）——只有本模块用。
"""

from __future__ import annotations

import json
import threading

from tools.核心 import quest
from tools.核心.state_manager import state


# ------------------------------------------------------------
# add
# ------------------------------------------------------------
ADD_TOOL = {
    "type": "function",
    "function": {
        "name": "add_quest",
        "description": "把梁峰刚答应/正在做的一件事做成一个可追踪的任务。没有可任务化的事就不要调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "标题": {"type": "string", "description": "≤10 字"},
                "描述": {"type": "string", "description": "一句话·玩家视角·不剧透"},
                "委托人": {"type": "string", "description": "托付者姓名；自己起的念头留空"},
                "里程碑": {"type": "array", "items": {"type": "string"},
                           "description": "2-4 条可验证的小目标"},
                "时限文本": {"type": "string", "description": "如「三日内」「今夜子时前」"},
                "时限时辰": {"type": "integer", "description": "折算成时辰（1 日 = 12 时辰）"},
                "失败后果": {"type": "string",
                             "description": "若梁峰没做到，世界会怎样（隐藏字段，不给玩家看）"},
            },
            "required": ["标题", "里程碑", "时限时辰"],
        },
    },
}

ADD_SYSTEM = """\
你是南宋武侠游戏的「任务裁定」。玩家刚把一段经历「任务化」了。
请读下面的对话记录，找出**梁峰刚答应 / 正在做的、有对象有目的的那件事**，把它写成一个任务并调用 `add_quest`。
要求：
- 标题 ≤10 字；描述一句话（玩家视角，**不得剧透幕后真相**）。
- 里程碑 2-4 条，**可验证**（做完能看出来，不要「努力寻找」这种）。
- 时限按这件事本身给：`时限文本`（如「三日内」「今夜子时前」）＋ `时限时辰`（1 日 = 12 时辰）。
- `失败后果`：若梁峰没做到，世界会变成什么样（一两句，隐藏字段）。
- 只认「答应 / 承诺 / 受托 / 已实际动手」；闲聊、买卖、问路、吃喝**不要建**。
- 若对话里没有可任务化的事，**不要调用工具**。
- 现在时间与地点见状态块；不要生造地图上没有的地名。
"""


def _state_text() -> str:
    basic = state.load("基本信息", {}) or {}
    return json.dumps({"时间": basic.get("时间"), "位置": basic.get("位置")},
                      ensure_ascii=False)


def arbitrate_add(history_messages: list[dict], hint: str = "") -> list[dict]:
    """读会话记录 → 调 add_quest 建任务。返回新建任务（玩家投影）。"""
    import llm
    existing = [t.get("标题") for t in quest.active()]
    sys_msgs = [{"role": "system", "content": ADD_SYSTEM}]
    if existing:
        sys_msgs.append({"role": "system",
                         "content": "现有任务（**别重复建**）：" + "、".join(x for x in existing if x)})
    sys_msgs.append({"role": "system", "content": "===== 当前状态 =====\n" + _state_text()})
    msgs = sys_msgs + list(history_messages or [])
    ask = "请把梁峰最近答应/正在做的那件事做成任务，调用 add_quest。"
    if hint:
        ask += f"（玩家提示：{hint}）"
    msgs.append({"role": "user", "content": ask})

    msg = llm.send_messages(msgs, tools=[ADD_TOOL])
    created = []
    for tc in (getattr(msg, "tool_calls", None) or []):
        if tc.function.name != "add_quest":
            continue
        try:
            a = json.loads(tc.function.arguments)
        except (json.JSONDecodeError, TypeError):
            continue
        t = quest.add(
            标题=a.get("标题", ""), 描述=a.get("描述", ""), 委托人=a.get("委托人", ""),
            里程碑=a.get("里程碑") or [], 时限文本=a.get("时限文本", ""),
            时限时辰=a.get("时限时辰", 12), 来源="任务裁定", 失败后果=a.get("失败后果", ""),
        )
        if t:
            created.append(t)
    return created


# ------------------------------------------------------------
# expire（DDL）
# ------------------------------------------------------------
EXPIRE_SYSTEM = (
    "你是南宋武侠游戏的「任务裁定」。一个任务到了时限，梁峰未能完成。"
    "请据此写出这件事的**自然结局**：世界照常运转，不会等他。"
    "只写结果本身（两三句），不要写梁峰的反应，不要输出 JSON，不要解释。"
)


def _expire_text(t: dict) -> str:
    import llm
    material = json.dumps(
        {k: t.get(k) for k in ("标题", "描述", "委托人", "里程碑", "时限", "失败后果")},
        ensure_ascii=False,
    )
    msgs = [
        {"role": "system", "content": EXPIRE_SYSTEM},
        {"role": "user", "content": "任务：" + material + "\n\n请写出结局。"},
    ]
    return (llm.complete(msgs) or "").strip()


_inflight: set = set()
_lock = threading.Lock()


def _work(t: dict):
    try:
        txt = _expire_text(t)
        quest.expire(t.get("id", ""), 结果=txt)
    except Exception as e:
        # 裁定失败：也要了结，避免任务永远挂着（降级为机械过期）
        try:
            quest.expire(t.get("id", ""), 结果="（任务已过期。）")
        except Exception:
            pass
        print(f"[quest] DDL 裁定失败（{type(e).__name__}: {e}），已机械过期")
    finally:
        with _lock:
            _inflight.discard(t.get("id"))


def arbitrate_expiry_async(t: dict) -> bool:
    """任务到时限 → 异步叫一次旁路大模型给结局。已在跑则跳过。"""
    tid = t.get("id")
    if not tid:
        return False
    with _lock:
        if tid in _inflight:
            return False
        _inflight.add(tid)
    threading.Thread(target=_work, args=(t,), daemon=True, name="quest-expire").start()
    return True


# ------------------------------------------------------------
# 里程碑裁定（里程碑全部完成时）
# ------------------------------------------------------------
MILESTONE_SYSTEM = (
    "你是南宋武侠游戏的「任务裁定」。一个任务列出的里程碑都已完成。"
    "请判断这件事是否**真的了结了**："
    "若还没有（事情还有下文、对方还会有求、或承诺尚未兑现）→ 「需要补充」=「是」，"
    "并给 1-3 条**新的、可验证的**里程碑；若确实了结 → 「需要补充」=「否」，不要给里程碑。"
    '只输出 JSON：{"需要补充":"是"或"否","里程碑":["…"],"理由":"一句话"}'
)


def _milestone_check(t: dict) -> dict:
    import llm
    basic = state.load("基本信息", {}) or {}
    tm = basic.get("时间") or {}
    payload = {
        "任务": {k: t.get(k) for k in ("标题", "描述", "委托人")},
        "已完成里程碑": [m.get("项") for m in (t.get("里程碑") or [])],
        "时间": tm.get("纪年") or tm.get("日期"),
        "当前地点": (basic.get("位置") or {}).get("地点"),
    }
    txt = llm.complete_json([
        {"role": "system", "content": MILESTONE_SYSTEM},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ])
    try:
        r = json.loads(txt or "{}")
        return r if isinstance(r, dict) else {}
    except json.JSONDecodeError:
        return {}


_m_inflight: set = set()
_mlock = threading.Lock()


def _milestone_work(t: dict):
    tid = t.get("id", "")
    try:
        cap = int(quest.config().get("里程碑扩展上限", 3) or 0)
        if int(t.get("扩展次数", 0) or 0) >= cap:
            quest.complete(tid, 结果="里程碑已了结，任务收束。")
            return
        r = _milestone_check(t)
        if str(r.get("需要补充")) == "是" and r.get("里程碑"):
            res = quest.add_milestones(tid, r["里程碑"])
            if not res.get("新增"):                 # 补的与旧的重复 → 视为了结
                quest.complete(tid, 结果=r.get("理由") or "任务了结。")
        else:
            quest.complete(tid, 结果=r.get("理由") or "任务了结。")
    except Exception as e:
        print(f"[quest] 里程碑裁定失败（{type(e).__name__}: {e}），已机械了结")
        try:
            quest.complete(tid, 结果="（任务了结。）")
        except Exception:
            pass
    finally:
        with _mlock:
            _m_inflight.discard(tid)


def arbitrate_milestones_async(t: dict) -> bool:
    """任务里程碑全部完成 → 异步问旁路大模型「要不要补新里程碑」。"""
    tid = t.get("id")
    if not tid:
        return False
    with _mlock:
        if tid in _m_inflight:
            return False
        _m_inflight.add(tid)
    threading.Thread(target=_milestone_work, args=(t,), daemon=True,
                     name="quest-milestone").start()
    return True
