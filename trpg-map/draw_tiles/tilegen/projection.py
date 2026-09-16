import math

from config import TILE_SIZE


def lonlat_to_pixel(lon, lat, zoom):

    lat = max(
        min(lat, 85.05112878),
        -85.05112878
    )

    world_size = TILE_SIZE * (2 ** zoom)

    x = (
        (lon + 180.0)
        / 360.0
        * world_size
    )

    lat_rad = math.radians(lat)

    y = (
        1
        - math.asinh(
            math.tan(lat_rad)
        ) / math.pi
    ) / 2 * world_size

    return x, y


def lonlat_to_tile(lon, lat, zoom):

    x, y = lonlat_to_pixel(
        lon,
        lat,
        zoom
    )

    return (
        int(x // TILE_SIZE),
        int(y // TILE_SIZE)
    )


def meters_per_pixel(zoom, lat=None):

    """某 zoom / 纬度下，1 像素代表多少米（Web Mercator）。"""

    from config import REF_LAT

    if lat is None:
        lat = REF_LAT

    return (
        40075016.686
        * math.cos(math.radians(lat))
        / (TILE_SIZE * (2 ** zoom))
    )


def meters_to_px(meters, zoom, lat=None, scale=1.0,
                 minimum=None, maximum=None):

    """把真实米数换算成像素宽度（带上下限）。"""

    from config import MIN_LINE_PX, MAX_LINE_PX

    if minimum is None:
        minimum = MIN_LINE_PX

    if maximum is None:
        maximum = MAX_LINE_PX

    px = meters * scale / meters_per_pixel(zoom, lat)

    return int(max(minimum, min(maximum, round(px))))


def get_tiles_for_bbox(bbox, zoom):

    min_lon, min_lat, max_lon, max_lat = bbox

    x1, y1 = lonlat_to_tile(
        min_lon,
        max_lat,
        zoom
    )

    x2, y2 = lonlat_to_tile(
        max_lon,
        min_lat,
        zoom
    )

    return (
        min(x1, x2),
        max(x1, x2),
        min(y1, y2),
        max(y1, y2)
    )


def get_bbox_for_circle(center_lon, center_lat, radius_km):

    """
    根据圆心和半径（公里）计算经纬度包围盒。

    纬度方向：1 度约 111.32 公里。
    经度方向：111.32 * cos(lat) 公里。
    """

    dlat = radius_km / 111.32

    dlon = radius_km / (
        111.32 * math.cos(
            math.radians(center_lat)
        )
    )

    return (
        center_lon - dlon,
        center_lat - dlat,
        center_lon + dlon,
        center_lat + dlat
    )


def haversine_km(lon1, lat1, lon2, lat2):

    """
    两点间的球面距离（公里）。
    """

    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)

    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1_r)
        * math.cos(lat2_r)
        * math.sin(dlon / 2) ** 2
    )

    return 2 * 6371.0 * math.asin(
        math.sqrt(a)
    )


def bbox_km_size(bbox):

    """
    返回 bbox 的中心，以及在该中心纬度下的
    近似宽、高（公里）。
    """

    min_lon, min_lat, max_lon, max_lat = bbox

    center_lon = (min_lon + max_lon) / 2
    center_lat = (min_lat + max_lat) / 2

    width_km = haversine_km(
        min_lon, center_lat,
        max_lon, center_lat
    )

    height_km = haversine_km(
        center_lon, min_lat,
        center_lon, max_lat
    )

    return center_lon, center_lat, width_km, height_km


def expand_bbox_to_aspect(bbox, aspect_w, aspect_h, margin):

    """
    把 bbox 以中心为基准外扩成 aspect_w:aspect_h 的比例，
    再按 margin 比例往四周加留白。返回新 bbox。
    """

    center_lon, center_lat, width_km, height_km = bbox_km_size(bbox)

    if width_km / height_km < aspect_w / aspect_h:
        width_km = height_km * aspect_w / aspect_h
    else:
        height_km = width_km * aspect_h / aspect_w

    scale = 1 + 2 * margin
    width_km *= scale
    height_km *= scale

    dlon = width_km / 2 / (
        111.32 * math.cos(
            math.radians(center_lat)
        )
    )

    dlat = height_km / 2 / 111.32

    return (
        center_lon - dlon,
        center_lat - dlat,
        center_lon + dlon,
        center_lat + dlat
    )