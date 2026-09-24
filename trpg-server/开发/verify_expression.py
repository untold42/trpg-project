# -*- coding: utf-8 -*-
"""
verify_expression.py
====================
【一次性验证脚本，非正式模块】表情选择是否适合交给本地小模型（Qwen3-4B）。

背景：
    `trpg-world/主持人/特定人物.md` 现在是靠**大模型**在输出 chat 时：
      ① 命中人物 → 调 `check_expression` 拿表情枚举 → 填 `expression`；
      ② 命中人物 → 调 `get_character` 读档案。
    本脚本验证「① 表情选择」能否改由小模型做（与 ui_sim 的场景/音乐同类）。
    ② 档案读取不进本脚本（那必须在大模型本轮生成前完成，不能事后补）。

做什么：
    用一批带**人工标注可接受集**的真实感台词，逐条（或批量）问 4B「选哪个表情」，
    统计：命中率、无效值率、失败率、延迟（p50/p95）。
    单表情角色（枚举只有「正常」）走确定性分支，不调模型。

运行（需 LM Studio 已加载 qwen/qwen3-4b-2507）：
    cd trpg-server
    python 开发/verify_expression.py              # 单条 + 批量 都测
    python 开发/verify_expression.py --mode single
    python 开发/verify_expression.py --mode batch
    python 开发/verify_expression.py --timeout 8 --repeats 2

退出码：0=跑完；2=小模型不可用（LM Studio 没起 / 模型没加载）。
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

# 允许 `python 开发/verify_expression.py` 直接跑（把 trpg-server 加入 import 路径）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")   # Windows 控制台默认 GBK，中文会乱码
except Exception:
    pass

from tools.小模型.character_expressions import CHARACTER_EXPRESSIONS  # noqa: E402
from tools.小模型 import small_model  # noqa: E402

# ------------------------------------------------------------
# 生产候选提示词（与未来 expression_sim 保持一致）
# ------------------------------------------------------------
SYSTEM = (
    "你是南宋武侠小说的「表情标注器」，只输出 JSON。"
    "给你一个角色名、TA 此刻的台词（及少量上下文）、以及**可用表情枚举**，"
    "从枚举里选**最贴合此刻心情/语气**的一个。"
    "**只能从给定枚举里选一个，不得自创、不得改写**；"
    "台词太短、信息不足、或拿不准时，选「正常」。"
    "禁止思考、禁止解释、禁止输出 JSON 以外的任何内容。/no_think"
)

#: --mock：不调小模型，直接用枚举第一项回填（仅用于验证脚本流程本身）
MOCK = False


def _ask(system: str, user: str, schema: dict, max_tokens: int, timeout: float):
    """对 small_model.ask_json 的薄封装（支持 --mock）。"""
    if MOCK:
        props = schema.get("properties") or {}
        return {k: ((v.get("enum") or ["正常"])[0]) for k, v in props.items()}
    return small_model.ask_json(system, user, schema, max_tokens=max_tokens, timeout=timeout)


# ------------------------------------------------------------
# 测试用例：{speaker, line, context?, accept:[可接受的表情，第一个为首选]}
# accept 必须都是该角色真实存在的表情（脚本会自检）。
# ------------------------------------------------------------
CASES = [
    {"speaker": "唐布衣", "line": "「唐门的东西，也是你能碰的？」",
     "context": "梁峰伸手去拿桌上的暗器囊。",
     "accept": ["愤怒", "生气", "严肃"]},
    {"speaker": "唐布衣", "line": "「噗……你这副模样，倒让我想起三师弟。」",
     "context": "梁峰一身泥水站在门口。",
     "accept": ["憋笑", "大笑", "开心"]},
    {"speaker": "叶云裳", "line": "「嘻嘻，我把他的靴子藏进灶膛里啦。」",
     "context": "她蹦蹦跳跳跑进来，一脸得意。",
     "accept": ["捣蛋", "调皮", "开心"]},
    {"speaker": "叶云裳", "line": "「哥哥……你别丢下我一个人。」",
     "context": "夜色里，她拽住梁峰的衣袖。",
     "accept": ["哭泣", "悲伤", "难过"]},
    {"speaker": "虞小梅", "line": "「这位公子，生得好生俊俏，可愿陪奴家说说话？」",
     "context": "她斜倚在栏杆上，眼波流转。",
     "accept": ["好色", "极端好色", "开心"]},
    {"speaker": "虞小梅", "line": "「不、不是我干的！你别看我！」",
     "context": "打翻的瓷瓶还在地上滚。",
     "accept": ["慌张", "紧张", "尴尬"]},
    {"speaker": "郁竹", "line": "「谁、谁要你多管闲事。」",
     "context": "她别过脸去，耳根发红。",
     "accept": ["害羞", "极端害羞", "尴尬"]},
    {"speaker": "刘鄂", "line": "「老子劈了你这条狗！」",
     "context": "他一脚踹翻条凳，抄起门后的朴刀。",
     "accept": ["狂暴", "愤怒", "生气"]},
    {"speaker": "龙湘", "line": "「唔……这鸡腿真香。你要不要来一口？」",
     "context": "她蹲在墙根，油光满面地啃着。",
     "accept": ["吃鸡腿", "开心"]},
    {"speaker": "上官隼", "line": "「鱼儿，上钩了。」",
     "context": "他立在暗处，望着街口那道身影。",
     "accept": ["阴险", "开心"]},
    {"speaker": "唐默铃", "line": "「啊！我、我把药方弄丢了！」",
     "context": "她翻遍了袖袋，脸色发白。",
     "accept": ["慌张", "极端慌张", "紧张"]},
    {"speaker": "魏菊", "line": "「哼，好一个正人君子。」",
     "context": "她将茶盏重重搁在桌上。",
     "accept": ["冷笑", "生气"]},
    {"speaker": "王二壮", "line": "「哈哈哈！痛快！再来一碗！」",
     "context": "酒肆里，他一巴掌拍在梁峰肩上。",
     "accept": ["大笑", "开心"]},
    {"speaker": "夏侯兰", "line": "「我什么都不知道呢。」",
     "context": "她指尖绕着发梢，唇边带笑。",
     "accept": ["伪装", "阴险", "极端阴险", "开心"]},
    {"speaker": "瑞杏", "line": "「急什么，先坐下喝盏茶。」",
     "context": "窗外喊杀隐隐，她却提着壶斟茶。",
     "accept": ["悠闲", "开心", "正常"]},
    {"speaker": "申屠龙", "line": "「你终于肯来了。」",
     "context": "他背手立在崖边，缓缓转身。",
     "accept": ["开心", "正常"]},
    # 单表情角色：应走确定性分支，不调模型
    {"speaker": "剑圣", "line": "「剑，不是这么用的。」",
     "context": "他随手一抖，剑尖凝而不发。",
     "accept": ["正常"]},
]


def _cands(name: str) -> list[str]:
    return list(CHARACTER_EXPRESSIONS.get(name, []))


def _selfcheck() -> None:
    """自检用例：角色存在、accept 都是真实枚举、首个为首选。"""
    bad = []
    for i, c in enumerate(CASES):
        cs = _cands(c["speaker"])
        if not cs:
            bad.append(f"#{i} {c['speaker']} 不在表情表中")
            continue
        for e in c["accept"]:
            if e not in cs:
                bad.append(f"#{i} {c['speaker']}: accept「{e}」不在枚举 {cs}")
    if bad:
        print("用例自检失败：")
        for b in bad:
            print("  -", b)
        sys.exit(1)


# ------------------------------------------------------------
# 调用
# ------------------------------------------------------------
def single_call(case: dict, timeout: float):
    """逐条问。返回 (got, seconds, raw)。"""
    name = case["speaker"]
    cands = _cands(name)
    if len(cands) == 1:                      # 确定性：不调模型
        return cands[0], 0.0, {"deterministic": True}
    schema = {
        "type": "object",
        "properties": {"expression": {"type": "string", "enum": cands}},
        "required": ["expression"],
    }
    user = (
        f"角色：{name}\n"
        f"上下文：{case.get('context') or '（无）'}\n"
        f"台词：{case['line']}\n"
        f"可用表情（只能选其一）：{cands}"
    )
    t0 = time.time()
    try:
        r = _ask(SYSTEM, user, schema, max_tokens=24, timeout=timeout)
    except Exception as e:
        return None, time.time() - t0, {"error": f"{type(e).__name__}: {e}"}
    return (r or {}).get("expression"), time.time() - t0, r


def batch_call(cases: list[dict], timeout: float):
    """一次问多个角色（同名只取第一次出现）。返回 {name: got}, seconds, raw。"""
    items = []
    seen = set()
    for c in cases:
        n = c["speaker"]
        cands = _cands(n)
        if len(cands) <= 1 or n in seen:
            continue
        seen.add(n)
        items.append((n, cands, c))
    if not items:
        return {}, 0.0, {}
    props = {n: {"type": "string", "enum": cands} for n, cands, _ in items}
    schema = {"type": "object", "properties": props, "required": [n for n, _, _ in items]}
    lines = []
    for n, cands, c in items:
        lines.append(f"- {n}｜上下文：{c.get('context') or '（无）'}｜台词：{c['line']}｜可选：{cands}")
    user = "下面每个角色各选一个表情：\n" + "\n".join(lines)
    t0 = time.time()
    try:
        r = _ask(SYSTEM, user, schema, max_tokens=40 * len(items), timeout=timeout)
    except Exception as e:
        return {}, time.time() - t0, {"error": f"{type(e).__name__}: {e}"}
    return (r or {}), time.time() - t0, r


# ------------------------------------------------------------
# 报告
# ------------------------------------------------------------
def _fmt(x: float) -> str:
    return f"{x:.2f}s"


def _lat_stats(lat: list[float]) -> str:
    lat = [x for x in lat if x > 0]
    if not lat:
        return "（无模型调用）"
    lat.sort()
    p95 = lat[min(len(lat) - 1, int(round(0.95 * (len(lat) - 1))))]
    return f"n={len(lat)}  均 {statistics.mean(lat):.2f}s  p50 {statistics.median(lat):.2f}s  p95 {p95:.2f}s  max {max(lat):.2f}s"


def run_single(cases, timeout):
    print("\n" + "=" * 78)
    print("【单条模式】逐条调用小模型")
    print("=" * 78)
    hits = primary = invalid = failed = 0
    lats = []
    for i, c in enumerate(cases):
        got, dt, raw = single_call(c, timeout)
        cands = _cands(c["speaker"])
        accept = c["accept"]
        if len(cands) == 1:
            status = "确定"
            hits += 1
            primary += 1
        elif got is None:
            status = "失败"
            failed += 1
            lats.append(dt)
        elif got not in cands:
            status = "越界"
            invalid += 1
            lats.append(dt)
        else:
            lats.append(dt)
            primary += (got == accept[0])
            if got in accept:
                hits += 1
                status = "命中" if got == accept[0] else "可接受"
            else:
                status = "偏离"
        mark = {"命中": "✅", "确定": "✅", "可接受": "🟡", "偏离": "❌",
                "越界": "⛔", "失败": "💥"}.get(status, "?")
        print(f"{mark} [{i:02d}] {c['speaker']:<5} 得={str(got):<6} 期望首选={accept[0]:<6} "
              f"可接受={accept}  {_fmt(dt)}  {status}")
        if raw and isinstance(raw, dict) and raw.get("error"):
            print(f"        raw error: {raw['error']}")
    n = len(cases)
    model_n = sum(1 for c in cases if len(_cands(c['speaker'])) > 1)
    print("-" * 78)
    print(f"总 {n} 条（其中 {model_n} 条需模型，{n - model_n} 条确定性跳过）")
    print(f"可接受命中率 {hits}/{n}   首选命中率 {primary}/{n}   越界 {invalid}   失败 {failed}")
    print("延迟：" + _lat_stats(lats))
    return hits, n, invalid, failed


def run_batch(cases, timeout):
    print("\n" + "=" * 78)
    print("【批量模式】所有多表情角色一次问（同名取首次）")
    print("=" * 78)
    got_map, dt, raw = batch_call(cases, timeout)
    hits = invalid = failed = 0
    model_cases = []
    seen = set()
    for c in cases:
        if len(_cands(c["speaker"])) <= 1 or c["speaker"] in seen:
            continue
        seen.add(c["speaker"])
        model_cases.append(c)
    for c in model_cases:
        n = c["speaker"]
        got = got_map.get(n)
        cands = _cands(n)
        if got is None:
            failed += 1
            status = "失败"
        elif got not in cands:
            invalid += 1
            status = "越界"
        elif got in c["accept"]:
            hits += 1
            status = "命中" if got == c["accept"][0] else "可接受"
        else:
            status = "偏离"
        mark = {"命中": "✅", "可接受": "🟡", "偏离": "❌", "越界": "⛔", "失败": "💥"}.get(status, "?")
        print(f"{mark} {n:<5} 得={str(got):<6} 期望首选={c['accept'][0]:<6} 可接受={c['accept']}  {status}")
    if raw and isinstance(raw, dict) and raw.get("error"):
        print("raw error:", raw["error"])
    print("-" * 78)
    print(f"批量一次调用，含 {len(model_cases)} 个角色，耗时 {_fmt(dt)}"
          f"（单条模式若逐个调约需 {len(model_cases)}×）")
    print(f"可接受命中率 {hits}/{len(model_cases)}   越界 {invalid}   失败 {failed}")
    return hits, len(model_cases), invalid, failed


def main():
    ap = argparse.ArgumentParser(description="验证小模型选表情是否可行")
    ap.add_argument("--mode", choices=["single", "batch", "both"], default="both")
    ap.add_argument("--timeout", type=float, default=10.0, help="单次调用超时（秒）")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条（0=全部）")
    ap.add_argument("--repeats", type=int, default=1, help="重复轮数（看稳定性）")
    ap.add_argument("--mock", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()

    global MOCK
    MOCK = args.mock
    _selfcheck()
    cases = CASES[: args.limit] if args.limit > 0 else CASES

    if not MOCK and not small_model.available():
        print("❌ 小模型不可用：请确认 LM Studio 已启动并加载 qwen/qwen3-4b-2507。")
        print("   （只想验证脚本流程可用 --mock）")
        sys.exit(2)
    print(f"小模型{'[MOCK]' if MOCK else ''}；用例 {len(cases)} 条；timeout={args.timeout}s；repeats={args.repeats}")

    total_hits = total_n = 0
    for rep in range(args.repeats):
        if args.repeats > 1:
            print(f"\n########## 第 {rep + 1}/{args.repeats} 轮 ##########")
        if args.mode in ("single", "both"):
            h, n, _, _ = run_single(cases, args.timeout)
            total_hits += h
            total_n += n
        if args.mode in ("batch", "both"):
            run_batch(cases, args.timeout)
    if args.mode == "single" and args.repeats > 1:
        print(f"\n合计可接受命中率：{total_hits}/{total_n}")


if __name__ == "__main__":
    main()
