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
"""

import os
import queue
import threading

from tools import world_sim, world_state

MAX_TICKS = 10  # 单次最多补演多少天（更早的直接跳过）
# 总开关：TRPG_WORLD_SIM=0 可关掉世界推演（测试/无小模型时）
ENABLED = os.environ.get("TRPG_WORLD_SIM", "1") != "0"

_q: "queue.Queue[dict | None]" = queue.Queue()
_lock = threading.Lock()
_thread = None
_enqueued_to = ""  # 已入队到的日期（内存）；"" 表示尚未初始化


def _loop():
    while True:
        task = _q.get()
        try:
            if task is None:
                return
            world_sim.run_day(task["date"], task.get("player_location"))
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


def on_turn_end():
    """引擎每轮结束调用：检测跨天并入队日推演任务。"""
    global _enqueued_to
    if not ENABLED:
        return
    try:
        _ensure_thread()
        now = world_state.current_date()
        if not now:
            return
        if not _enqueued_to:
            # 首次：以当前推演游标为准；若空则以今天为起点（不回补历史）
            _enqueued_to = world_state.cursor() or now

        delta = world_state.days_between(_enqueued_to, now)
        if delta <= 0:
            return

        start = _enqueued_to
        if delta > MAX_TICKS:
            # 跳过早先的日子，只补最近 MAX_TICKS 天
            start = world_state.day_before(now, MAX_TICKS)
            world_sim.fast_forward(start)
            delta = MAX_TICKS

        loc = world_state.current_location()
        d = start
        for _ in range(delta):
            d = world_state.day_after(d)
            _q.put({"date": d, "player_location": loc})
        _enqueued_to = now
    except Exception as e:
        print(f"[world_worker] on_turn_end 出错：{e}")


def clear():
    """清空队列并重置入队游标（存档 / 放弃本轮后调用）。"""
    global _enqueued_to
    with _lock:
        while True:
            try:
                _q.get_nowait()
                _q.task_done()
            except queue.Empty:
                break
        _enqueued_to = world_state.cursor()


def pending() -> int:
    return _q.qsize()
