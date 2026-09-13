# -*- coding: utf-8 -*-
"""
mem_store.py
============
chroma 长期记忆的访问层（懒加载）。

两个 collection（对应两种记忆，见 ARCHITECTURE.md 第三节）：

    gm_memory   —— 主持人：客观事实（世界发生了什么）。全局检索，只增。
    char_memory —— 角色：主观记忆（记忆/感情/认知）。**必须带 owner**，按 owner 检索。

设计要点：
    - 懒加载：导入本模块不产生副作用；首次真正读写时才连 chroma、加载 embedding 模型。
    - 唯一入口：DB.py 的工具经这里读写，工具不再 `from main import memory`。
    - embedding 统一用 LM Studio 的 `lms.embedding_model`（与 init_GM_DB.py 一致）。
"""

import os
import threading

_HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get(
    "TRPG_CHROMA_PATH",
    os.path.abspath(os.path.join(_HERE, "..", "..", "trpg-db", "chroma_db")),
)
EMBED_MODEL = "Qwen/Qwen3-Embedding-0.6B"

# collection 名（chroma 只接受 ASCII，故用英文名；语义见 docstring）
GM = "gm_memory"
CHAR = "char_memory"
VALID = (GM, CHAR)

_lock = threading.RLock()
_client = None
_model = None
_collections = {}


def _ensure():
    """惰性初始化 chroma 客户端与 embedding 模型。"""
    global _client, _model
    with _lock:
        if _client is None:
            import chromadb
            _client = chromadb.PersistentClient(path=DB_PATH)
        if _model is None:
            import lmstudio as lms
            _model = lms.embedding_model(EMBED_MODEL)
    return _client, _model


def get_collection(name: str):
    """取（必要时创建）指定 collection。name 只能是 gm_memory / char_memory。"""
    if name not in VALID:
        raise ValueError(f"未知 collection：{name}（只能是 {GM} 或 {CHAR}）")
    with _lock:
        if name not in _collections:
            client, _ = _ensure()
            _collections[name] = client.get_or_create_collection(name)
        return _collections[name]


def embed(texts):
    """texts: list[str] -> list[list[float]]"""
    _, model = _ensure()
    vectors = model.embed(texts)
    return [list(v) for v in vectors]
