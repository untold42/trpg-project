# -*- coding: utf-8 -*-
"""
factions.py
===========
玩家可见的势力条目（画廊用）。

数据源：`trpg-world/势力介绍.json`（**玩家可见**，已剔除剧透）。
GM 正典在 `trpg-world/江湖势力/*.md`（含剧透），**不经此接口暴露**。

链路原则：前端要的游戏数据一律向后端请求，后端从 `trpg-world` 对应文件返回。
"""

import json
from pathlib import Path

# tools/ -> trpg-server/ -> trpg-project/
_ROOT = Path(__file__).resolve().parent.parent.parent.parent
FACTIONS_FILE = _ROOT / "trpg-world" / "势力介绍.json"


def list_factions() -> list:
    """读 `trpg-world/势力介绍.json`，返回 [{name, desc, detail}]。"""
    try:
        data = json.loads(FACTIONS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        desc = str(item.get("desc") or "")
        out.append({
            "name": str(item["name"]),
            "desc": desc,
            "detail": str(item.get("detail") or desc),
        })
    return out
