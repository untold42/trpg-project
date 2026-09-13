# -*- coding: utf-8 -*-
"""
init_GM_DB.py
=============
初始化 chroma 记忆库的**结构**：创建两个空 collection，**不写入任何内容**。

    gm_memory   —— 主持人：客观事实（世界到底发生了什么）
    char_memory —— 角色：主观记忆（记忆/感情/认知），带 owner

数据库路径 = 本文件同目录下的 `chroma_db/`（即 trpg-db/chroma_db），
与 `trpg-server/tools/mem_store.py` 的默认路径一致。

用法：
    python init_GM_DB.py            # 建结构（已存在则跳过）
    python init_GM_DB.py --reset    # 先删掉旧库再重建（会清空所有记忆！）

注意：
    - 本脚本不涉及 embedding，因此**不需要 LM Studio**。
    - **运行前请关闭任何打开 chroma_db 的程序**（如 DB Browser for SQLite）。
      chromadb 启动 Rust 内核时要拿写锁，被占住会静默卡死、无任何输出。
"""

import os
import shutil
import sys

import chromadb

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "chroma_db")
COLLECTIONS = ("gm_memory", "char_memory")


def main():
    if "--reset" in sys.argv:
        if os.path.exists(DB_PATH):
            shutil.rmtree(DB_PATH)
            print("已删除旧库：", DB_PATH)
        else:
            print("旧库不存在，直接新建")

    client = chromadb.PersistentClient(path=DB_PATH)
    print("初始化结构：", DB_PATH)
    for name in COLLECTIONS:
        col = client.get_or_create_collection(name)
        print(f"  {name}: 就绪（{col.count()} 条）")
    print("完成。")


if __name__ == "__main__":
    main()
