"""
figure_out_struction.py —— 打印某个数据 JSON 的结构（顶层字段 / 对象数 / 首个对象）。

用法：
    python figure_out_struction.py [数据文件]
默认查看 trpg-map/数据/扬州_OSM全量.json。
"""

import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_FILE = os.path.join(BASE_DIR, "数据", "扬州_OSM全量.json")

path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FILE

print("读取：", os.path.abspath(path))

with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

print("顶层字段：", data.keys())
print("objects 类型：", type(data["objects"]))
print("objects 数量：", len(data["objects"]))

print("\n第一个 object：")
print(json.dumps(data["objects"][0], ensure_ascii=False, indent=2))
