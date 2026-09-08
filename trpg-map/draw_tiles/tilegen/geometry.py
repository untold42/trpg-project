def get_points_from_geometry(geometry):

    if not geometry:
        return []

    geometry_type = geometry.get("type")

    coordinates = geometry.get("coordinates")

    if not coordinates:
        return []

    points = []

    if geometry_type == "Point":

        points.append(coordinates)

    elif geometry_type == "LineString":

        points.extend(coordinates)

    elif geometry_type == "Polygon":

        for ring in coordinates:
            points.extend(ring)

    elif geometry_type == "MultiLineString":

        for line in coordinates:
            points.extend(line)

    elif geometry_type == "MultiPolygon":

        for polygon in coordinates:

            for ring in polygon:
                points.extend(ring)

    return points


def prepare_object(obj, zoom, lonlat_to_pixel):

    geometry = obj.get("geometry")

    if not geometry:
        return None

    geometry_type = geometry.get("type")

    coordinates = geometry.get("coordinates")

    if not coordinates:
        return None

    if geometry_type == "Point":

        lon, lat = coordinates

        x, y = lonlat_to_pixel(lon, lat, zoom)

        return {"obj": obj, "type": "Point", "coordinates": [(x, y)]}

    if geometry_type == "LineString":

        pixels = [lonlat_to_pixel(lon, lat, zoom) for lon, lat in coordinates]

        return {"obj": obj, "type": "LineString", "coordinates": pixels}

    if geometry_type == "MultiLineString":

        all_lines = []

        for line in coordinates:

            pixels = [lonlat_to_pixel(lon, lat, zoom) for lon, lat in line]

            all_lines.append(pixels)

        return {"obj": obj, "type": "MultiLineString", "coordinates": all_lines}

    if geometry_type == "Polygon":

        all_rings = []

        for ring in coordinates:

            pixels = [lonlat_to_pixel(lon, lat, zoom) for lon, lat in ring]

            all_rings.append(pixels)

        return {"obj": obj, "type": "Polygon", "coordinates": all_rings}

    if geometry_type == "MultiPolygon":

        all_polygons = []

        for polygon in coordinates:

            polygon_rings = []

            for ring in polygon:

                pixels = [lonlat_to_pixel(lon, lat, zoom) for lon, lat in ring]

                polygon_rings.append(pixels)

            all_polygons.append(polygon_rings)

        return {"obj": obj, "type": "MultiPolygon", "coordinates": all_polygons}

    return None


def get_pixel_bbox(prepared):

    coordinates = prepared["coordinates"]

    points = []

    def collect(value):

        if (
            isinstance(value, tuple)
            and len(value) == 2
            and all(isinstance(v, (int, float)) for v in value)
        ):
            points.append(value)
            return

        if isinstance(value, list) or isinstance(value, tuple):

            for item in value:
                collect(item)

    collect(coordinates)

    if not points:
        return None

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]

    return (min(xs), min(ys), max(xs), max(ys))
