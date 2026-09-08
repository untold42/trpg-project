# -*- coding: utf-8 -*-
"""
state_manager.py
================
统一的游戏状态读写层。

所有工具不再各自 open 游戏数据 JSON，统一通过这里的 state 单例读写：
    - 路径集中管理（tools/游戏数据/{name}.json，绝对路径，与启动目录无关）
    - 读文件容错（文件损坏/不存在时返回默认值，不崩）
    - 原子写（先写临时文件再 rename，写到一半崩溃也不会损坏 JSON）
    - 读写加锁（将来并发也安全）

用法：
    from tools.state_manager import state

    data = state.load("基本信息", {})      # 读
    state.save("基本信息", data)           # 写
    state.update("金钱", lambda d: {...})  # 读-改-写一体
"""

import json
import os
import threading


class StateManager:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        self._lock = threading.RLock()

    def _path(self, name):
        return os.path.join(self.data_dir, f"{name}.json")

    def load(self, name, default=None):
        """读 游戏数据/{name}.json。文件不存在/损坏时返回 default。"""
        try:
            with open(self._path(name), "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return default

    def save(self, name, data):
        """原子写：先写 .tmp 再 os.replace 替换，避免写一半崩溃损坏 JSON。"""
        path = self._path(name)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    def update(self, name, fn):
        """读-改-写一体：fn(data) 返回新 data。"""
        with self._lock:
            data = self.load(name, {})
            new_data = fn(data)
            self.save(name, new_data)
            return new_data


# 全局单例：tools/游戏数据/ 目录
GAME_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "游戏数据")
state = StateManager(GAME_DATA_DIR)
