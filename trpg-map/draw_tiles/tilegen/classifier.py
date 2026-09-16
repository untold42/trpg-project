def is_water(tags, category):

    if category == "water":
        return True

    if tags.get("natural") == "water":
        return True

    if tags.get("water") in (
        "river",
        "canal",
        "pond",
        "lake",
        "basin",
        "reservoir"
    ):
        return True

    return False


def is_waterway(tags, category):

    if category == "waterway":
        return True

    if tags.get("waterway"):
        return True

    return False


def is_building(tags, category):

    if category == "building":
        return True

    if tags.get("building"):
        return True

    return False


def classify_object(prepared):

    obj = prepared["obj"]

    tags = obj.get("tags", {})

    category = obj.get("category", "")

    geometry_type = prepared["type"]


    landuse = tags.get("landuse")

    if landuse in (
        "farmland",
        "forest",
        "wood",
        "grass",
        "meadow",
        "recreation_ground",
        "village_green",
        "cemetery"
    ):
        return "land"


    if is_water(tags, category):
        return "water"


    if is_waterway(tags, category):
        return "waterway"


    # natural=wood / scrub / wetland / bare_rock 等也是“土地”，
    # 必须放在 is_water 之后（否则会把 natural=water 也吃进来）。
    if tags.get("natural") in (
        "wood",
        "scrub",
        "wetland",
        "bare_rock",
        "grassland",
        "heath",
    ):
        return "land"


    if tags.get("man_made") == "city_wall":
        return "wall"


    if category == "road":
        return "road"


    # 民居矩形不画在瓦片上（避免密集），但数据保留在 JSON/DB 里
    if obj.get("ancient_kind") == "民居":
        return "other"


    if is_building(tags, category):
        return "building"


    if geometry_type == "Point":
        return "point"


    return "other"