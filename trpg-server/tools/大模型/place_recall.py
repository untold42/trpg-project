# -*- coding: utf-8 -*-
"""
place_recall.py
===============
地点「回忆」：点地图上的 POI → 回忆此地（**只查 RAG**）。

来源：`gm_memory`（客观长期记忆，chroma 语义检索，取 Top-N）。
**不返回**建筑信息 / 本局见闻（那是 `query_place` 的事）。
降级：chroma / embedding 不可用 → 空结果（前端显示“毫无印象”）。
"""

GM = "gm_memory"


def recall_place(place: str, n: int = 2) -> dict:
    """回忆某地点：只返回 `gm_memory` 语义检索 Top-`n`（**不返回建筑信息 / 见闻**）。"""
    place = (place or "").strip()
    out = {"place": place, "memories": []}
    if not place:
        return out

    try:
        from tools.大模型.DB import DB_query_tool
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
