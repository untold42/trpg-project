# -*- coding: utf-8 -*-
"""
director_probe.py
=================
【诊断脚本，非正式模块】验证「导演」接入《故事大纲》后是否真的能干活。

测什么：
    A 首局（无前情）      —— 会不会给出一个**把玩家拉进主线的开场钩子**，且不剧透；
    B 有前情（含悬线）    —— 会不会**做减法**（1 主线 + ≤2 支线 + 穷尽冷藏/砍）、
                             能不能自己挖出「主角行动未交代」的线、是否服务大纲主线方向；
    C 与不带大纲对比       —— 同一材料，看接纲前后差异（可选，`--no-outline`）。

顺带产出硬指标：
    - 字数（大纲要求 ≤500）、耗时；
    - **剧透扫描**：身份/结局底牌词是否漏进简报（简报会进 GM 上下文，漏了就是事故）。

运行（需 `.env` 里有 `GLM_API_KEY`；GLM 慢，一次 40–200s，429 常见会重试）：
    cd trpg-server
    python director_probe.py            # 跑 A + B
    python director_probe.py --only a
    python director_probe.py --no-outline   # 对照：不喂大纲（临时把 OUTLINE_PATH 指向空）

退出码：0=跑完；2=GLM 不可用（缺 key / 全部失败）。
"""

from __future__ import annotations

import argparse

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:  # Windows 控制台默认 GBK，会把中文打成乱码
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from tools import director  # noqa: E402

REPORT = Path(__file__).resolve().parent / "director_probe_out.md"

# 场景 B：一段「日常戏 + 悬线混杂」的上一局存档（刻意埋 3 类未回收的线）
STORY_B = """\
1220-01-17 戌时 岳阳·巴陵街

 旁白：梁峰在巴陵街的酒肆里坐下，要了一壶温酒。邻桌几个脚夫正抱怨漕运抽成又涨了。
 旁白：梁峰听了一阵，没插话。
梁峰：小二，再添碟茴香豆。
 旁白：酒喝到戌时末，梁峰起身回客栈歇了。

 旁白：回想过往——三日前，他在洞庭湖畔遇一名卖唱的盲女，女孩托他带一句话给城西
       破庙里的哥哥「阿七」，说她还活着。梁峰当时答应了，这几日却一直没去。
 旁白：也是三日前，锦香宫的盛雪在湖畔救起落水的梁峰同伴，临走时撂下一句：
       「三日后到君山岛来，温夫人有话问你。」梁峰点头应下。今日正是第三日。

 旁白：那日他在西门入城，守门的老卒收了前面商队一只布包便放行，却拦住他盘问许久。
       梁峰留了心，觉得那老卒未必只图财。

 旁白：另有一桩——他在码头听人闲谈，说近来洞庭水匪劫了三艘漕船，官府却压着不查，
       有人疑心是白鲨帮借水匪的名头做事。梁峰当时只是听着。

 旁白：这一晚，什么也没有发生。
"""


def _scan_spoiler(text: str) -> list[str]:
    return director.scan_spoilers(text)  # 单一真相源：director.SPOILER_TERMS


def _selftest():
    """离线验证代码兼底（不调 GLM）：泄漏 → 重试改写；再漏 → 机械消弧。"""
    orig_save, orig_gen = director._save, director.generate
    try:
        # ① 第一次泄漏，重试干净 → 用重试版
        saved, calls = {}, {"n": 0}

        def gen_retry_ok(material, extra_hint=""):
            calls["n"] += 1
            return ("禁止揭示“五神共选”身份。" if calls["n"] == 1
                    else "不得直说他那身五行之力的来历。")

        director._save = lambda s, c="", e="": saved.__setitem__(s, c)
        director.generate = gen_retry_ok
        director._work("材料")
        assert calls["n"] == 2, f"应重试一次，实际 {calls['n']} 次"
        assert not director.scan_spoilers(saved.get("ok", "")), saved.get("ok")
        print("兼底自测① 泄漏→重试改写→干净 ✅")

        # ② 两次都漏 → 就地消弧，仍不得漏
        saved, calls = {}, {"n": 0}

        def gen_always_leak(material, extra_hint=""):
            calls["n"] += 1
            return "他是五神共选之子，瑞杏是多周目者。"

        director._save = lambda s, c="", e="": saved.__setitem__(s, c)
        director.generate = gen_always_leak
        director._work("材料")
        out = saved.get("ok", "")
        assert calls["n"] == 2 and not director.scan_spoilers(out), out
        print(f"兼底自测② 两次都漏→机械消弧 ✅：{out}")
    finally:
        director._save, director.generate = orig_save, orig_gen


def _run(name: str, material: str, with_outline: bool = True):
    if not with_outline:
        director.OUTLINE_PATH = Path("__nonexistent__.md")
        director._outline_cache = None

    outline_chars = len(director.outline_text())
    head = f"\n{'=' * 68}\n【{name}】大纲注入：{outline_chars} 字 | 材料：{len(material)} 字\n{'=' * 68}"
    print(head)
    t0 = time.time()
    try:
        out = director.generate(material)
    except Exception as e:
        print(f"!! 生成失败：{type(e).__name__}: {e}")
        return None, head + f"\n!! 生成失败：{type(e).__name__}: {e}\n"
    dt = time.time() - t0
    if not out:
        print("!! 空输出")
        return None, head + "\n!! 空输出\n"
    hits = _scan_spoiler(out)
    verdict = f"耗时 {dt:.0f}s | 正文 {len(out)} 字 | 剧透扫描：{('命中 ' + str(hits) + ' ❌') if hits else '干净 ✅'}"
    print(out)
    print("-" * 68)
    print(verdict)
    # 控制台可能仍乱码 → 原始报告同时落 UTF-8 文件
    return out, f"{head}\n\n{out}\n\n{'-' * 68}\n{verdict}\n"


def _run_e2e(name: str, material: str):
    """跑生产路径 director._work（重试 + 消弧），结果捕到内存，不污染真实简报。"""
    saved: dict = {}
    calls = {"n": 0}
    orig_save, orig_gen = director._save, director.generate

    def counting_gen(m, extra_hint=""):
        calls["n"] += 1
        return orig_gen(m, extra_hint=extra_hint)

    director._save = lambda s, c="", e="": saved.__setitem__(s, c)
    director.generate = counting_gen
    t0 = time.time()
    try:
        director._work(material)
    finally:
        director._save, director.generate = orig_save, orig_gen
    dt = time.time() - t0
    out = saved.get("ok", "")
    hits = director.scan_spoilers(out)
    verdict = (f"耗时 {dt:.0f}s（GLM 调用 {calls['n']} 次）| 正文 {len(out)} 字 | "
               f"剧透扫描：{('命中 ' + str(hits) + ' ❌') if hits else '干净 ✅'}")
    print(out)
    print("-" * 68)
    print(verdict)
    REPORT.write_text(f"# director_probe E2E\n\n{out}\n\n{'-' * 68}\n{verdict}\n",
                      encoding="utf-8")
    print(f"报告已写入 {REPORT}")
    return 0 if (out and not hits) else 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["a", "b"], help="只跑某一场")
    ap.add_argument("--no-outline", action="store_true", help="对照组：不喂大纲")
    ap.add_argument("--e2e", action="store_true",
                    help="跑生产路径 director._work（含泄漏重试/消弧），只跑 A")
    args = ap.parse_args()

    if not director.ENABLED:
        print("TRPG_DIRECTOR=0，导演已关闭")
        return 2

    _selftest()

    if args.e2e:
        return _run_e2e("A 首局（生产路径 _work）", director._first_material())

    with_outline = not args.no_outline
    report = ["# director_probe 报告", f"大纲：{'注入' if with_outline else '未注入(对照)'}", ""]
    ok = False
    if args.only != "b":
        out, block = _run("A 首局·无前情（找开场钩子）", director._first_material(), with_outline)
        report.append(block)
        ok = ok or bool(out)
    if args.only != "a":
        out, block = _run("B 有前情·悬线混杂（考取舍与找漏）", STORY_B, with_outline)
        report.append(block)
        ok = ok or bool(out)
    REPORT.write_text("\n".join(report), encoding="utf-8")
    print(f"\n报告已写入 {REPORT}")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
