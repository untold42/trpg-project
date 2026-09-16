# -*- coding: utf-8 -*-
"""
南宋建筑地图图标生成器 · 入口
=============================

    用法（在本目录执行）
    ------------------------------------------------------------------
    python gen_map_icons.py                      # 生成默认建筑（qinglou）到 mapicons/
    python gen_map_icons.py ward                 # 生成指定建筑
    python gen_map_icons.py ward --preview --small 40    # ASCII 校验（40px 实际显示尺寸）
    python gen_map_icons.py ward --preview --scan 58,88  # 逐像素扫描线，核对横向排版
    python gen_map_icons.py ward --stats         # 客观指标（亮度/纯度/亮暗占比）
    python gen_map_icons.py ward --sheet         # 出多尺寸预览图给用户看
    python gen_map_icons.py ward --backup --sheet        # 覆盖前自动备份（带时间戳）

    画新建筑：编辑 buildings.py，加一个 render_xxx() 并登记到 BUILDINGS。
    工具箱与坑位说明见 kit.py 抬头注释；完整技法见 README.md。
"""
import sys

from buildings import BUILDINGS
from kit import cli

if __name__ == "__main__":
    cli(BUILDINGS, default="qinglou", argv=sys.argv[1:])
