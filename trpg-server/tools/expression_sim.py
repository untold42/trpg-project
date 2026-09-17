# -*- coding: utf-8 -*-
"""
expression_sim.py
=================
人物表情填充管线（小模型）。

链路：
    大模型产出 chat（**不带 expression**）
      → 本模块按「整轮上下文 + 每一行的表情枚举」让小模型选表情
      → 就地写回 event["expression"]
      → 返回前端（前端 Character.tsx 据此选立绘）

为什么归小模型：
    表情是 UI 决策（画哪张立绘），与 bg / music 同类；候选是**封闭枚举**（CHARACTER_EXPRESSIONS），
    输出极小，4B 的强项。实测：0 越界、可接受命中 ~94%、单次 ~0.25s。

要点：
    - **白名单用代码判定**（`CHARACTER_EXPRESSIONS.keys()` = 前端 `assets/人物/` 有立绘的角色），
      不是让小模型判断——集合查找零成本零错误。
    - **按「行」配**，不是按「speaker」配：同一人一轮可能说多句、情绪不同。
    - **整轮上下文**：narration + 所有 chat 行都给小模型，判情绪更准。
    - **单候选角色**（枚举只有「正常」）确定性填，不调模型。
    - **降级**：小模型不可用 / 输出非法 → 不填（前端回退 `正常.png` 或不画），绝不阻塞叙事。
    - 不改 `raw`（history / current.jsonl / 存档保持干净，表情只是前端展示数据）。

不含 `get_character`：档案读取必须在大模型**本轮生成之前**完成，不能事后补（见 README）。
开关：`TRPG_EXPRESSION_SIM=0` 关闭。
"""

from __future__ import annotations

import os

from tools import small_model
from tools.find_specific_expression import CHARACTER_EXPRESSIONS

ENABLED = os.environ.get("TRPG_EXPRESSION_SIM", "1") != "0"

#: 给模型的「整轮上下文」截断长度
CONTEXT_LIMIT = 1200

SYSTEM = (
    "你是南宋武侠小说的「表情标注器」，只输出 JSON。"
    "给你一段完整的本轮叙事（供判断语气 / 情绪）与若干「待标注的台词行」，"
    "为**每一行**从它自己的**可用表情枚举**里选**最贴合此刻心情/语气**的一个。"
    "**只能从该行给定的枚举里选一个，不得自创、不得改写、不得串用别人的枚举**；"
    "台词太短、信息不足、或拿不准时，选「正常」。"
    "禁止思考、禁止解释、禁止输出 JSON 以外的任何内容。/no_think"
)


def _chat_rows(events: list) -> list[tuple[int, str, str]]:
    """本轮所有 chat 行 → [(在 events 中的下标, speaker, content)]。"""
    rows = []
    for i, e in enumerate(events):
        if isinstance(e, dict) and e.get("type") == "chat":
            rows.append((i, str(e.get("speaker") or "").strip(), str(e.get("content") or "")))
    return rows


def _turn_text(events: list) -> str:
    """整轮叙事文本（narration + chat），供模型判断情绪。"""
    parts = []
    for e in events:
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


def fill(events: list) -> list:
    """**就地**给 events 里的 chat 补 `expression`，返回同一个 list。

    非 chat 事件不动；白名单外的 speaker 显式清空（大模型可能乱填）。
    """
    if not ENABLED or not isinstance(events, list):
        return events

    todo: list[tuple[int, str, str, list[str]]] = []
    for idx, speaker, content in _chat_rows(events):
        events[idx]["expression"] = ""               # 引擎是唯一生产者：先清空（防大模型残留）
        cands = CHARACTER_EXPRESSIONS.get(speaker)
        if not cands:
            continue                                 # 无立绘资源：留空
        if len(cands) == 1:
            events[idx]["expression"] = cands[0]     # 确定性，不调模型
            continue
        todo.append((idx, speaker, content, list(cands)))

    if not todo:
        return events

    keys = [f"L{n}" for n in range(len(todo))]
    props = {keys[n]: {"type": "string", "enum": todo[n][3]} for n in range(len(todo))}
    schema = {"type": "object", "properties": props, "required": keys}

    rows = [
        f"- {keys[n]}｜{todo[n][1]}：「{todo[n][2]}」｜可选：{todo[n][3]}"
        for n in range(len(todo))
    ]
    user = (
        "整轮叙事（供判断语气 / 情绪）：\n" + (_turn_text(events) or "（无）") +
        "\n\n请为下面每一行各选一个表情（各自只能从自己的可选集里选）：\n" + "\n".join(rows)
    )

    try:
        r = small_model.ask_json(
            SYSTEM, user, schema, max_tokens=24 * len(todo), timeout=8
        )
    except Exception:
        r = None
    if not isinstance(r, dict):
        return events                              # 降级：不填，前端回退

    for n, key in enumerate(keys):
        v = r.get(key)
        if v in todo[n][3]:                        # 只接受枚举内的值
            events[todo[n][0]]["expression"] = v
    return events
