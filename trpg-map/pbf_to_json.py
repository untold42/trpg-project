# -*- coding: utf-8 -*-
"""
pbf_to_json.py —— 把 OSM 的 .pbf 文件转成与 map_ancient_center.json 同构的 JSON。

输出结构（对齐 draw_tiles/map_ancient_center.json）：
    {
      "name": "...",
      "version": 2,
      "source": "OpenStreetMap",
      "coordinate_system": "WGS84",
      "objects": [
        {
          "id": <int|null>,
          "name": <str|null>,
          "category": <str>,
          "geometry": {"type": "Point|LineString|MultiPolygon", "coordinates": ...},
          "tags": {...}
        },
        ...
      ],
      "filter": {"type": "circle", "center": {"longitude":..., "latitude":...}, "radius_km":...}
    }

几何规则（与目标文件一致）：
  - 带"面状"标签的闭合 way  -> MultiPolygon，id=null（目标文件里这类多边形 id 为 null）
  - 其余 way（开线或闭合但无面状标签） -> LineString，id=way id
  - multipolygon 关系 -> MultiPolygon，id=关系 id
  - 带标签的 node -> Point，id=node id

分类规则：见 classify()。想调整归类只需改里面的映射表。

依赖：pip install osmium   （纯 pyosmium 绑定，已装在本机）
用法：
    python pbf_to_json.py 扬州.pbf -o map_out.json             # 精选模式（默认）
    python pbf_to_json.py 扬州.pbf -o map_out.json --radius 30 # 额外圆形裁剪 30km
    python pbf_to_json.py 扬州.pbf -o map_out.json --full       # 保留 PBF 全部要素
    python pbf_to_json.py input.pbf -o out.json --center-lon 119.4175 --center-lat 32.41 --radius 30
"""

import argparse
import json
import math
import os
import shutil
import sys
import tempfile

import osmium

try:
    from shapely.geometry import Polygon as _ShapelyPolygon
    from shapely.geometry import LineString as _ShapelyLine
    from shapely.ops import unary_union as _unary_union, linemerge as _linemerge
    _HAS_SHAPELY = True
except Exception:  # shapely 不可用时只做不带合并的降级
    _HAS_SHAPELY = False

# ---------------------------------------------------------------
# 输出 JSON 里保留哪些 OSM tag（对齐目标文件的 whitelist）
# ---------------------------------------------------------------
KEEP_TAG_KEYS = {
    "highway", "natural", "building", "bridge", "boundary", "amenity",
    "surface", "leisure", "water", "railway", "man_made", "waterway",
    "landuse", "sport", "shop", "place", "height", "tourism", "tunnel",
    "historic", "office", "military",
}

# 面状分类对应的 tag 组合（闭合 way 有这些 tag 之一 => 当作多边形）
POLYGON_KEYS = {
    "building",
    "landuse",
    "leisure",
    "amenity",
    "tourism",
    "shop",
    "historic",
    "boundary",
    "natural",   # natural=water -> water，其它 natural -> natural
    "place",     # place 面 -> area
    "man_made",  # man_made=pier 等面状 -> area
    "highway",   # highway=pedestrian 等面状 -> area
    "railway",   # railway=platform 等面状 -> area
    "water",     # 兜底：water=*
}

# ---------------------------------------------------------------
# “精选模式”（默认开启）下按值过滤，对齐 map_ancient_center.json
# 若想保留 PBF 里的全部要素，用 --full 关闭这些过滤。
# ---------------------------------------------------------------
CURATED_FILTERS = {
    # 道路：只保留主要道路类型（去掉 service/footway/path/cycleway/track 等）
    "highway": {
        "primary", "secondary", "tertiary", "unclassified", "residential",
        "living_street", "corridor", "bridleway",
        # 面状 highway（pedestrian 广场、services 服务区等）
        "pedestrian", "services", "raceway", "bus_stop",
    },
    # 建筑：只保留常见/有意义的建筑类型
    "building": {
        "yes", "apartments", "house", "residential", "dormitory", "detached",
        "industrial", "university", "school", "office", "government", "temple",
        "college", "commercial", "service", "roof", "transportation", "hospital",
        "grandstand", "warehouse", "retail", "train_station", "hut",
    },
    # 水系线
    "waterway": {
        "canal", "river", "ditch", "drain", "stream", "dock", "dam", "weir",
    },
    # 自然面（不含 natural=water，water 单独归 water 类）
    "natural": {
        "water", "wood", "scrub", "wetland", "tree_row", "bare_rock", "tree", "peak",
    },
    # 休闲
    "leisure": {
        "pitch", "park", "common", "garden", "stadium", "sports_centre",
        "swimming_pool", "track", "horse_riding", "nature_reserve",
        "fitness_station", "marina", "golf_course",
    },
    # 用地
    "landuse": {
        "forest", "grass", "plant_nursery", "farmyard", "recreation_ground",
        "flowerbed", "cemetery", "basin", "farmland", "reservoir", "observatory",
        "government", "military", "governmental", "harbour", "meadow", "winter_sports",
    },
    # 铁路线（station 在点上另处理）
    "railway": {
        "rail", "construction", "abandoned", "station", "proposed", "disused",
    },
}


# 哪些 tag key 值得作为“点”输出（其余 tag 的点丢弃）
POINT_WORTHY_KEYS = {
    "amenity", "shop", "tourism", "historic", "man_made",
    "natural", "railway", "place",
}


def passes_curated_filter(tags, use_curated):
    """按 CURATED_FILTERS 判断该对象是否保留。"""
    if not use_curated:
        return True
    for key, allowed in CURATED_FILTERS.items():
        val = tags.get(key)
        if val is not None and val not in allowed:
            return False
    return True


def _haversine_km(lon1, lat1, lon2, lat2):
    """两经纬度点之间的大圆距离（公里）。"""
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class CircleFilter:
    """圆形区域过滤（默认不裁剪，只写进 filter 元数据；传 --radius > 0 时启用）。"""

    def __init__(self, lon, lat, radius_km):
        self.lon = lon
        self.lat = lat
        self.radius = radius_km

    def point_inside(self, lon, lat):
        return _haversine_km(self.lon, self.lat, lon, lat) <= self.radius

    def any_point_inside(self, coords_iter):
        return any(self.point_inside(lon, lat) for lon, lat in coords_iter)


def tags_to_dict(tag_list):
    """osmium TagList -> 普通 dict（只保留 whitelist 内的 key）。

    注意：osmium 读出的中文本来就是正确的 UTF-8，不要再做编码“修复”。
    早期版本曾误加 `encode('utf-8').decode('gb18030')`，会把“岳阳楼区”
    之类的正确地名改成乱码，已移除。
    """
    out = {}
    for t in tag_list:
        if t.k in KEEP_TAG_KEYS:
            out[t.k] = t.v
    return out


def extract_name(tag_list):
    """取 OSM 名称：name > name:zh > name:en，都没有返回 None。"""
    for key in ("name", "name:zh", "name:en"):
        try:
            val = tag_list[key]
            if val:
                return val
        except KeyError:
            pass
    return None


# ---------------------------------------------------------------
# 分类
# ---------------------------------------------------------------
def classify(tags, geometry_type):
    """根据 tags 与几何类型返回 category 字符串。

    geometry_type: "Point" / "LineString" / "MultiPolygon"
    """
    # 面
    if geometry_type == "MultiPolygon":
        if tags.get("building"):
            return "building"
        if tags.get("natural") == "water" or tags.get("water"):
            return "water"
        if tags.get("natural"):
            return "natural"
        if tags.get("landuse"):
            return "landuse"
        if tags.get("leisure"):
            return "leisure"
        if tags.get("amenity"):
            return "poi_area"
        if tags.get("tourism"):
            return "tourism"
        if tags.get("shop"):
            return "area"
        if tags.get("historic"):
            return "historic"
        if tags.get("boundary"):
            return "boundary"
        if tags.get("place"):
            return "area"
        if tags.get("man_made"):
            return "area"
        if tags.get("highway"):
            return "area"
        if tags.get("railway"):
            return "area"
        return "area"

    # 线
    if geometry_type == "LineString":
        if tags.get("highway"):
            return "road"
        if tags.get("railway"):
            return "railway"
        if tags.get("waterway"):
            return "waterway"
        if tags.get("boundary"):
            return "line"
        if tags.get("natural"):
            return "line"
        if tags.get("leisure"):
            return "line"
        if tags.get("man_made"):
            return "man_made"
        return "line"

    # 点
    if tags.get("place"):
        return "place"
    if tags.get("amenity"):
        return "poi"
    if tags.get("shop"):
        return "shop"
    if tags.get("tourism"):
        return "tourism"
    if tags.get("historic"):
        return "historic"
    if tags.get("man_made"):
        return "man_made"
    if tags.get("railway"):
        return "railway"
    if tags.get("natural"):
        return "point"
    return "poi"


def is_area_worthy(tags):
    """闭合 way 是否算“面状”要素（决定 emit 成 MultiPolygon 还是 LineString）。"""
    if not tags:
        return False
    for k in POLYGON_KEYS:
        if k in tags:
            return True
    return False


# ---------------------------------------------------------------
# 几何构建
# ---------------------------------------------------------------
def area_to_multipolygon(area):
    """osmium Area -> GeoJSON MultiPolygon coordinates。"""
    polygons = []
    for outer in area.outer_rings():
        poly = []
        # 外环
        ring = _ring_coords(outer)
        poly.append(ring)
        # 内环（洞）
        for inner in area.inner_rings(outer):
            poly.append(_ring_coords(inner))
        polygons.append(poly)
    return polygons


def _ring_coords(ring):
    """NodeRefList -> [[lon, lat], ...]，确保闭合（首尾相同）。"""
    coords = [[ref.lon, ref.lat] for ref in ring]
    if len(coords) >= 2 and coords[0] != coords[-1]:
        coords.append(coords[0][:])
    return coords


def _to_multipolygon(g):
    """shapely 几何 -> GeoJSON MultiPolygon coordinates（用于降级合并）。"""
    if g is None or g.is_empty:
        return []
    if g.geom_type == "Polygon":
        return [[[[round(x, 7), round(y, 7)] for x, y in g.exterior.coords]]
                + [[[round(x, 7), round(y, 7)] for x, y in r.coords] for r in g.interiors]]
    if g.geom_type == "MultiPolygon":
        out = []
        for p in g.geoms:
            out.append([[[round(x, 7), round(y, 7)] for x, y in p.exterior.coords]]
                       + [[[round(x, 7), round(y, 7)] for x, y in r.coords] for r in p.interiors])
        return out
    if g.geom_type == "GeometryCollection":
        out = []
        for sub in g.geoms:
            out.extend(_to_multipolygon(sub))
        return out
    return []


# ---------------------------------------------------------------
# 主转换器
# ---------------------------------------------------------------
class PbfToJson:
    def __init__(self, center_lon, center_lat, radius_km, name="扬州地图", use_curated=True):
        self.name = name
        self.filter = CircleFilter(center_lon, center_lat, radius_km)
        self.use_curated = use_curated
        self.objects = []

    # ---- 读取 osmium 数据 ----
    def _read_file(self, pbf_path):
        """返回 osmium 可读的文件路径。

        osmium 的 C 扩展在 Windows 下不能正确处理非 ASCII 路径，
        因此对含非 ASCII 字符的文件名，先复制到一个临时 ASCII 文件名。
        """
        abspath = os.path.abspath(pbf_path)
        # 路径含非 ASCII 字符 -> 复制到临时 ASCII 文件
        try:
            abspath.encode("ascii")
        except UnicodeEncodeError:
            tmp_dir = tempfile.mkdtemp(prefix="pbf2json_")
            tmp_path = os.path.join(tmp_dir, "input.pbf")
            shutil.copy(pbf_path, tmp_path)
            return tmp_path
        return abspath

    def convert(self, pbf_path):
        src = self._read_file(pbf_path)

        # 第一遍：收集 multipolygon/boundary 关系的成员 way 与元数据
        rel_members, rel_meta, parent_rels = self._collect_relations(src)

        # 第二遍：真正转换（locations=True 才能拿到成员 way 的坐标）
        handler = _ConvertHandler(self, rel_members, rel_meta, parent_rels)
        handler.apply_file(src, locations=True)
        # 汇总“拼装失败”的关系：退回输出其可用成员几何，避免整块丢失
        handler.finalize()

        # 排序：非空 id 按 id 升序，null id 的放在最后
        self.objects.sort(key=lambda o: (o["id"] is None, o["id"] if o["id"] is not None else 0))
        return self

    def _collect_relations(self, src):
        """收集 multipolygon/boundary 关系：成员 way、元数据、way->父关系。"""
        rel_members = {}
        rel_meta = {}
        parent_rels = {}

        class _Collector(osmium.SimpleHandler):
            def __init__(self):
                super().__init__()

            def relation(self, r):
                typ = r.tags.get("type")
                if typ not in ("multipolygon", "boundary"):
                    return
                ways = [m.ref for m in r.members if m.type == "w"]
                if not ways:
                    return
                rel_members[r.id] = ways
                rel_meta[r.id] = {
                    "tags": tags_to_dict(r.tags),
                    "name": extract_name(r.tags),
                }
                for w in ways:
                    parent_rels.setdefault(w, []).append(r.id)

        c = _Collector()
        c.apply_file(src)
        return rel_members, rel_meta, parent_rels

    # ---- 输出 ----
    def to_dict(self):
        return {
            "name": self.name,
            "version": 2,
            "source": "OpenStreetMap",
            "coordinate_system": "WGS84",
            "objects": self.objects,
            "filter": {
                "type": "circle",
                "center": {
                    "longitude": self.filter.lon,
                    "latitude": self.filter.lat,
                },
                "radius_km": self.filter.radius,
            },
        }

    def save(self, out_path):
        data = self.to_dict()
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return data


class _ConvertHandler(osmium.SimpleHandler):
    """第二遍：node -> Point，way -> LineString，area -> MultiPolygon。"""

    def __init__(self, converter, rel_members, rel_meta, parent_rels):
        super().__init__()
        self.conv = converter
        self.rel_members = rel_members      # rel_id -> [way_id]
        self.rel_meta = rel_meta            # rel_id -> {tags, name}
        self.parent_rels = parent_rels      # way_id -> [rel_id]
        self.member_geoms = {}              # way_id -> {coords, closed}
        self.assembled = set()              # 成功拼装的关系 id

    def _keep(self, tags):
        return passes_curated_filter(tags, self.conv.use_curated)

    def _area_vertices(self, area):
        """遍历 area 所有顶点坐标。"""
        for outer in area.outer_rings():
            for ref in outer:
                yield ref.lon, ref.lat
            for inner in area.inner_rings(outer):
                for ref in inner:
                    yield ref.lon, ref.lat

    def node(self, n):
        if len(n.tags) == 0:
            return
        tags = tags_to_dict(n.tags)
        # 点只保留 POINT_WORTHY_KEYS 里的 tag（与目标文件一致：poi/shop/place 等）
        if not any(k in tags for k in POINT_WORTHY_KEYS):
            return
        if not self._keep(tags):
            return
        if self.conv.filter.radius > 0 and not self.conv.filter.point_inside(n.lon, n.lat):
            return
        obj = {
            "id": n.id,
            "name": extract_name(n.tags),
            "category": classify(tags, "Point"),
            "geometry": {"type": "Point", "coordinates": [n.lon, n.lat]},
            "tags": tags,
        }
        self.conv.objects.append(obj)

    def way(self, w):
        # 关系成员 way：先收集几何（开线），等关系拼装结果出来再定
        if w.id in self.parent_rels:
            if not w.is_closed():
                coords = [[ref.lon, ref.lat] for ref in w.nodes]
                self.member_geoms[w.id] = {"coords": coords, "closed": False}
            return

        # 闭合 way 交给 area 回调处理（面或线都在那里出），这里只处理开线
        if w.is_closed():
            return

        tags = tags_to_dict(w.tags)
        if not self._keep(tags):
            return

        # 过滤
        if self.conv.filter.radius > 0:
            if not self.conv.filter.any_point_inside((ref.lon, ref.lat) for ref in w.nodes):
                return

        coords = [[ref.lon, ref.lat] for ref in w.nodes]
        self.conv.objects.append({
            "id": w.id,
            "name": extract_name(w.tags),
            "category": classify(tags, "LineString"),
            "geometry": {"type": "LineString", "coordinates": coords},
            "tags": tags,
        })

    def area(self, a):
        oid = a.orig_id()

        # 关系成员（闭合 way）：先收集几何，不直接输出
        if a.from_way() and oid in self.parent_rels:
            ring = next(a.outer_rings(), None)
            if ring is not None:
                self.member_geoms[oid] = {"coords": _ring_coords(ring), "closed": True}
            return

        tags = tags_to_dict(a.tags)
        if not self._keep(tags):
            return

        if self.conv.filter.radius > 0:
            if not self.conv.filter.any_point_inside(self._area_vertices(a)):
                return

        if a.from_way():
            # 闭合 way
            if not is_area_worthy(tags):
                # 无面状标签的闭合 way 按线输出（例如只有 source 标签的湖岸线）
                ring = next(a.outer_rings(), None)
                if ring is None:
                    return
                coords = _ring_coords(ring)
                self.conv.objects.append({
                    "id": oid,
                    "name": extract_name(a.tags),
                    "category": classify(tags, "LineString"),
                    "geometry": {"type": "LineString", "coordinates": coords},
                    "tags": tags,
                })
                return

            # 面状闭合 way -> 多边形，id=null（与目标文件一致）
            self.conv.objects.append({
                "id": None,
                "name": extract_name(a.tags),
                "category": classify(tags, "MultiPolygon"),
                "geometry": {"type": "MultiPolygon", "coordinates": area_to_multipolygon(a)},
                "tags": tags,
            })
        else:
            # multipolygon 关系 -> 多边形，id=关系 id
            self.assembled.add(oid)
            self.conv.objects.append({
                "id": oid,
                "name": extract_name(a.tags),
                "category": classify(tags, "MultiPolygon"),
                "geometry": {"type": "MultiPolygon", "coordinates": area_to_multipolygon(a)},
                "tags": tags,
            })

    def finalize(self):
        """处理拼装失败的关系：用现存成员几何回退输出，避免整块丢失。

        源数据若是不完整裁剪（如岳阳.pbf 缺洞庭湖 231 条边界 way 中的 134 条），
        area manager 拼不出闭合环，关系面就不会产生；这里把能用的成员几何
        （闭合部分合并成面、开线合并成线）退回去，至少让湖岸/边界可见。
        """
        for rid, wids in self.rel_members.items():
            if rid in self.assembled:
                continue
            meta = self.rel_meta.get(rid, {})
            tags = meta.get("tags") or {}
            name = meta.get("name")

            closed = []
            open_lines = []
            for wid in wids:
                g = self.member_geoms.get(wid)
                if not g:
                    continue
                if g["closed"] and len(g["coords"]) >= 4:
                    closed.append(g["coords"])
                elif not g["closed"] and len(g["coords"]) >= 2:
                    open_lines.append(g["coords"])

            # 闭合成员 -> 合并成多边形
            if closed and _HAS_SHAPELY:
                polys = []
                for c in closed:
                    try:
                        p = _ShapelyPolygon(c)
                        if p.is_valid and not p.is_empty and p.area > 0:
                            polys.append(p)
                    except Exception:
                        pass
                if polys:
                    merged = _unary_union(polys)
                    mp = _to_multipolygon(merged)
                    if mp:
                        self.conv.objects.append({
                            "id": rid,
                            "name": name,
                            "category": classify(tags, "MultiPolygon"),
                            "geometry": {"type": "MultiPolygon", "coordinates": mp},
                            "tags": tags,
                        })

            # 开线成员 -> 合并成水岸/边界线
            segs = []
            if open_lines and _HAS_SHAPELY:
                try:
                    merged = _linemerge(_unary_union([_ShapelyLine(c) for c in open_lines]))
                    if merged.geom_type == "MultiLineString":
                        segs = [list(line.coords) for line in merged.geoms]
                    elif merged.geom_type == "LineString":
                        segs = [list(merged.coords)]
                except Exception:
                    segs = open_lines
            else:
                segs = open_lines

            line_cat = "waterway" if (tags.get("natural") == "water" or tags.get("water")) \
                else classify(tags, "LineString")
            for coords in segs:
                if len(coords) < 2:
                    continue
                self.conv.objects.append({
                    "id": None,
                    "name": None,
                    "category": line_cat,
                    "geometry": {"type": "LineString",
                                 "coordinates": [[x, y] for x, y in coords]},
                    "tags": tags,
                })


def main():
    parser = argparse.ArgumentParser(
        description="把 OSM PBF 转成 map_ancient_center.json 同构的 JSON"
    )
    parser.add_argument("input", help="输入的 .pbf 文件路径")
    parser.add_argument("-o", "--output", default="map_from_pbf.json", help="输出的 .json 文件路径")
    parser.add_argument("--name", default="扬州地图", help="输出 JSON 的 name 字段")
    parser.add_argument("--center-lon", type=float, default=119.4175, help="filter 圆心经度（默认 119.4175）")
    parser.add_argument("--center-lat", type=float, default=32.41, help="filter 圆心纬度（默认 32.41）")
    parser.add_argument("--radius", type=float, default=0.0,
                        help="圆形裁剪半径（公里），0 表示不裁剪只写元数据（默认 0）")
    parser.add_argument("--full", action="store_true",
                        help="关闭精选过滤，保留 PBF 里的全部要素")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"错误：找不到输入文件 {args.input}", file=sys.stderr)
        sys.exit(1)

    conv = PbfToJson(
        center_lon=args.center_lon,
        center_lat=args.center_lat,
        radius_km=args.radius,
        name=args.name,
        use_curated=not args.full,
    )
    conv.convert(args.input)
    data = conv.save(args.output)

    print("=" * 48)
    print("PBF -> JSON 转换完成")
    print("=" * 48)
    print("输入：", args.input)
    print("输出：", args.output)
    print("对象数量：", len(data["objects"]))
    print("filter：", json.dumps(data["filter"], ensure_ascii=False))


if __name__ == "__main__":
    main()
