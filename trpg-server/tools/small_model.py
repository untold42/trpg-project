# -*- coding: utf-8 -*-
"""
small_model.py
==============
本地小模型（Qwen3-4B）的调用封装。

用途（两条管线，见 README.md §5.6）：
    - ui_event 生成（✅ 已封装 ask_json）
    - 世界推演的离散采样：只出「地点 / 事件类型」两个极简字段

关键经验（实测）：
    - 不逼它"极简"的话，它会把字段写成整段小说，单次 19s+；
    - 用严格 system（"只填地名 2-6 字、禁止叙述/思考"）后，单次降到 0.5-1.1s；
    - `respond(..., response_format=<JSON Schema>)` 保证返回合法 JSON；
    - 结果直接从 `res.parsed` 取 dict。

失败一律返回 None，由调用方降级（世界推演是 off-screen，失败不影响玩）。
"""

import json
import os
import threading

MODEL_KEY = "qwen/qwen3-4b-2507"

#: 单次调用默认上限（秒）：超时则 cancel 生成、返回 None（由调用方降级）
#: 可用环境变量 `TRPG_SMALL_TIMEOUT` 覆盖。
TIMEOUT = float(os.environ.get("TRPG_SMALL_TIMEOUT", "10"))

_lock = threading.RLock()
_model = None


def _get_model():
    """懒加载 LM Studio 里已加载的 Qwen3-4B。"""
    global _model
    with _lock:
        if _model is None:
            import lmstudio as lms
            _model = lms.llm(MODEL_KEY)
        return _model


def available() -> bool:
    try:
        _get_model()
        return True
    except Exception:
        return False


def ask_json(system: str, user: str, schema: dict, max_tokens: int = None,
             timeout: float = None):
    """一次结构化调用（带硬超时）。成功返回 dict；超时/失败返回 None。

    - `max_tokens`：限制生成长度（强烈建议给）。
    - `timeout`：秒；默认 `TIMEOUT=10`。超时会 **cancel 生成**（真中断，不是干等）。
    - **判定 / 分类类系统提示必须在末尾加 `/no_think` 禁止思考**，否则 4B 会陷入长思考
      （实测：不禁思考会生成 8000+ token / 150s+；加 `/no_think` 后降到 0.5–3s）。

    实现：流式 `respond_stream` 放到守护线程里消费，主线程最多等 `timeout` 秒；
    超时就调 `stream.cancel()` 发取消消息。`set_sync_api_timeout` 不管用（它只管消息间隔）。
    """
    timeout = TIMEOUT if timeout is None else float(timeout)
    holder: dict = {}
    done = threading.Event()

    def _run():
        try:
            model = _get_model()
            stream = model.respond_stream(
                {"messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ]},
                response_format=schema,
                config={"maxTokens": max_tokens} if max_tokens else None,
            )
            holder["stream"] = stream
            for _ in stream:      # 消费至完成
                pass
            holder["res"] = stream.result()
        except Exception as e:
            holder["err"] = e
        finally:
            done.set()

    th = threading.Thread(target=_run, daemon=True)
    th.start()
    if not done.wait(timeout):
        st = holder.get("stream")
        try:
            if st is not None:
                st.cancel()       # 真中断生成
        except Exception:
            pass
        return None

    res = holder.get("res")
    if res is None:
        return None
    parsed = getattr(res, "parsed", None)
    if isinstance(parsed, dict):
        return parsed
    try:  # 退回：部分版本 parsed 可能是字符串
        data = json.loads(getattr(res, "content", "") or "")
        return data if isinstance(data, dict) else None
    except Exception:
        return None
