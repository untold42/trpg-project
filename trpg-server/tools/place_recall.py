# -*- coding: utf-8 -*-
"""
place_recall.py
===============
地点「回忆」：点地图上的 POI → 回忆此地。

两级来源（都是**只读**，不写任何记忆）：
    1. `place_notes`（本局见闻，SQLite，按地名精确取）
    2. `gm_memory`（客观长期记忆，chroma 语义检索，取 Top-N）

降级：chroma / embedding 不可用 → 只返回 place_notes；两者都空 → 空结果（前端显示"毫无印象"）。
"""

from tools import map_query

GM = "gm_memory"


def recall_place(place: str, n: int = 2) -> dict:
    """回忆某地点，返回 {place, notes, memories}。

    - `notes`：本局见闻（place_notes），可能有 time。
    - `memories`：gm_memory 语义检索 Top-`n`，带 time（若有）。
    """
    place = (place or "").strip()
    out = {"place": place, "notes": [], "memories": []}
    if not place:
        return out

    try:
        out["notes"] = map_query.notes_for(place)
    except Exception:
        pass

    try:
        from tools.DB import DB_query_tool
        r = DB_query_tool(place, collection=GM, n=n)
        if r.get("success"):
            docs = r.get("documents") or []
            metas = r.get("metadatas") or []
            for i, d in enumerate(docs):
                meta = metas[i] if i < len(metas) else {}
                out["memories"].append({
                    "content": str(d),
                    "time": str((meta or {}).get("time") or ""),
                })
    except Exception:
        pass

    return out
