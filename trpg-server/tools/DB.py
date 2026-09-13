# -*- coding: utf-8 -*-
"""
DB.py
=====
长期记忆（chroma）的四个工具。**按 collection + owner 寻址**。

    gm_memory   —— 主持人：客观事实，全局，只增
    char_memory —— 角色：主观记忆，必须带 owner

检索铁律（ARCHITECTURE.md 第三节）：
    查 char_memory 必须带 owner（当前视角角色）；查 gm_memory 才全局。跨 owner 视为 bug。
"""

from tools.mem_store import CHAR, GM, embed, get_collection


def _where(owner=None, time=None):
    """组装 chroma 的 where 过滤条件。"""
    conds = []
    if owner:
        conds.append({"owner": owner})
    if time:
        conds.append({"time": time})
    if not conds:
        return None
    return conds[0] if len(conds) == 1 else {"$and": conds}


def check_DB_length(collection: str = GM) -> dict:
    """查看某个 collection 的条目数。仅供调试/巡检，**不再作为 LLM 工具**（不再用于编 id）。"""
    try:
        n = get_collection(collection).count()
    except Exception as e:
        return {"success": False, "error": str(e)}
    return {"success": True, "collection": collection, "count": n}


def _next_id(collection: str, prefix: str) -> str:
    """代码分配下一个 id：取现有同前缀 id 的数值后缀最大值 +1。

    用 max+1（而非 count+1）：删过条目后也不会碰撞。
    （碰撞在 chroma 里是**静默丢弃**，会悄悔丢记忆——所以不能用数量推 id。）
    """
    col = get_collection(collection)
    try:
        ids = col.get(include=[])["ids"]
    except Exception:
        ids = col.get()["ids"]
    nums = []
    for i in ids:
        if i.startswith(prefix + "_"):
            suffix = i[len(prefix) + 1:]
            if suffix.isdigit():
                nums.append(int(suffix))
    return f"{prefix}_{max(nums) + 1 if nums else 1}"


def DB_query_tool(content: str, collection: str = GM, owner: str = None,
                  time: str = None, n: int = 2):
    """语义检索记忆。game 进行中查历史用。

    collection=char_memory 时必须给 owner；gm_memory 全局检索。
    """
    if collection == CHAR and not owner:
        return {"success": False, "error": "查角色记忆必须提供 owner（角色名）"}
    try:
        col = get_collection(collection)
        kwargs = {"query_embeddings": embed([content]), "n_results": n}
        where = _where(owner, time)
        if where:
            kwargs["where"] = where
        results = col.query(**kwargs)
    except Exception as e:
        return {"success": False, "error": str(e)}

    return {
        "success": True,
        "collection": collection,
        "documents": (results.get("documents") or [[]])[0],
        "ids": (results.get("ids") or [[]])[0],
        "metadatas": (results.get("metadatas") or [[]])[0],
    }


def DB_add_and_update_tool(operation: str, collection: str, content: str, id: str = None,
                           time: str = None, owner: str = None, kind: str = None) -> dict:
    """新增或更新一条记忆。

    - **add**：**不用给 id**，代码自动编号（max+1）；给传的 id 会被忽略。
    - **update**：必须给 id（来自 DB_query_tool / DB_query_tool_in_saving 返回的旧记忆 id）。
    - collection=char_memory 时必须给 owner。
    """
    if collection == CHAR and not owner:
        return {"success": False, "error": "写角色记忆必须提供 owner（角色名）"}
    if operation not in ("add", "update"):
        return {"success": False, "error": "operation 只能是 add 或 update"}

    # chroma 要求 metadata 非空：time 始终写入（可为空串）
    metadata = {"time": time or ""}
    if owner:
        metadata["owner"] = owner
    if kind:
        metadata["kind"] = kind

    doc = f"{time},{content}" if time else content
    prefix = "gm" if collection == GM else "char"
    try:
        col = get_collection(collection)
        emb = embed([doc])
        if operation == "add":
            new_id = _next_id(collection, prefix)
            col.add(documents=[doc], embeddings=emb, metadatas=[metadata], ids=[new_id])
            return {"success": True, "operation": "add", "id": new_id, "collection": collection}

        # update
        if not id:
            return {"success": False, "error": "update 必须提供 id（旧记忆的 id）"}
        try:
            exists = col.get(ids=[id])["ids"]
        except Exception:
            exists = []
        if not exists:
            return {"success": False, "error": f"要更新的记忆 {id} 不存在；若是新信息请用 add"}
        col.update(documents=[doc], embeddings=emb, metadatas=[metadata], ids=[id])
        return {"success": True, "operation": "update", "id": id, "collection": collection}
    except Exception as e:
        return {"success": False, "error": str(e)}


def DB_query_tool_in_saving(content: str, collection: str = GM, owner: str = None,
                            time: str = None, n: int = 4) -> dict:
    """存档蒸馏用：对一条待写入信息，找最相似的前 n 条旧记忆（判断 add / update）。"""
    if collection == CHAR and not owner:
        return {"success": False, "error": "查角色记忆必须提供 owner（角色名）"}
    try:
        col = get_collection(collection)
        kwargs = {"query_embeddings": embed([f"{time},{content}" if time else content]),
                  "n_results": n}
        where = _where(owner, time)
        if where:
            kwargs["where"] = where
        results = col.query(**kwargs)
    except Exception as e:
        return {"success": False, "error": str(e)}

    return {
        "success": True,
        "collection": collection,
        "ids": (results.get("ids") or [[]])[0],
        "documents": (results.get("documents") or [[]])[0],
    }
