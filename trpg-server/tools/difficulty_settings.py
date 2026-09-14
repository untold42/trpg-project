# -*- coding: utf-8 -*-
"""
difficulty_settings.py
======================
游戏**难度**设置（只管难度），存 `游戏数据/难度设置.json`。

因为它在 `游戏数据/` 下，会被 `engine.snapshot_state()` 的「状态现拼」自动纳入
**每次 LLM 调用**——主持人据此调整叙事与判定。

**难度的含义（描述）也存在 `难度设置.json` 里**，是数据、不是规则：`难度说明` 字段列各级含义，
可手工编辑扩充；LLM 每轮从状态块读到「当前难度 + 各级含义」。
难度只影响「世界如何回应」，**不改硬事实**（距离 / 时间 / 骰值仍由代码算）。
"""

import os

from tools.state_manager import state

#: 首次创建 难度设置.json 时的种子（之后以文件为准，可手工编辑）
DEFAULT_DIFFICULTY = "普通"
DEFAULT_DESCRIPTIONS = {
    "轻松": "对玩家宽容：事件偏有利、敌手偏弱、伤势轻、死亡可避免、花销与收获宽松、NPC 更愿帮忙。",
    "普通": "基准，不加不减。",
    "困难": "事件偏不利、敌手偏强、伤势更重、资源更紧、失败有实际代价、NPC 更计较。",
    "硬核": "无怜悯：重伤可致命、失败留长期后果、敌手用尽全力、不因「主角」而放水。",
}


def _load() -> dict:
    """读难度设置并补齐缺失字段（难度说明是数据源，支持手工编辑扩充）。"""
    data = state.load("难度设置", {})
    if not isinstance(data, dict):
        data = {}
    if not isinstance(data.get("难度说明"), dict) or not data["难度说明"]:
        data["难度说明"] = dict(DEFAULT_DESCRIPTIONS)
    if data.get("难度") not in data["难度说明"]:
        data["难度"] = (DEFAULT_DIFFICULTY if DEFAULT_DIFFICULTY in data["难度说明"]
                        else next(iter(data["难度说明"])))
    return data


def _ensure():
    """确保 难度设置.json 存在（否则「状态现拼」里不会出现，LLM 看不到难度）。"""
    if not os.path.isfile(os.path.join(state.data_dir, "难度设置.json")):
        state.save("难度设置", _load())


def get_settings() -> dict:
    _ensure()
    data = _load()
    state.save("难度设置", data)  # 回写补齐（保证状态块里含「难度说明」）
    return {"难度": data["难度"], "可选难度": list(data["难度说明"].keys())}


def set_difficulty(难度: str) -> dict:
    """设置难度（写 游戏数据/难度设置.json；描述保留在文件里）。"""
    难度 = (难度 or "").strip()
    data = _load()
    if 难度 not in data["难度说明"]:
        return {"success": False,
                "error": f"未知难度「{难度}」；可选：{'、'.join(data['难度说明'])}"}
    data["难度"] = 难度
    state.save("难度设置", data)
    return {"success": True, "难度": 难度, "可选难度": list(data["难度说明"].keys())}
