# -*- coding: utf-8 -*-
"""
verify_quest.py
===============
【一次性验证脚本】小模型（Qwen3-4B）能否承担任务的三个操作：
    add_quest      —— 从本轮叙事里认出「梁峰答应了 / 开始做一件具体的事」，抽出任务；
    update_quest   —— 在已有任务里，判断本轮推进了哪个里程碑；
    complete_quest —— 在已有任务里，判断本轮是否完成了某个任务。

为什么测：
    任务若交给小模型（每轮一次），GM 就不必带任务工具、也不占用大模型步数；
    但小模型必须**该建才建、不该建不建**（呼应之前"怕它对正常对话乱加好感度"的教训）。

设计：
    三个操作各给一套 schema（枚举 + 短字段），分别测。
    add 用「是/否」先门禁，再抽字段；update/complete 给任务清单让它选。

运行（需 LM Studio 已加载 qwen/qwen3-4b-2507）：
    cd trpg-server
    python 开发/verify_quest.py                 # 三个都测
    python 开发/verify_quest.py --mode add
    python 开发/verify_quest.py --repeats 3
    python 开发/verify_quest.py --mock          # 只验流程
"""

from __future__ import annotations

import argparse
import io
import statistics
import sys
import time
from pathlib import Path

SERVER = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from tools.小模型 import small_model  # noqa: E402

MOCK = False


def _ask(system, user, schema, max_tokens, timeout):
    if MOCK:
        out = {}
        for k, v in (schema.get("properties") or {}).items():
            out[k] = (v.get("enum") or ["否"])[0]
        return out
    return small_model.ask_json(system, user, schema, max_tokens=max_tokens, timeout=timeout)


# ============================================================
# A. add_quest
# ============================================================
ADD_SYSTEM = (
    "你是南宋武侠游戏的「任务识别器」，只输出 JSON。"
    "判断本轮叙事里，**梁峰是否答应了要去做、或已经动手去做一件具体的事**（有对象、有目的）。"
    "只有「答应 / 承诺 / 受托 / 已实际动手」才算；普通寒暄、买卖、问路、吃喝、闲聊都不算。"
    "判定为「是」时，抽出：标题（≤10 字）、描述（一句话·玩家视角）、委托人（人名或空）、"
    "里程碑（2-4 条可验证的小目标）、时限（按事情本身给，如「今夜子时前」「三日内」；没写就据情境给一个合理值）。"
    "判定为「是」时，标题 / 描述 / 里程碑 / 时限**都不得留空**（时限拿不准也要估一个）。"
    "拿不准就选「否」。禁止思考、禁止解释、禁止输出 JSON 以外的内容。/no_think"
)

ADD_CASES = [
    {"n": "温夫人托付", "new": True,
     "scene": "温夫人：「锦香宫有两名女子一夜未归，我疑心被人掳去。梁峰，你可能替我查一查？」\n"
              "梁峰：我点头应下，说三日内必有回音。"},
    {"n": "与王二壮喝酒闲聊", "new": False,
     "scene": "梁峰：我跟王二壮喝了两碗酒，聊些江湖闲话，说说笑笑。"},
    {"n": "唐默铃托寻药方", "new": True,
     "scene": "唐默铃：「那药方是我师父留下的，你若能寻回，我……」\n梁峰：我应承下来。"},
    {"n": "买鸡腿", "new": False,
     "scene": "梁峰：我买了只鸡腿，蹲在墙根啃完。"},
    {"n": "问路", "new": False,
     "scene": "梁峰：我向路边老卒问了问去城南的路，谢过便走。"},
    {"n": "当众立誓复仇", "new": True,
     "scene": "梁峰：我当众立誓，三月之内必取那恶贼首级，为沈家满门偿命。"},
    {"n": "客套称赞", "new": False,
     "scene": "梁峰：「夫人院中花木甚好。」\n温夫人：「公子过奖。」"},
]


def run_add(timeout):
    schema = {
        "type": "object",
        "properties": {
            "新增": {"type": "string", "enum": ["是", "否"]},
            "标题": {"type": "string"},
            "描述": {"type": "string"},
            "委托人": {"type": "string"},
            "里程碑": {"type": "array", "items": {"type": "string"}},
            "时限": {"type": "string"},
        },
        "required": ["新增", "标题", "描述", "里程碑", "时限"],
    }
    ok_new = ok_field = 0
    lat = []
    for i, c in enumerate(ADD_CASES):
        user = f"本轮叙事：\n{c['scene']}\n\n是否新增任务？是则抽出字段。"
        t0 = time.time()
        try:
            r = _ask(ADD_SYSTEM, user, schema, max_tokens=160, timeout=timeout) or {}
        except Exception as e:
            print(f"💥 [{i}] {c['n']}：{type(e).__name__}: {e}")
            continue
        lat.append(time.time() - t0)
        got_new = r.get("新增") == "是"
        match = got_new == c["new"]
        ok_new += match
        complete = ""
        if c["new"] and got_new:
            has = bool(str(r.get("标题") or "").strip()) and \
                  bool(r.get("里程碑")) and bool(str(r.get("时限") or "").strip())
            ok_field += has
            complete = "字段全" if has else "字段缺"
        elif c["new"] and not got_new:
            complete = "漏建"
        elif (not c["new"]) and got_new:
            complete = "误建"
        else:
            complete = "正确未建"
        print(f"{'✅' if match else '❌'} [{i}] {c['n']:<12} 期望{'建' if c['new'] else '不建'} "
              f"得={'建' if got_new else '不建'}（{complete}）"
              + (f" 『{r.get('标题')}』{r.get('里程碑')}" if got_new else ""))
    n = len(ADD_CASES)
    print(f"  add 判定正确 {ok_new}/{n}；建对且字段齐 {ok_field}/{sum(1 for c in ADD_CASES if c['new'])}")
    if lat:
        print(f"  延迟 均 {statistics.mean(lat):.2f}s")
    return ok_new, n


# ============================================================
# B/C. 共享任务清单
# ============================================================
QUESTS = {
    "q1": {"标题": "查明失踪的姑娘们",
           "里程碑": ["去城西打听", "找到人贩落脚处", "救出姑娘们"]},
    "q2": {"标题": "投亲",
           "里程碑": ["打听到崔家住处", "上门拜访", "问出父母消息"]},
}


def _quest_list(qid):
    q = QUESTS[qid]
    ms = " ".join(f"{i+1}.{m}" for i, m in enumerate(q["里程碑"]))
    return f"{qid}｜{q['标题']}｜里程碑：{ms}"


UPDATE_SYSTEM = (
    "你是南宋武侠游戏的「任务进度判定器」，只输出 JSON。"
    "给你一个进行中的任务（含里程碑）和本轮叙事，判断本轮**是否完成/推进了其中某一个里程碑**。"
    "只有叙事里**明确做到**了才选「是」，并原样抄回那个里程碑的文字；只是提到、计划、打听一半都不算。"
    "拿不准选「否」。禁止思考、禁止解释、禁止输出 JSON 以外的内容。/no_think"
)

UPDATE_CASES = [
    {"q": "q1", "scene": "梁峰：我在城西一家茶摊坐了半日，终于从脚夫口中问出——那两人是被一伙人贩带上船的。",
     "expect": "去城西打听"},
    {"q": "q1", "scene": "梁峰：我回到客栈睡下，一夜无话。", "expect": None},
    {"q": "q1", "scene": "梁峰：我循着线索摸到城南破庙后的窝点，亲眼认出关着姑娘们的那间屋子。",
     "expect": "找到人贩落脚处"},
    {"q": "q2", "scene": "梁峰：我在城门处向老卒打听，终于问明崔家住在城南水巷。",
     "expect": "打听到崔家住处"},
]


def run_update(timeout):
    schema = {
        "type": "object",
        "properties": {"推进": {"type": "string", "enum": ["是", "否"]},
                       "里程碑": {"type": "string"}},
        "required": ["推进"],
    }
    ok = 0
    lat = []
    for i, c in enumerate(UPDATE_CASES):
        user = (f"进行中的任务：\n{_quest_list(c['q'])}\n\n本轮叙事：\n{c['scene']}\n\n"
                f"本轮推进了哪个里程碑？没有就选「否」。")
        t0 = time.time()
        try:
            r = _ask(UPDATE_SYSTEM, user, schema, max_tokens=60, timeout=timeout) or {}
        except Exception as e:
            print(f"💥 [{i}]：{type(e).__name__}: {e}")
            continue
        lat.append(time.time() - t0)
        got = "是" == r.get("推进")
        ms = str(r.get("里程碑") or "").strip()
        want = c["expect"]
        match = (got and want and want in ms) or ((not got) and want is None)
        # 只选对里程碑、没选错
        if got and want and want not in ms:
            match = False
        ok += match
        print(f"{'✅' if match else '❌'} [{i}] 期望={want or '无'} 得={'推进:' + ms if got else '否'}")
    n = len(UPDATE_CASES)
    print(f"  update 正确 {ok}/{n}")
    if lat:
        print(f"  延迟 均 {statistics.mean(lat):.2f}s")
    return ok, n


COMPLETE_SYSTEM = (
    "你是南宋武侠游戏的「任务完成判定器」，只输出 JSON。"
    "给你若干进行中的任务和本轮叙事，判断本轮**是否彻底完成了其中某一个任务**"
    "（目标达成、事情了结）。只是推进了一步、或还在做，都不算。"
    "完成就抄回该任务标题，否则选「否」。禁止思考、禁止解释、禁止输出 JSON 以外的内容。/no_think"
)

COMPLETE_CASES = [
    {"q": ["q2"], "scene": "梁峰：我拜访崔家，得知父母当年已亡故，崔家交给我一件遗物。", "done": "投亲"},
    {"q": ["q2"], "scene": "梁峰：我在城中转了几圈，仍没找到崔家的门。", "done": None},
    {"q": ["q1", "q2"], "scene": "梁峰：我将那伙人贩扭送官府，被掳的姑娘们都平安回了锦香宫。", "done": "查明失踪的姑娘们"},
    {"q": ["q1", "q2"], "scene": "梁峰：我还在打听人贩的下落，暂且没有结果。", "done": None},
]


def run_complete(timeout):
    schema = {
        "type": "object",
        "properties": {"完成": {"type": "string", "enum": ["是", "否"]},
                       "任务": {"type": "string"}},
        "required": ["完成"],
    }
    ok = 0
    lat = []
    for i, c in enumerate(COMPLETE_CASES):
        qlist = "\n".join(_quest_list(q) for q in c["q"])
        user = f"进行中的任务：\n{qlist}\n\n本轮叙事：\n{c['scene']}\n\n本轮完成了哪个任务？没有就选「否」。"
        t0 = time.time()
        try:
            r = _ask(COMPLETE_SYSTEM, user, schema, max_tokens=60, timeout=timeout) or {}
        except Exception as e:
            print(f"💥 [{i}]：{type(e).__name__}: {e}")
            continue
        lat.append(time.time() - t0)
        got = "是" == r.get("完成")
        title = str(r.get("任务") or "").strip()
        want = c["done"]
        match = (got and want and want in title) or ((not got) and want is None)
        ok += match
        print(f"{'✅' if match else '❌'} [{i}] 期望={want or '无'} 得={'完成:' + title if got else '否'}")
    n = len(COMPLETE_CASES)
    print(f"  complete 正确 {ok}/{n}")
    if lat:
        print(f"  延迟 均 {statistics.mean(lat):.2f}s")
    return ok, n


def main():
    ap = argparse.ArgumentParser(description="测小模型能否做任务三操作")
    ap.add_argument("--mode", choices=["add", "update", "complete", "all"], default="all")
    ap.add_argument("--timeout", type=float, default=10.0)
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--mock", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()

    global MOCK
    MOCK = args.mock
    if not MOCK and not small_model.available():
        print("❌ 小模型不可用：请确认 LM Studio 已启动并加载 qwen/qwen3-4b-2507。")
        sys.exit(2)

    agg = {}
    for rep in range(args.repeats):
        if args.repeats > 1:
            print(f"\n########## 第 {rep + 1}/{args.repeats} 轮 ##########")
        if args.mode in ("add", "all"):
            print("\n===== A. add_quest（该建才建）=====")
            a, n = run_add(args.timeout); agg["add"] = agg.get("add", 0) + a; agg["add_n"] = agg.get("add_n", 0) + n
        if args.mode in ("update", "all"):
            print("\n===== B. update_quest（推进哪个里程碑）=====")
            a, n = run_update(args.timeout); agg["up"] = agg.get("up", 0) + a; agg["up_n"] = agg.get("up_n", 0) + n
        if args.mode in ("complete", "all"):
            print("\n===== C. complete_quest（是否完成）=====")
            a, n = run_complete(args.timeout); agg["cp"] = agg.get("cp", 0) + a; agg["cp_n"] = agg.get("cp_n", 0) + n
    if args.repeats > 1:
        print("\n" + "=" * 78)
        print(f"合计：add {agg.get('add',0)}/{agg.get('add_n',0)}  "
              f"update {agg.get('up',0)}/{agg.get('up_n',0)}  "
              f"complete {agg.get('cp',0)}/{agg.get('cp_n',0)}")


if __name__ == "__main__":
    main()
