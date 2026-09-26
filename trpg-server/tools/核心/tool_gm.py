# -*- coding: utf-8 -*-
"""
tool_gm.py
==========
**工具 GM**（异步 worker）：把叙事 GM 写下的「工具意图」（自然语言）落成真实状态变更。

设计：`trpg-server/文档/设计-双GM拆分.md`。
链路：
    叙事GM（DeepSeek，只读工具）→ `tool` 意图
      → 本模块入队（单 worker + FIFO）
      → 工具GM（默认 luna 开思考；**失败重试 3 次 → 回退 DeepSeek**）
           据当前状态 + 意图，调 20 个工具（TOOL_GM_TOOLS）逐条落地
      → 写 `sessions/工具日志.jsonl`（审计）+ 推 `kind:"toollog"` 让前端刷新日志面板

要点：
    - **只执行、不叙事**（提示词禁叙事）。
    - 工具白名单 = `TOOL_GM_TOOL_NAMES`（幻觉调用会被拒）。
    - 失败不清空：意图与结果都进日志，玩家可据此找叙事GM 纠正。
"""

from __future__ import annotations

import json
import queue
import threading
import time
from collections import deque
from pathlib import Path

from tools.大模型.registry import TOOL_GM_TOOLS, TOOL_GM_TOOL_NAMES, TOOLS_MAP
from tools.核心.state_manager import state

SERVER_DIR = Path(__file__).resolve().parent.parent.parent
LOG_FILE = SERVER_DIR / "sessions" / "工具日志.jsonl"

_RECENT: deque = deque(maxlen=40)      # 供前端 / 叙事GM 读的最近日志
_log_lock = threading.Lock()

_jobs: "queue.Queue" = queue.Queue(maxsize=32)
_worker_lock = threading.Lock()
_worker_on = False

#: 已入队但**尚未落地**的意图（供叙事GM 每轮看到，防重复扣钱）
_pending_lock = threading.Lock()
_pending: list[dict] = []
_next_id = 0

SYSTEM = (
    "你是南宋武侠游戏的后台「工具执行器」。读下面这段**本轮叙事**（主持人已写出来、已经发生的事），"
    "判断玩家/世界的状态应发生哪些变更，调用相应工具把它们落地。\n"
    "规则：\n"
    "1. 只调用工具，**禁止输出任何叙事/解释文字**。\n"
    "2. **只处理叙事里明确发生的事**；闲聊、寒暄、没有实际动作的对话，**不要调任何工具**。\n"
    "3. 数量没写明的（物价、扣多少血等）按南宋常识给合理值。\n"
    "4. 一件事可能需要多个工具（「买一壶酒揣进怀里」= 减钱 + 加物品）。\n"
    "5. **时间**：只有叙事明确写了经过多久（「睡到天明」「行了两个时辰」）才调 advance_time/sleep；否则**不要动时间**。\n"
    "6. 不要重复调用同一个（同一笔只扣一次）。\n"
    "7. 拿不准要不要改的，**宁可不改**。\n"
    "8. 状态（钱/背包/属性）已在上面给出，**不要调用任何查询类工具**（get_state/get_money/get_inventory 等）——只调会改变状态的工具。"
)


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


# ------------------------------------------------------------
# 入队 / worker
# ------------------------------------------------------------
def submit(narration: str, mode: str, game_time: str = "") -> None:
    """把**本轮叙事**交给后台工具GM（不阻塞）——工具GM 自己读叙事、判断并调工具。"""
    global _worker_on, _next_id
    text = str(narration or "").strip()
    if not text:
        return
    with _worker_lock:
        if not _worker_on:
            threading.Thread(target=_worker, daemon=True, name="tool-gm").start()
            _worker_on = True
    _next_id += 1
    job = {"id": _next_id, "text": text, "mode": mode, "game_time": game_time}
    with _pending_lock:
        _pending.append(job)
    try:
        _jobs.put_nowait(job)
    except queue.Full:
        with _pending_lock:
            _pending[:] = [j for j in _pending if j["id"] != job["id"]]
        print("[tool_gm] 队列已满，丢弃本轮叙事")


def _worker() -> None:
    while True:
        job = _jobs.get()
        try:
            entry = _execute(job["text"], job["mode"], job["game_time"])
            _append_log(entry)
            _notify(entry)
        except Exception as e:
            print(f"[tool_gm] 执行失败：{type(e).__name__}: {e}")
        finally:
            with _pending_lock:
                _pending[:] = [j for j in _pending if j["id"] != job["id"]]
            _jobs.task_done()


def pending_text() -> str:
    """尚未落地的叙事（含在跑与在排队），供叙事GM 注入。"""
    with _pending_lock:
        items = list(_pending)
    return "\n".join(f"[{j.get('game_time') or '——'}] 后台正在落地：{j['text'][:40]}…" for j in items)


def pending_count() -> int:
    with _pending_lock:
        return len(_pending)


def clear(wait: bool = True) -> None:
    """放弃本轮 / 回滚前调用：**作废排队任务、等在跑的那个结束、清空待落地**。

    与 `world_worker.clear` 同理：不清的话，回滚后后台 worker 还会把旧叙事落地。
    """
    while True:
        try:
            job = _jobs.get_nowait()
        except queue.Empty:
            break
        else:
            _jobs.task_done()
            with _pending_lock:
                _pending[:] = [j for j in _pending if j["id"] != job["id"]]
    with _pending_lock:
        _pending.clear()
    if wait:
        _jobs.join()


# ------------------------------------------------------------
# 执行
# ------------------------------------------------------------
def _state_text() -> str:
    keys = ("金钱", "背包", "状态", "属性", "基本信息")
    snap = {}
    for k in keys:
        v = state.load(k, None)
        if v is not None:
            snap[k] = v
    return json.dumps(snap, ensure_ascii=False)[:4000]


def _luna_client():
    import openai
    from tools.核心 import two_gm
    cfg = (two_gm.config().get("工具GM") or {})
    cli = openai.OpenAI(api_key=cfg.get("api_key") or "none",
                        base_url=cfg.get("base_url"), timeout=float(cfg.get("timeout") or 120),
                        max_retries=0)
    return cli, cfg


def _call_once(messages, use_fallback: bool):
    """调一次工具GM。use_fallback=True 时走 DeepSeek（llm.py 的配置）。"""
    if use_fallback:
        import llm
        cfg = llm.config()
        return llm._client(cfg).chat.completions.create(
            model=cfg["model"], messages=messages, tools=TOOL_GM_TOOLS).choices[0].message
    cli, cfg = _luna_client()
    extra = {}
    if cfg.get("reasoning_effort"):
        extra["reasoning_effort"] = cfg["reasoning_effort"]
    return cli.chat.completions.create(
        model=cfg.get("model") or "gpt-6-luna", messages=messages,
        tools=TOOL_GM_TOOLS, **extra).choices[0].message


def _call_llm(messages):
    """luna 重试 N 次；仍失败 → 回退 DeepSeek。返回 (message, 用了谁)。"""
    from tools.核心 import two_gm
    retries = max(1, int(two_gm.config().get("重试") or 3))
    last = None
    for _ in range(retries):
        try:
            return _call_once(messages, False), "luna"
        except Exception as e:
            last = e
    try:
        return _call_once(messages, True), "deepseek(回退)"
    except Exception as e:
        raise RuntimeError(f"工具GM 全失败：luna={last} / deepseek={e}")


def _run_tool(name: str, args: dict):
    if name not in TOOL_GM_TOOL_NAMES:
        return {"success": False, "error": f"工具不在白名单：{name}"}
    fn = TOOLS_MAP.get(name)
    if fn is None:
        return {"success": False, "error": f"没有此工具：{name}"}
    try:
        return fn(**args)
    except Exception as e:
        return {"success": False, "error": f"{type(e).__name__}: {e}"}


def _is_ok(r) -> bool:
    """工具结果是否成功：dict 看 success!=False；字符串等非 dict 一律当成功。"""
    if isinstance(r, dict):
        return r.get("success") is not False
    return True


def _execute(narration: str, mode: str, game_time: str) -> dict:
    user = (f"当前状态：\n{_state_text()}\n\n本轮叙事：\n{narration[:2500]}")
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
    calls: list[dict] = []
    for _ in range(6):                      # 工具回环上限
        msg, who = _call_llm(messages)
        tcs = getattr(msg, "tool_calls", None) or []
        if not tcs:
            break
        messages.append({"role": "assistant", "content": msg.content,
                         "tool_calls": [t.model_dump() for t in tcs]})
        for tc in tcs:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except (json.JSONDecodeError, TypeError):
                args = {}
            res = _run_tool(tc.function.name, args)
            calls.append({"tool": tc.function.name, "args": args, "result": res})
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": json.dumps(res, ensure_ascii=False)[:1500]})
    ok = sum(1 for c in calls if _is_ok(c["result"]))
    status = "已完成" if calls and ok == len(calls) else ("部分失败" if calls else "无操作")
    return {
        "ts": _now(), "game_time": game_time, "mode": mode,
        "叙事": narration[:200], "calls": calls, "status": status,
        "摘要": "；".join(f"{c['tool']}" for c in calls) or "（无需变更）",
    }


# ------------------------------------------------------------
# 日志 / 通知
# ------------------------------------------------------------
def _append_log(entry: dict) -> None:
    with _log_lock:
        _RECENT.append(entry)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _notify(entry: dict) -> None:
    # 无操作的轮次不打扰前端（日志面板也不显示）
    if not (entry.get("calls") or []):
        return
    try:
        from tools.核心.ui_events import push, ui_event
        push(ui_event("toollog", 状态=entry.get("status"), 条数=len(entry.get("calls") or [])))
    except Exception:
        pass


def recent(n: int = 20) -> list[dict]:
    """最近 n 条**有实际工具调用**的工具日志（无操作的条目不显示）。冷启动从磁盘读尾巴。"""
    entries: list[dict] = []
    try:
        lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    if lines:
        for ln in lines[-max(n * 6, 120):]:
            ln = ln.strip()
            if not ln:
                continue
            try:
                entries.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
    else:
        with _log_lock:
            entries = list(_RECENT)
    entries = [e for e in entries if (e.get("calls") or [])]   # 无操作的不显示
    return entries[-n:]


def recent_text(n: int = 6) -> str:
    """给叙事GM 注入用的紧凑文本（意图 + 结果）。"""
    out = []
    for e in recent(n):
        nar = (e.get("叙事") or "")[:40]
        res = "；".join(f"{c['tool']}({'成功' if _is_ok(c.get('result')) else '失败'})"
                        for c in (e.get("calls") or []))
        out.append(f"[{e.get('game_time') or e.get('ts')}] 叙事「{nar}…」→ {res or '无需变更'}")
    return "\n".join(out)
