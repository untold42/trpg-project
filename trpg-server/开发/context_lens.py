#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
context_lens.py
===============
把 `sessions/context_dump/*.json`（`context_dump.py` 抓的真实请求）渲染成一个静态 HTML。

用法：
    python context_lens.py            # 生成 sessions/context_report.html
    python context_lens.py --open     # 生成并用浏览器打开
    python context_lens.py --last 3   # 只看最近 3 轮

独立于游戏：只读 dump 文件，不 import 游戏状态、不起服务器、不连数据库。
"""

from __future__ import annotations

import argparse
import html
import json
import sys
import time
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
DUMP_DIR = SERVER_DIR / "sessions" / "context_dump"
DEFAULT_OUT = SERVER_DIR / "sessions" / "context_report.html"

#: 玩家输入的几种前缀（与 main.py / engine.py 保持一致）
USER_PREFIXES = [
    ("玩家的对主持人说的话：", "场外话（主持人）"),
    ("梁峰开口说：「", "台词"),
    ("梁峰：", "行动"),
]


def block_of(message: dict) -> str:
    """给一条消息起个短标签：块名 / 玩家输入类型 / 角色。"""
    role = message.get("role") or "?"
    content = message.get("content")
    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, default=str)

    if role == "system" and text.startswith("====="):
        head = text.split("=====", 2)
        if len(head) >= 3 and head[2].startswith("="):
            title = text.split("\n", 1)[0].strip("= ").strip()
            if title:
                return title
    if role == "user":
        for prefix, label in USER_PREFIXES:
            if text.startswith(prefix):
                return label
        return "玩家输入（其他）"
    if role == "assistant":
        return "模型输出"
    if role == "tool":
        return "工具返回"
    return "系统（其他）"


def text_of(message: dict) -> str:
    content = message.get("content")
    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, default=str)
    calls = message.get("tool_calls") or []
    if calls:
        text += "\n\n--- tool_calls ---\n" + json.dumps(calls, ensure_ascii=False, indent=1, default=str)
    return text or "（空）"


def load_dumps(last: int = 0) -> list[dict]:
    if not DUMP_DIR.is_dir():
        return []
    files = sorted(DUMP_DIR.glob("*.json"))
    if last > 0:
        files = files[-last:]
    out = []
    for path in files:
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def render(dumps: list[dict], out_path: Path) -> None:
    turns: list[str] = []
    for record in dumps:
        messages = record.get("messages") or []
        rows: list[str] = []
        for i, message in enumerate(messages, 1):
            label = block_of(message)
            body = text_of(message)
            rows.append(
                f'<details class="msg" data-search="{html.escape(label)}">'
                f'<summary><span class="idx">#{i:02d}</span>'
                f'<span class="role">{html.escape(message.get("role") or "?")}</span>'
                f'<span class="block">{html.escape(label)}</span>'
                f'<span class="size">{len(body):,} 字</span></summary>'
                f'<pre>{html.escape(body)}</pre></details>'
            )
        tool_names = record.get("工具") or []
        turns.append(
            '<section class="turn">'
            f'<h2><span class="seq">#{record.get("序号", 0):04d}</span> '
            f'{html.escape(record.get("时间") or "")}'
            f'<span class="dim"> · {html.escape(record.get("模型") or "")}</span>'
            f'<span class="dim"> · {len(messages)} 条消息</span>'
            f'<span class="dim"> · 正文 {record.get("正文字符数", 0):,} 字</span>'
            f'<span class="dim"> · 工具 {len(tool_names)} 个（{(record.get("工具字符数") or 0):,} 字）</span></h2>'
            f'<div class="tools">工具：{html.escape("、".join(str(n) for n in tool_names)) or "（无）"}</div>'
            + "".join(rows) +
            '</section>'
        )

    newest = dumps[-1] if dumps else {}
    tools_json = html.escape(json.dumps(newest.get("tools") or [], ensure_ascii=False, indent=1))
    total = sum(d.get("正文字符数", 0) for d in dumps)

    page = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>LLM 上下文 · 实际发送记录</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ margin: 0; padding: 20px 24px 80px; background: #14120f; color: #e8e2d6;
         font: 14px/1.6 "Microsoft YaHei", system-ui, sans-serif; }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  .meta {{ color: #9c9384; font-size: 12px; margin-bottom: 16px; }}
  .toolbar {{ position: sticky; top: 0; z-index: 5; background: #14120ff2; padding: 10px 0;
              border-bottom: 1px solid #38312a; display: flex; gap: 8px; align-items: center; }}
  .toolbar input {{ flex: 1; max-width: 420px; background: #0e0c0a; color: #e8e2d6;
                    border: 1px solid #4a4136; border-radius: 4px; padding: 6px 10px; }}
  .toolbar button {{ background: #2a241d; color: #d8cbb4; border: 1px solid #4a4136;
                     border-radius: 4px; padding: 6px 12px; cursor: pointer; }}
  .toolbar button:hover {{ background: #3a3128; }}
  .turn {{ margin: 26px 0 0; border-top: 1px solid #38312a; padding-top: 12px; }}
  .turn h2 {{ font-size: 14px; font-weight: 600; margin: 0 0 8px; color: #f0d9a8; }}
  .seq {{ color: #c8a35c; }}
  .dim {{ color: #8d8474; font-weight: 400; }}
  .tools {{ color: #8d8474; font-size: 12px; margin-bottom: 10px; }}
  details.msg {{ border-left: 2px solid #3d352c; margin: 4px 0; background: #191612; }}
  details.msg[open] {{ border-left-color: #c8a35c; }}
  details.msg > summary {{ cursor: pointer; padding: 5px 10px; display: flex; gap: 10px;
                           align-items: baseline; list-style: none; }}
  details.msg > summary::-webkit-details-marker {{ display: none; }}
  details.msg > summary:hover {{ background: #221d17; }}
  .idx {{ color: #7d7364; width: 34px; flex: none; }}
  .role {{ color: #86a5c8; width: 74px; flex: none; }}
  .block {{ color: #d8cbb4; flex: 1; }}
  .size {{ color: #7d7364; flex: none; }}
  pre {{ margin: 0; padding: 10px 14px 14px; white-space: pre-wrap; word-break: break-word;
         background: #0e0c0a; color: #cfc7b8; font: 12.5px/1.55 Consolas, "Courier New", monospace; }}
  .empty {{ color: #9c9384; }}
  details.schema {{ margin-top: 30px; border-top: 1px solid #38312a; padding-top: 10px; }}
  details.schema > summary {{ cursor: pointer; color: #f0d9a8; font-weight: 600; }}
  [hidden] {{ display: none !important; }}
</style></head><body>
<h1>LLM 上下文 · 实际发送记录</h1>
<div class="meta">{len(dumps)} 轮 · 正文合计 {total:,} 字 · 渲染于 {time.strftime("%Y-%m-%d %H:%M:%S")}
 · 来源 <code>{html.escape(str(DUMP_DIR))}</code></div>
<div class="toolbar">
  <input id="q" placeholder="过滤：只显示命中的消息（回车后自动展开）">
  <button onclick="setAll(true)">全部展开</button>
  <button onclick="setAll(false)">全部折叠</button>
  <span id="hit" class="dim"></span>
</div>
{"".join(turns) if turns else '<p class="empty">还没有 dump。用 TRPG_DUMP_CONTEXT=1 启动游戏，走一轮再回来。</p>'}
<details class="schema"><summary>工具 schema 全文（取最新一轮；共 {len(newest.get("tools") or [])} 个）</summary>
<pre>{tools_json}</pre></details>
<script>
function setAll(open) {{
  document.querySelectorAll("details.msg").forEach(function (d) {{ d.open = open; }});
}}
document.getElementById("q").addEventListener("input", function (e) {{
  var q = e.target.value.trim().toLowerCase();
  var hits = 0;
  document.querySelectorAll("section.turn").forEach(function (turn) {{
    var shown = 0;
    turn.querySelectorAll("details.msg").forEach(function (d) {{
      var hay = (d.dataset.search + " " + d.textContent).toLowerCase();
      var ok = !q || hay.indexOf(q) >= 0;
      d.hidden = !ok;
      if (ok) {{ shown++; hits++; if (q) d.open = true; }}
    }});
    turn.hidden = shown === 0;
  }});
  document.getElementById("hit").textContent = q ? ("命中 " + hits + " 条") : "";
}});
</script></body></html>"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="把真实发送的 LLM 上下文渲染成静态 HTML")
    parser.add_argument("--last", type=int, default=0, help="只看最近 N 轮（默认全部）")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="输出 HTML 路径")
    parser.add_argument("--open", action="store_true", help="生成后用浏览器打开")
    args = parser.parse_args()

    dumps = load_dumps(args.last)
    render(dumps, args.out)
    print(f"轮次 {len(dumps)}  →  {args.out}")
    if not dumps:
        print("（dump 目录为空：用 TRPG_DUMP_CONTEXT=1 启动 trpg-server 跑一轮）")

    if args.open:
        import webbrowser
        webbrowser.open(args.out.resolve().as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
