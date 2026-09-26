# -*- coding: utf-8 -*-
"""
verify_gm_speed.py
==================
对比「大模型当 GM」的响应速度：DeepSeek vs 其他 OpenAI 兼容端点（如 gpt-6-luna）。

方法：同一套消息（真实 `主持人/*.md` 规则 + 状态 + 玩家行动）与同一工具集
（`registry.ALL_TOOLS` 清洗版），各跑 N 次，比较**单次 LLM 往返**延迟。

注意：
    - 这是**单次往返**耗时；一局真实回合可能多次往返（工具循环），按往返数线性放大。
    - 同一 endpoint 连续调用会命中前缀缓存 → 后续更快（真实游玩也一样受益）。
    - 默认每模型先跑 1 次预热（不计入），再测 N 次。

用法（trpg-server 下）：
    python 开发/verify_gm_speed.py                 # 各 3 次
    python 开发/verify_gm_speed.py --runs 5
    python 开发/verify_gm_speed.py --only gpt-6-luna
    python 开发/verify_gm_speed.py --prompt "梁峰拔剑在手，环顾四周。"
"""

from __future__ import annotations

import argparse
import glob
import json
import os
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

from dotenv import load_dotenv  # noqa: E402
from openai import OpenAI  # noqa: E402
import llm  # noqa: E402  （复用清洗好的工具 schema）

load_dotenv()

DEFAULT_PROMPT = "梁峰：我走进客栈，问掌柜要一间上房。"
DEFAULT_STATE = ("===== 当前状态 =====\n"
                 "位置：扬州·城南水巷（城内）\n"
                 "时间：嘉定十三年正月十七 申时\n"
                 "天气：晴，微风")


def _rules() -> str:
    files = sorted(glob.glob(str(SERVER.parent / "trpg-world" / "主持人" / "*.md")))
    return "\n\n".join(Path(f).read_text(encoding="utf-8") for f in files)


def _messages(prompt: str) -> list:
    return [
        {"role": "system", "content": _rules()},
        {"role": "user", "content": prompt},
        {"role": "system", "content": DEFAULT_STATE},
    ]


def _targets() -> list[dict]:
    """要对比的模型：DeepSeek（.env）+ 配置/大模型.json 里的远端端点。"""
    out = [{
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "api_key": os.getenv("LLM_API_KEY", ""),
        "model": "deepseek-v4-flash",
    }]
    try:
        cfg = json.loads((SERVER / "配置" / "大模型.json").read_text(encoding="utf-8"))
        if cfg.get("base_url") and "deepseek.com" not in cfg["base_url"]:
            out.append({
                "name": cfg.get("model") or "remote",
                "base_url": cfg["base_url"],
                "api_key": cfg.get("api_key") or os.getenv(cfg.get("api_key_env") or "", ""),
                "model": cfg.get("model"),
            })
    except (OSError, json.JSONDecodeError):
        pass
    return out


def _one(target: dict, messages: list, timeout: float) -> tuple:
    """跑一次，返回 (秒, 是否工具调用, content 长度)。"""
    cli = OpenAI(api_key=target["api_key"] or "none", base_url=target["base_url"],
                 timeout=timeout, max_retries=0)
    t0 = time.time()
    resp = cli.chat.completions.create(
        model=target["model"], messages=messages, tools=llm._ALL_TOOLS_PLAIN)
    dt = time.time() - t0
    m = resp.choices[0].message
    return dt, bool(m.tool_calls), len(m.content or "")


def main():
    ap = argparse.ArgumentParser(description="对比大模型 GM 的响应速度")
    ap.add_argument("--runs", type=int, default=3, help="每个模型测几次（默认 3）")
    ap.add_argument("--warmup", type=int, default=1, help="预热次数（不计入）")
    ap.add_argument("--timeout", type=float, default=180)
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    ap.add_argument("--only", default="", help="只测名字包含该串的模型")
    args = ap.parse_args()

    messages = _messages(args.prompt)
    targets = [t for t in _targets() if args.only.lower() in t["name"].lower()]
    if not targets:
        print("❌ 没有可测的模型（检查 .env 的 LLM_API_KEY / 配置/大模型.json）")
        sys.exit(2)

    print(f"规则字数 {len(messages[0]['content'])}｜工具 {len(llm._ALL_TOOLS_PLAIN)} 个"
          f"｜每模型 预热 {args.warmup} + 测 {args.runs}")
    print("=" * 62)
    summary = []
    for t in targets:
        for _ in range(max(0, args.warmup)):
            try:
                _one(t, messages, args.timeout)
            except Exception as e:
                print(f"⚠️  {t['name']} 预热失败：{type(e).__name__}: {str(e)[:80]}")
                break
        times, tool_hits = [], 0
        for i in range(max(1, args.runs)):
            try:
                dt, tcall, clen = _one(t, messages, args.timeout)
            except Exception as e:
                print(f"❌ {t['name']} 第{i+1}次失败：{type(e).__name__}: {str(e)[:120]}")
                continue
            times.append(dt)
            tool_hits += 1 if tcall else 0
            print(f"  {t['name']:<16} #{i+1}  {dt:6.2f}s   {'工具调用' if tcall else f'直接输出{clen}字'}")
        if times:
            summary.append((t["name"], times, tool_hits))

    print("=" * 62)
    print(f"{'模型':<18}{'均':>8}{'中位':>8}{'最快':>8}{'最慢':>8}   工具调用")
    for name, times, hits in summary:
        print(f"{name:<18}{statistics.mean(times):>7.2f}s{statistics.median(times):>7.2f}s"
              f"{min(times):>7.2f}s{max(times):>7.2f}s   {hits}/{len(times)}")


if __name__ == "__main__":
    main()
