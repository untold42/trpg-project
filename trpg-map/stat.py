import json
import os
import sys
from collections import Counter

# 默认统计 trpg-map/数据/ 下的数据（可命令行覆盖）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_FILE = os.path.join(BASE_DIR, "数据", "扬州_OSM精简.json")

path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FILE

with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

print("统计文件：", os.path.abspath(path))

objects = data["objects"]


# =========================
# 按 category 统计 tags
# =========================

categories = [
    "building",
    "road",
    "point",
    "water",
    "transport",
    "landuse",
    "line",
]

for target_category in categories:

    counter = Counter()

    for obj in objects:

        if obj.get("category") != target_category:
            continue

        tags = obj.get("tags", {})

        for key, value in tags.items():
            counter[(key, value)] += 1

    print("\n")
    print("=" * 60)
    print(f"CATEGORY: {target_category}")
    print("=" * 60)

    for (key, value), count in counter.most_common(30):

        print(
            f"{key:20} "
            f"{str(value):30} "
            f"{count}"
        )
