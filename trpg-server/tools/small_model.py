# -*- coding: utf-8 -*-
"""
small_model.py
==============
本地小模型（Qwen3-4B）的调用封装。

用途（两条管线，见 ARCHITECTURE.md 第七节）：
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
import threading

MODEL_KEY = "qwen/qwen3-4b-2507"

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


def ask_json(system: str, user: str, schema: dict):
    """一次结构化调用。成功返回 dict；失败返回 None。"""
    try:
        model = _get_model()
        res = model.respond(
            {"messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]},
            response_format=schema,
        )
    except Exception:
        return None

    parsed = getattr(res, "parsed", None)
    if isinstance(parsed, dict):
        return parsed
    try:  # 退回：部分版本 parsed 可能是字符串
        data = json.loads(res.content)
        return data if isinstance(data, dict) else None
    except Exception:
        return None
