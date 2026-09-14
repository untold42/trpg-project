# -*- coding: utf-8 -*-
"""
battle_settings.py
==================
**战斗专用设置**（与「游戏难度」无关，故**不放进 `difficulty_settings.py`**）。

目前只有一项：`思路判定模型` —— 战斗里判定玩家「思路」修正时用哪个模型
（`小模型` 默认 / `大模型`），由**战斗界面**里随时切换。

存储：`trpg-server/sessions/battle_settings.json`（运行期配置）
——刻意**不放 `游戏数据/`**，因此不会进每轮 LLM 状态块。
"""

import json
from pathlib import Path

_PATH = Path(__file__).resolve().parent.parent / "sessions" / "battle_settings.json"

THOUGHT_MODEL_KEY = "思路判定模型"
THOUGHT_MODEL_OPTIONS = ["小模型", "大模型"]
THOUGHT_MODEL_DEFAULT = "小模型"


def _load() -> dict:
    try:
        data = json.loads(_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, json.JSONDecodeError):
        data = {}
    if data.get(THOUGHT_MODEL_KEY) not in THOUGHT_MODEL_OPTIONS:
        data[THOUGHT_MODEL_KEY] = THOUGHT_MODEL_DEFAULT
    return data


def _save(data: dict):
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    _PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_thought_model() -> str:
    """战斗判「思路」用哪个模型：'小模型'（默认）或 '大模型'。"""
    return _load()[THOUGHT_MODEL_KEY]


def set_thought_model(模型: str) -> dict:
    """切换「思路判定模型」（写 sessions/battle_settings.json）。"""
    模型 = (模型 or "").strip()
    if 模型 not in THOUGHT_MODEL_OPTIONS:
        return {"success": False,
                "error": f"未知模型「{模型}」；可选：{'、'.join(THOUGHT_MODEL_OPTIONS)}"}
    data = _load()
    data[THOUGHT_MODEL_KEY] = 模型
    _save(data)
    return {"success": True, THOUGHT_MODEL_KEY: 模型,
            "可选思路判定模型": list(THOUGHT_MODEL_OPTIONS)}
