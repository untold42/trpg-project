import json
import random


INPUT_FILE = "map_clean.json"
OUTPUT_FILE = "map_ancient.json"


# 固定随机种子
# 保证每次运行结果一致
random.seed(1221)


# =========================================================
# 道路
# =========================================================

ROAD_KEEP_RATE = {
    "primary": 1.00,
    "secondary": 1.00,
    "tertiary": 0.60,
    "unclassified": 0.30,
    "residential": 0.15,
    "living_street": 0.15,
}


REMOVE_ROAD = {
    "primary_link",
    "secondary_link",
    "tertiary_link",
    "service",
    "track",
    "footway",
    "cycleway",
    "path",
    "pedestrian",
    "steps",
    "motorway",
    "motorway_link",
    "trunk",
    "trunk_link",
}


# =========================================================
# 建筑
# =========================================================

BUILDING_KEEP_RATE = {
    "yes": 0.25,

    "apartments": 0.10,

    "house": 0.30,
    "detached": 0.30,
    "residential": 0.30,

    "industrial": 0.05,

    "warehouse": 0.05,
    "commercial": 0.10,
    "retail": 0.10,

    "farm_auxiliary": 1.00,

    "school": 1.00,
    "university": 1.00,
}


REMOVE_BUILDING = {
    "storage_tank",
    "cooling_tower",
}


# =========================================================
# Landuse
# =========================================================

KEEP_LANDUSE = {
    "farmland",
    "forest",
    "meadow",
    "grass",
    "cemetery",
    "farmyard",
    "aquaculture",
    "recreation_ground",
    "village_green",
}


REMOVE_LANDUSE = {
    "residential",
    "industrial",
    "retail",
    "commercial",
    "construction",
    "greenfield",
    "railway",
    "garages",
    "brownfield",
    "quarry",
}


# =========================================================
# 读取
# =========================================================

with open(INPUT_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)


objects = data["objects"]

new_objects = []

removed = 0


# =========================================================
# 开始处理
# =========================================================

for obj in objects:

    category = obj.get("category")
    tags = obj.get("tags", {})


    # -----------------------------------------------------
    # 1. transport
    # -----------------------------------------------------

    if category == "transport":
        removed += 1
        continue


    # -----------------------------------------------------
    # 2. road
    # -----------------------------------------------------

    if category == "road":

        highway = tags.get("highway")

        # 明确删除
        if highway in REMOVE_ROAD:
            removed += 1
            continue

        # 按比例保留
        if highway in ROAD_KEEP_RATE:

            rate = ROAD_KEEP_RATE[highway]

            if random.random() > rate:
                removed += 1
                continue

        new_objects.append(obj)
        continue


    # -----------------------------------------------------
    # 3. building
    # -----------------------------------------------------

    if category == "building":

        building = tags.get("building")


        # 明确删除
        if building in REMOVE_BUILDING:
            removed += 1
            continue


        # 历史建筑：无条件保留
        if "historic" in tags:
            new_objects.append(obj)
            continue


        # 宗教建筑：保留
        if tags.get("amenity") == "place_of_worship":
            new_objects.append(obj)
            continue


        # 建筑类型
        if building in BUILDING_KEEP_RATE:

            rate = BUILDING_KEEP_RATE[building]

            if random.random() > rate:
                removed += 1
                continue


        # 其他建筑暂时保留
        new_objects.append(obj)
        continue


    # -----------------------------------------------------
    # 4. landuse
    # -----------------------------------------------------

    if category == "landuse":

        landuse = tags.get("landuse")


        # 现代土地利用删除
        if landuse in REMOVE_LANDUSE:
            removed += 1
            continue


        # 自然/农业土地保留
        if landuse in KEEP_LANDUSE:
            new_objects.append(obj)
            continue


        # 其他暂时保留
        new_objects.append(obj)
        continue


    # -----------------------------------------------------
    # 5. point
    # -----------------------------------------------------

    if category == "point":

        # 保留少数有自然/历史意义的点
        if (
            "natural" in tags
            or "historic" in tags
            or tags.get("waterway") == "lock_gate"
        ):
            new_objects.append(obj)
            continue

        # 其他 point 大多是现代设施
        removed += 1
        continue


    # -----------------------------------------------------
    # 6. 其他类别
    # -----------------------------------------------------

    new_objects.append(obj)


# =========================================================
# 保存
# =========================================================

data["objects"] = new_objects


with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(
        data,
        f,
        ensure_ascii=False,
        indent=2
    )


# =========================================================
# 输出统计
# =========================================================

print("========================================")
print("古代化地图裁剪完成")
print("========================================")

print("原始对象数量：", len(objects))
print("删除对象数量：", removed)
print("剩余对象数量：", len(new_objects))

print()
print("输出文件：", OUTPUT_FILE)