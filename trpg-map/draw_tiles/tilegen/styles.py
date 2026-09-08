from config import (
    FARMLAND_COLOR,
    FOREST_COLOR,
    GRASS_COLOR,
    CEMETERY_COLOR,

    PRIMARY_COLOR,
    SECONDARY_COLOR,
    TERTIARY_COLOR,
    RESIDENTIAL_COLOR,
    OTHER_ROAD_COLOR,

    BUILDING_COLOR,
    BUILDING_OUTLINE,

    HISTORIC_BUILDING_COLOR,
    HISTORIC_BUILDING_OUTLINE,

    TEMPLE_COLOR,
    TEMPLE_OUTLINE
)


def get_landuse_color(tags):

    landuse = tags.get("landuse")

    if landuse == "farmland":
        return FARMLAND_COLOR

    if landuse in ("forest", "wood"):
        return FOREST_COLOR

    if landuse in (
        "grass",
        "meadow",
        "recreation_ground",
        "village_green"
    ):
        return GRASS_COLOR

    if landuse == "cemetery":
        return CEMETERY_COLOR

    return None


def should_draw_building(tags, zoom):

    if zoom <= 10:
        return False

    if zoom == 11:

        important_values = (
            "school",
            "university",
            "college",
            "temple",
            "place_of_worship",
            "monument",
            "museum",
            "government"
        )

        values = (
            tags.get("historic"),
            tags.get("amenity"),
            tags.get("building")
        )

        return any(
            value in important_values
            for value in values
            if value
        )

    if zoom == 12:

        if tags.get("historic"):
            return True

        if tags.get("amenity") in (
            "school",
            "university",
            "college",
            "place_of_worship",
            "hospital",
            "government"
        ):
            return True

        return tags.get("building") in (
            "temple",
            "church",
            "civic",
            "government",
            "school",
            "university"
        )

    return True


def get_road_style(tags, zoom):

    highway = tags.get("highway")

    if highway == "primary":

        if zoom >= 14:
            return PRIMARY_COLOR, 4

        if zoom >= 12:
            return PRIMARY_COLOR, 3

        return PRIMARY_COLOR, 2


    if highway == "secondary":

        if zoom >= 14:
            return SECONDARY_COLOR, 3

        if zoom >= 12:
            return SECONDARY_COLOR, 2

        return SECONDARY_COLOR, 1


    if highway == "tertiary":

        if zoom >= 14:
            return TERTIARY_COLOR, 2

        return TERTIARY_COLOR, 1


    if highway in (
        "residential",
        "living_street"
    ):

        if zoom < 13:
            return None

        return RESIDENTIAL_COLOR, 1


    if highway in (
        "unclassified",
        "road"
    ):

        if zoom < 14:
            return None

        return OTHER_ROAD_COLOR, 1


    if highway == "service":
        return None

    return None