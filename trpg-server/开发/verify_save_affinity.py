# -*- coding: utf-8 -*-
"""
verify_save_affinity.py
=======================
【一次性探针，会花钱】端到端验证：存档蒸馏时，大模型到底给不给 `好感度变化`。

做法：
  · 用**真实**存档规则（`trpg-world/存档流程.md`）+ 真实 `SAVE_TOOLS`；
  · 输入一段合成的本局记录（一个 NPC 应升温、一个应降温）；
  · 跑工具循环，但**拦截所有写入**（`update_character_archive` / `DB_*` / `update_place_*` 都不真正执行）；
    **只真实执行只读工具**（get_character / query_place / query_nearby）。
  · 打印模型给出的 `update_character_archive` 参数（尤其 `好感度变化`）。

副作用：只发 API 请求；**不写档案、不连/写 chroma、不改游戏数据**。

运行：cd trpg-server && python 开发/verify_save_affinity.py
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

SERVER = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import llm  # noqa: E402
import save_pipeline  # noqa: E402
from tools.大模型.registry import SAVE_TOOLS, TOOLS_MAP  # noqa: E402

#: 只真实执行的只读工具（其余一律假装成功、并记录参数）
SAFE = {"get_character", "query_place", "query_nearby"}

TRANSCRIPT = """\
# 本局记录

1220-01-17 未时 岳阳·洞庭湖上

 旁白：一艘挂着白鲨旗的快船被官军水师围住，船头立着条大汉——正是白鲨帮的刘鄂。
       梁峰恰在附近一叶渔舟上。
梁峰：我摇橹靠过去，朝官军船头喊：「这船上是我的货，诸位军爷行个方便。」
 旁白：官军迟疑片刻，终究摆摆手放行。刘鄂跳上渔舟，重重拍了下梁峰肩膀。
刘鄂：「好小子，敢替老子顶官差！这份情，我刘鄂记下了。」
 旁白：梁峰只摆摆手，说声顺手。

1220-01-17 酉时 岳阳·街市

 旁白：上官隼负手立在街心，身后跟着一队官差。他抬眼打量梁峰，神色淡漠。
梁峰：我按刀上前，压低声音：「上官大人，有些事，劝你莫要再查。」
 旁白：上官隼眯起眼，面色一沉，缓缓后退半步。
上官隼：「……后生，你可知你在同谁说话。」

 旁白：入夜，梁峰回到客栈，一夜无话。
"""

HINTS_TURNS = [
    {"time": "1220-01-17 未时",
     "instructions": [{"type": "chat", "speaker": "刘鄂", "content": "好小子！"}],
     "tool_calls": []},
    {"time": "1220-01-17 酉时",
     "instructions": [{"type": "chat", "speaker": "上官隼", "content": "你可知你在同谁说话。"}],
     "tool_calls": []},
]

STATE = """\
===== 基本信息.json =====
{"时间": {"日期": "1220-01-17", "时辰": "戌时"}, "位置": {"地点": "岳阳楼", "在城内": true}}
===== 状态.json =====
{"生命值": 50, "精力值": 60, "饥饿": 80, "健康": "康健"}
"""


def main():
    import os
    if not os.environ.get("LLM_API_KEY"):
        print("❌ 缺少 LLM_API_KEY"); sys.exit(2)

    rules = save_pipeline.load_save_rules()
    hints = save_pipeline.save_hints(HINTS_TURNS)
    messages = [{"role": "system", "content": rules}]
    if hints:
        messages.append({"role": "system", "content": hints})
    messages.append({"role": "user", "content":
                     "《本局完整记录》\n\n" + TRANSCRIPT
                     + "\n\n请按规则将其蒸馏进长期记忆，只调用数据库工具，不要输出叙事。"})
    messages.append({"role": "system", "content": "===== 当前状态 =====\n" + STATE})

    print(f"规则 {len(rules)} 字；附加任务 {len(hints)} 字；工具 {len(SAVE_TOOLS)} 个")
    print("=" * 78)

    arch_calls = []
    for rnd in range(1, 5):
        msg = llm.send_messages(messages, tools=SAVE_TOOLS)
        tcs = list(getattr(msg, "tool_calls", None) or [])
        if not tcs:
            print(f"[第 {rnd} 轮] 无工具调用，结束。")
            break
        names = [tc.function.name for tc in tcs]
        print(f"[第 {rnd} 轮] 调用：{names}")
        messages.append({
            "role": "assistant", "content": msg.content or "",
            "tool_calls": [{"id": tc.id, "type": "function",
                            "function": {"name": tc.function.name,
                                         "arguments": tc.function.arguments}} for tc in tcs],
        })
        for tc in tcs:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except Exception:
                args = {}
            if name == "update_character_archive":
                arch_calls.append(args)
                result = {"success": True, "name": args.get("name"), "（探针：未写入）": True}
            elif name in SAFE:
                fn = TOOLS_MAP.get(name)
                try:
                    result = fn(**args) if fn else {"success": False, "error": "无实现"}
                except Exception as e:
                    result = {"success": False, "error": f"{type(e).__name__}: {e}"}
            else:
                result = {"success": True, "（探针：写入已拦截）": True}
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": json.dumps(result, ensure_ascii=False)[:4000]})

    print("=" * 78)
    print(f"共捕获 {len(arch_calls)} 次 update_character_archive 调用：\n")
    ok = 0
    for a in arch_calls:
        name = a.get("name")
        delta = a.get("好感度变化")
        has = "好感度变化" in a
        ok += bool(has)
        mark = "✅" if has else "❌ 未给好感度变化"
        print(f"{mark}  {name}  好感度变化={delta}")
        for k in ("milestone", "feeling", "attitude", "recent"):
            if a.get(k):
                v = a[k]
                print(f"      {k}: {str(v)[:70]}")
    print()
    print(f"★ 合规率：{ok}/{len(arch_calls)} 给了 `好感度变化`" if arch_calls
          else "⚠️ 模型一次 update_character_archive 都没调")


if __name__ == "__main__":
    main()
