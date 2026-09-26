# -*- coding: utf-8 -*-
"""
verify_tool_intent.py
=====================
【阶段 1 评估探针】叙事 GM（DeepSeek）能不能稳定产出「参数级工具意图」（`{"type":"tool",...}`）？

背景：双GM 拆分（`文档/设计-双GM拆分.md`）要求叙事GM 在叙述之外，另写一串**自然语言动作**
交给工具GM 落地。本探针用**真实规则 + 真实工具集 + 真实玩家行动**跑 DeepSeek，
看它：① 是否输出 `tool` 字段；② 意图是否**参数写全**；③ 是否与实际工具调用一致。

用法（trpg-server 下，需 .env 的 LLM_API_KEY）：
    python 开发/verify_tool_intent.py
    python 开发/verify_tool_intent.py --case 5      # 只跑第 5 例（1 起）
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

SERVER = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import llm  # noqa: E402
from tools.核心 import instructions  # noqa: E402
from tools.大模型.registry import NARRATIVE_TOOLS, TOOLS_MAP  # noqa: E402
from engine import _TOOL_INTENT_CREED, _GM_CREED  # noqa: E402


def _rules() -> str:
    files = sorted(glob.glob(str(SERVER.parent / "trpg-world" / "主持人" / "*.md")))
    return "\n\n".join(Path(f).read_text(encoding="utf-8") for f in files)


STATE = ("===== 当前状态 =====\n"
         "位置：扬州·城南水巷（城内）\n"
         "时间：嘉定十三年正月十七 申时\n"
         "金钱：120 文；背包：木剑×1；生命 80/100；精力 60/100；饥饿 40/100\n"
         "天气：晴，微风")

CASES = [
    ("买酒付钱", "我在楼下向掌柜买了一壶酒，扔给他三文钱。"),
    ("移动", "我动身往城北蜀冈中峰去。"),
    ("睡到天明", "我回房睡下，一觉睡到天明。"),
    ("受伤", "我中了那贼子一刀，血流不止。"),
    ("吃面", "我在路边摊要了一碗热汤面，吃完抹嘴。"),
    ("请人作画", "我请柳氏替我画一幅《寒江独钓》，她应了。"),
    ("多步三件事", "我买了壶酒揣进怀里，转身往城南酒铺去。"),
]


def run_case(action: str) -> dict:
    """**瘦身模式**：叙事GM 只拿只读工具 + 工具意图要求；跑完工具回环后取最终输出。

    这才是双GM 的真实形态：它**根本没有写工具可调**，所以只能写 `tool` 意图。
    """
    msgs = [
        {"role": "system", "content": _rules()},
        {"role": "system", "content": STATE},
        {"role": "user", "content": "梁峰：" + action},
        {"role": "system", "content": _TOOL_INTENT_CREED},
        {"role": "system", "content": _GM_CREED},
    ]
    read_calls: list = []
    msg = llm.send_messages(msgs, tools=NARRATIVE_TOOLS)
    rounds = 0
    while getattr(msg, "tool_calls", None) and rounds < 6:
        rounds += 1
        msgs.append({"role": "assistant", "content": msg.content,
                     "tool_calls": [tc.model_dump() for tc in msg.tool_calls]})
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except (json.JSONDecodeError, TypeError):
                args = {}
            fn = TOOLS_MAP.get(name)
            try:
                result = fn(**args) if fn else {"error": "未知工具"}
            except Exception as e:
                result = {"error": f"{type(e).__name__}: {e}"}
            read_calls.append(name)
            msgs.append({"role": "tool", "tool_call_id": tc.id,
                         "content": json.dumps(result, ensure_ascii=False)[:4000]})
        msg = llm.send_messages(msgs, tools=NARRATIVE_TOOLS)
    items = instructions.parse(msg.content or "")
    intents = [it for it in items if it.get("type") == "tool"]
    narrative = [it for it in items if it.get("type") in ("chat", "narration")]
    return {"read_calls": read_calls, "intents": intents, "narrative": narrative}


def main():
    ap = argparse.ArgumentParser(description="评估叙事GM 的工具意图产出")
    ap.add_argument("--case", type=int, default=0, help="只跑第 N 例（1 起）；0=全部")
    args = ap.parse_args()

    cases = list(enumerate(CASES, 1)) if not args.case else [(args.case, CASES[args.case - 1])]
    for i, (name, action) in cases:
        print("=" * 64)
        print(f"[{i}] {name}｜梁峰：{action}")
        try:
            r = run_case(action)
        except Exception as e:
            print(f"  ❌ {type(e).__name__}: {e}")
            continue
        print("  ▸ 只读查询:", r["read_calls"] or "（无）")
        if not r["intents"]:
            print("  ▸ 工具意图: ❌ **未输出 tool 字段**")
        else:
            for it in r["intents"]:
                for ln in it["content"]:
                    print("      ·", ln)
        print("  ▸ 叙事:", " ".join(it.get("content", "")[:50] for it in r["narrative"])[:120] or "（无）")


if __name__ == "__main__":
    main()
