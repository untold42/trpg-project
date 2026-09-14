# -*- coding: utf-8 -*-
"""
world_worker.py
===============
世界推演的**异步 worker**（不阻塞玩家）。

流程：
    /action 每轮结束 ──► on_turn_end()
        比对「已入队游标」与当前游戏日期
        跨 N 天 ──► 入队 N 个「日任务」（超过 MAX_TICKS 则跳过早先的）
                              │
                     daemon 线程逐个消费 ──► world_sim.run_day()

要点：
    - **入队游标与推演游标分离**：避免"还没跑完就被重复入队"。
      入队用内存里的 `_enqueued_to`；推演进度由 `世界状态.模拟游标` 记录。
    - 进程重启后队列丢失，`_enqueued_to` 重置为当前推演游标 → 自动补上缺口。
    - `clear()`：存档/放弃时清空（底层状态已变，旧任务失效）。
    - 失败只记日志：世界推演是 off-screen，失败不影响玩。

线程模型（本次完善）：
    - 所有可变全局（`_enqueued_to` / `_generation` / 线程句柄）由 `_lock` 保护；
    - **世代号 `generation`**：`clear()` 时 +1；队列里/在途的旧任务出队时发现世代不符
      即跳过 —— 避免「放弃本轮」已回滚世界状态后，旧推演又把数据写回去；
    - **所有状态写入都只在 daemon 线程发生**：大跨度跳过的 `fast_forward` 也作为任务入队，
      不再在请求线程里改 `世界状态.json`（消除请求线程与 daemon 的写竞争）；
    - **`clear(wait=True)`**：清队后停在途任务结束，供 `abandon` 在**回滚之前**调用 ——
      保证在途写入也被一并回滚。（默认 `clear()` 不等，用于存档等无需回滚的场景。）
"""

import os
import queue
import threading
import time

from tools import world_sim, world_state

MAX_TICKS = 10  # 单次最多补演多少天（更早的直接跳过）
# 总开关：TRPG_WORLD_SIM=0 可关掉世界推演（测试/无小模型时）
ENABLED = os.environ.get("TRPG_WORLD_SIM", "1") != "0"
IDLE_TIMEOUT = 10.0  # clear(wait=True) 最长等待秒数（防在途任务卡死时无限阻塞）

_q: "queue.Queue[dict | None]" = queue.Queue()
_lock = threading.RLock()
_thread = None
_enqueued_to = ""   # 已入队到的日期（内存）；"" 表示尚未初始化
_generation = 0     # 世代号：clear() 递增，旧任务作废


# ------------------------------------------------------------
# daemon 线程
# ------------------------------------------------------------
def _loop():
    while True:
        task = _q.get()
        try:
            if task is None:  # 退出哨兵（当前未使用，保留）
                return
            with _lock:
                stale = task.get("generation") != _generation
            if stale:
                continue  # 该任务已在 clear() 时作废
            kind = task.get("kind", "day")
            if kind == "fast_forward":
                world_sim.fast_forward(task["date"])
            else:
                world_sim.run_day(task["date"], task.get("player_location"),
                                  task.get("player_region"))
        except Exception as e:
            print(f"[world_worker] 推演失败 {task}: {e}")
        finally:
            _q.task_done()


def _ensure_thread():
    global _thread
    with _lock:
        if _thread is None or not _thread.is_alive():
            _thread = threading.Thread(target=_loop, daemon=True, name="world-sim")
            _thread.start()


def _drain():
    """清空尚未开始的任务（逐个 task_done，保持 unfinished_tasks 计数正确）。"""
    while True:
        try:
            _q.get_nowait()
        except queue.Empty:
            return
        _q.task_done()


def _wait_idle(timeout: float = IDLE_TIMEOUT):
    """等在途任务结束（带超时，避免卡死时无限阻塞）。"""
    deadline = time.monotonic() + timeout
    while _q.unfinished_tasks and time.monotonic() < deadline:
        time.sleep(0.05)


# ------------------------------------------------------------
# 对外接口
# ------------------------------------------------------------
def on_turn_end():
    """引擎每轮结束调用：检测跨天并入队日推演任务。"""
    global _enqueued_to
    if not ENABLED:
        return
    try:
        _ensure_thread()
        with _lock:
            now = world_state.current_date()
            if not now:
                return
            if not _enqueued_to:
                # 首次：以当前推演游标为准；若空则以今天为起点（不回补历史）
                _enqueued_to = world_state.cursor() or now

            delta = world_state.days_between(_enqueued_to, now)
            if delta <= 0:
                return

            gen = _generation
            start = _enqueued_to
            if delta > MAX_TICKS:
                # 跳过早先的日子，只补最近 MAX_TICKS 天（fast_forward 也走队列，保序）
                start = world_state.day_before(now, MAX_TICKS)
                _q.put({"kind": "fast_forward", "date": start, "generation": gen})
                delta = MAX_TICKS

            loc = world_state.current_location()
            region = world_state.current_region()
            d = start
            for _ in range(delta):
                d = world_state.day_after(d)
                _q.put({"kind": "day", "date": d,
                        "player_location": loc, "player_region": region,
                        "generation": gen})
            _enqueued_to = now
    except Exception as e:
        print(f"[world_worker] on_turn_end 出错：{e}")


def clear(wait: bool = False):
    """清空队列并作废在途任务。

    - 世代 +1 ⇒ 队列里/在途的旧任务出队时被跳过（不再写状态）。
    - `wait=True` ⇒ 额外等在途任务真正结束。**`abandon` 必须在「回滚快照之前」调用它**，
      否则在途写入会晚于回滚落地，把回滚数据又写回去。
    """
    global _enqueued_to, _generation
    with _lock:
        _generation += 1
        _drain()
        if wait:
            _wait_idle()
        _enqueued_to = world_state.cursor()


def pending() -> int:
    return _q.qsize()


def status() -> dict:
    """调试/巡检：worker 当前状态。"""
    with _lock:
        return {
            "enabled": ENABLED,
            "alive": bool(_thread and _thread.is_alive()),
            "pending": _q.qsize(),
            "enqueued_to": _enqueued_to,
            "generation": _generation,
        }
