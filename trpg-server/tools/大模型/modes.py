# -*- coding: utf-8 -*-
"""
modes.py
========
游戏模式切换（探索 / 叙事 / 战斗）。

三态与进出规则（见 README.md 第五节）：
    - **探索**：整屏大地图，光标代表玩家，可自由走动；
    - **叙事**：对话 + 立绘 + 时钟；玩家**不能**自行移动；
    - **战斗**：战棋界面。

切换：
    探索 ──玩家输入（主持人/行动/说话/继续）──► 叙事（附带坐标，见 main./action）
    叙事 ──主持人判定──► 探索（本模块的工具 `resume_exploration`）
    叙事 ──start_battle──► 战斗 ──结束──► 叙事

即：**进入叙事由玩家发动，退出叙事由主持人裁决** —— 玩家不能自行在地图上乱走，
除非先向主持人说明「我要走了」。
"""

from tools.核心.ui_events import UI_EVENTS_KEY, mode_event


def resume_exploration():
    """LLM 工具：玩家离开当前场景、回到大地图自由行动。"""
    return {
        "success": True,
        "message": "玩家已回到探索模式（大地图，可自由走动）。"
                   "本轮请勿替玩家叙述他去了哪里——由玩家自行在地图上走动后再输入行动。",
        UI_EVENTS_KEY: [mode_event("explore")],
    }
