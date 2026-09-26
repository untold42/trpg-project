# -*- coding: utf-8 -*-
"""
verify_get_character.py
=======================
【一次性验证脚本，会花钱】大模型（DeepSeek）是否真的「人物一登场就调 get_character」。

背景：
    `总览.md` 规则 6 要求「人物出场时先调 get_character」。但工具返回**不进 history**
    （`engine._run` 的 tool_msgs 是轮内临时变量），所以：
      · 若大模型每轮都自觉重调 → 可以不常驻档案；
      · 若它只首次调、之后不调 → 下一轮它就"忘了"这份档案（history 里没有）。
    本脚本就是量这个**自觉性**。

测什么：
    T1 首次登场     —— 出场就调？调对人？（应：调）
    T2 连续对话     —— 下一轮它会不会**重新**调（history 里没有工具消息）？
    T3 无档案路人   —— 对没档案的路人会不会乱调 / 是否按规则 12 当场起名？
    T4 在场不新登场 —— 人在场、只是喝茶，会不会多余地调？

做法（尽量贴近真实）：
    system = 真实规则文本（`trpg-world/主持人/`）+ 一份合成状态块 + `_GM_CREED`；
    工具 = 真实 `ALL_TOOLS`；走 `llm.send_messages`（DeepSeek）。
    **不碰 游戏数据、不跑引擎**（只发请求、看它调什么）。

运行（需 `.env` 里有 `LLM_API_KEY`；**会真实扣费**）：
    cd trpg-server
    python 开发/verify_get_character.py                 # 全部场景
    python 开发/verify_get_character.py --only t1       # 只跑首次登场
    python 开发/verify_get_character.py --limit 3       # 只看前 3 条
    python 开发/verify_get_character.py --repeat 2      # 每条重复，看稳定性

退出码：0=跑完；2=缺 key / 调用失败。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

SERVER = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from tools.大模型.folder_to_prompt import folder_to_prompt  # noqa: E402
from tools.大模型.registry import ALL_TOOLS  # noqa: E402
from engine import _GM_CREED  # noqa: E402
import llm  # noqa: E402

RULES_DIR = SERVER.parent / "trpg-world" / "主持人"

#: 合成状态块（够用即可；真实引擎里这是 游戏数据/*.json 现拼）
STATE = """\
===== 基本信息.json =====
{"时间": {"日期": "1220-01-17", "时辰": "戌时", "刻": 3, "纪年": "嘉定十三年正月十七"},
 "位置": {"地点": "岳阳楼", "在城内": true, "区域": "岳州"},
 "天气": {"状况": "晴", "温度": "微寒"}}
===== 状态.json =====
{"生命值": 50, "生命上限": 50, "精力值": 60, "精力上限": 75, "饥饿": 80, "健康": 100}
===== 金钱.json =====
{"金钱": 320}
===== 背包.json =====
{"物品": {"五行剑": {"数量": 1, "描述": "随身佩剑"}}}
"""

# ------------------------------------------------------------
# 场景
#   turns: [(role, content), ...]，最后一条必须是 user（本轮）；assistant 行模拟"上一轮叙事"
# ------------------------------------------------------------
SCENARIOS = [
    # ---- T1 首次登场（已面对面、名字已知）：应调 get_character ----
    {"id": "t1_温夫人", "t": "t1", "npc": "温夫人", "turns": [
        ("user", "梁峰：我已在锦香宫前厅坐下，对面抱琵琶的正是温夫人。我起身见礼。")]},
    {"id": "t1_刘鄂", "t": "t1", "npc": "刘鄂", "turns": [
        ("user", "梁峰：白鲨帮的刘鄂跳上我的船，就立在面前三尺处。我抱拳通名。")]},
    {"id": "t1_王二壮", "t": "t1", "npc": "王二壮", "turns": [
        ("user", "梁峰：酒肆角落那桌，丐帮帮主王二壮正冲我招手。我端酒碗过去坐下。")]},
    {"id": "t1_车轩辕", "t": "t1", "npc": "车轩辕", "turns": [
        ("user", "梁峰：襄阳城外药庐前，车轩辕背着药箱立在那里。我上前行礼。")]},
    {"id": "t1_上官隼", "t": "t1", "npc": "上官隼", "turns": [
        ("user", "梁峰：上官隼负手立在街心，那队官差在他身后。我走到他面前站定。")]},
    {"id": "t1_叶云裳", "t": "t1", "npc": "叶云裳", "turns": [
        ("user", "梁峰：叶云裳不知何时蹲在我旁边，仰头看我手里那块干粮。")]},

    # ---- T2 连续对话：上一轮已聊过（history 里无工具消息）----
    {"id": "t2_温夫人", "t": "t2", "npc": "温夫人", "turns": [
        ("user", "梁峰：我已在锦香宫前厅坐下，对面抱琵琶的正是温夫人。我起身见礼。"),
        ("assistant", "旁白：温夫人淡淡颔首，命人上了茶。\n温夫人：「远来是客，坐吧。」"),
        ("user", "梁峰开口说：「夫人这琵琶，弦上似有旧伤。」")]},
    {"id": "t2_刘鄂", "t": "t2", "npc": "刘鄂", "turns": [
        ("user", "梁峰：白鲨帮的刘鄂跳上我的船，就立在面前三尺处。我抱拳通名。"),
        ("assistant", "旁白：刘鄂一脚踩在船舷上，咧嘴大笑。\n刘鄂：「敢上老子的船，算你有种！」"),
        ("user", "梁峰开口说：「刘帮主，我想打听倭寇近来可还猖獗。」")]},

    # ---- T3 无档案路人：规则 12 应当场起名；不该拿职业代称去查档案 ----
    {"id": "t3_酒肆老板", "t": "t3", "npc": "（未具名酒肆老板）", "turns": [
        ("user", "梁峰：我走进街边一间小酒肆，柜台后的老板起身招呼我。")]},

    # ---- T4 在场、但不新登场：不应多余调用 ----
    {"id": "t4_温夫人在场", "t": "t4", "npc": "温夫人", "turns": [
        ("user", "梁峰：我已在锦香宫前厅坐下，对面抱琵琶的正是温夫人。我起身见礼。"),
        ("assistant", "旁白：温夫人抱琵琶而坐，命人上了茶。\n温夫人：「远来是客，坐吧。」"),
        ("user", "梁峰：我端起茶盏，慢慢喝了一口，听岛上风声。")]},
]


def _build_messages(turns: list[tuple[str, str]], rules: str) -> list[dict]:
    msgs = [{"role": "system", "content": rules}]
    for role, content in turns:
        msgs.append({"role": role, "content": content})
    msgs.append({"role": "system", "content": "===== 当前状态 =====\n" + STATE})
    msgs.append({"role": "system", "content": _GM_CREED})
    return msgs


def run_one(sc: dict, rules: str):
    """发一次请求，返回 (tool_calls, content, reasoning, seconds)。"""
    msgs = _build_messages(sc["turns"], rules)
    t0 = time.time()
    msg = llm.send_messages(msgs, tools=ALL_TOOLS)
    dt = time.time() - t0
    tcs = []
    for tc in (getattr(msg, "tool_calls", None) or []):
        try:
            args = json.loads(tc.function.arguments)
        except Exception:
            args = {}
        tcs.append({"name": tc.function.name, "args": args})
    return tcs, (msg.content or ""), (getattr(msg, "reasoning_content", "") or ""), dt


def _verdict(sc: dict, tcs: list) -> str:
    """按场景类型给出结论。"""
    names = [t["name"] for t in tcs]
    gc = [t for t in tcs if t["name"] == "get_character"]
    called_npc = [str(t["args"].get("name") or "") for t in gc]
    hit = any(sc["npc"] and sc["npc"] in n for n in called_npc)
    if sc["t"] in ("t1", "t2"):
        if not gc:
            return "❌ 未调用"
        return ("✅ 调对了" if hit else f"🟡 调了但名字对不上：{called_npc}")
    if sc["t"] == "t3":
        if gc:
            return f"🟡 对路人调了 get_character：{called_npc}"
        return "✅ 未调（正确：新路人无档案）"
    if sc["t"] == "t4":
        return "🟡 多余调用了" if gc else "✅ 未调用（正确）"
    return "?"


def main():
    ap = argparse.ArgumentParser(description="验证大模型是否人物登场就调 get_character（会花钱）")
    ap.add_argument("--only", choices=["t1", "t2", "t3", "t4"], default=None)
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条（0=全部）")
    ap.add_argument("--repeat", type=int, default=1, help="每条重复次数（看稳定性）")
    ap.add_argument("--show-content", action="store_true", help="打印模型的叙事首段")
    args = ap.parse_args()

    import os
    if not os.environ.get("LLM_API_KEY"):
        print("❌ 缺少 LLM_API_KEY（.env）"); sys.exit(2)

    rules = folder_to_prompt(str(RULES_DIR))
    cases = [s for s in SCENARIOS if not args.only or s["t"] == args.only]
    if args.limit > 0:
        cases = cases[: args.limit]

    print(f"规则 {len(rules)} 字；工具 {len(ALL_TOOLS)} 个；场景 {len(cases)} 条 × {args.repeat} 轮")
    print("=" * 78)

    stats = {}
    for rep in range(args.repeat):
        if args.repeat > 1:
            print(f"\n########## 第 {rep + 1}/{args.repeat} 轮 ##########")
        for sc in cases:
            try:
                tcs, content, reasoning, dt = run_one(sc, rules)
            except Exception as e:
                print(f"💥 {sc['id']}：{type(e).__name__}: {e}")
                continue
            verdict = _verdict(sc, tcs)
            key = sc["t"]
            s = stats.setdefault(key, {"ok": 0, "n": 0})
            s["n"] += 1
            if verdict.startswith("✅"):
                s["ok"] += 1
            tools_txt = "、".join(
                t["name"] + (f"({t['args'].get('name')})" if t["name"] == "get_character" else "")
                for t in tcs
            ) or "（无工具）"
            print(f"{verdict}  [{sc['id']}]  {dt:.1f}s  工具：{tools_txt}")
            if args.show_content and content.strip():
                print("      叙事：" + content.strip().replace("\n", " ")[:120])
            if reasoning.strip():
                print("      思考：" + reasoning.strip().replace("\n", " ")[:100])

    print("=" * 78)
    labels = {"t1": "T1 首次登场（应调对）", "t2": "T2 连续对话（看是否重调）",
              "t3": "T3 无档案路人（不应拿代称去查）", "t4": "T4 在场不新登场（不应调）"}
    for k in ("t1", "t2", "t3", "t4"):
        if k in stats:
            s = stats[k]
            print(f"{labels[k]}：达标 {s['ok']}/{s['n']}")


if __name__ == "__main__":
    main()
