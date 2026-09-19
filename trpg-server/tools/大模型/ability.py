# -*- coding: utf-8 -*-
"""get_ability：读取玩家属性（统一走 state_manager，不依赖启动目录）。"""

import json

from tools.核心.state_manager import state


def get_ability():
    return json.dumps(state.load("属性", {}), ensure_ascii=False)
