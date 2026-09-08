def check_DB_length() -> int:
    from main import memory

    return memory.count()


def DB_query_tool(time=None, data_type=None, content="", n=2):
    from main import memory, model

    memory_embedding = model.encode([content]).tolist()

    if time and data_type:
        results = memory.query(
            query_embeddings=memory_embedding,
            n_results=n,
            where={"time": time, "type": data_type},
        )
    elif time:
        results = memory.query(
            query_embeddings=memory_embedding, n_results=n, where={"time": time}
        )
    elif data_type:
        results = memory.query(
            query_embeddings=memory_embedding, n_results=n, where={"type": data_type}
        )
    else:
        results = memory.query(
            query_embeddings=memory_embedding, n_results=n
        )

    return results["documents"][0]

def DB_query_tool_in_saving(time, content) -> str:
    from main import memory, model

    cat = f"{time},{content}"
    memory_embedding = model.encode([cat]).tolist()

    results = memory.query(query_embeddings=memory_embedding, n_results=4)

    return str({"documents": results["documents"][0], "ids": results["ids"][0]})


def DB_add_and_update_tool(operation, id, time, data_type, content) -> str:
    from main import memory, model

    cat = f"{time},{content}"
    memory_embedding = model.encode([cat]).tolist()

    if operation == "add":
        memory.add(
            documents=[cat],
            embeddings=memory_embedding,
            metadatas=[{"type": data_type, "time": time}],
            ids=[id],
        )
        return f"成功添加{id}至数据库"

    elif operation == "update":
        memory.update(
            documents=[cat],
            embeddings=memory_embedding,
            metadatas=[{"type": data_type, "time": time}],
            ids=[id],
        )
        return f"成功更新{id}的信息"

    else:
        return "操作失败，请返回正确的操作类型！"
