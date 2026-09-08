import json
from collections import Counter

with open("map_ancient_center.json", "r", encoding="utf-8") as f:
    data = json.load(f)

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