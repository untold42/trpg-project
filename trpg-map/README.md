# pbf_to_json.py —— OSM PBF 转 JSON 工具

把 OpenStreetMap 的 `.pbf` 二进制文件，转成与
[`../数据/扬州_OSM精简.json`](../数据/扬州_OSM精简.json) **同构**的 JSON。

> 一句话：`数据/源pbf/扬州.pbf`（原始 OSM 数据） → `数据/扬州_OSM全量.json`（和现有 pipeline 兼容的结构化数据）。

---

## 1. 为什么要这个工具

`trpg-map` 的数据流是这样的：

```
数据/源pbf/扬州.pbf (原始 OSM)
   │
   ▼   【本工具：pbf_to_json.py】
数据/扬州_OSM全量.json   ← 与 数据/扬州_OSM精简.json 同构
   │
   ▼   古代化/世界生成见 draw_tiles/build_world.py（一键：../生成.py）
古代化裁剪、南宋转译、瓦片、空间库…
```

仓库里现有的脚本（`stat.py`、`draw_tiles/*`）**都只读 JSON**，没有任何代码解析 PBF。
本工具补上了最前面这一步：把 PBF 转成下游能直接消费的 JSON。

---

## 2. 环境要求

- Python 3.8+（本项目实测 Python 3.14）
- `osmium`（纯 pyosmium 绑定，带 C 扩展）

```bash
python -m pip install osmium
```

> 注意：装的是 `osmium`，不是 `pyosmium`。两者 API 不同，本脚本基于 `osmium` 4.x 的
> `SimpleHandler` / `Area` 接口。

可选（本脚本不强制）：

```bash
python -m pip install shapely   # 仅当你打算自己扩展几何处理时
```

---

## 3. 快速开始

```bash
cd C:/Users/20866/Desktop/trpg-project/trpg-map

# 默认：精选模式
python pbf_to_json.py 数据/源pbf/扬州.pbf -o 数据/扬州_OSM全量.json

# 按圆形裁剪 30km（对齐 数据/扬州_OSM精简.json 的 filter 元数据）
python pbf_to_json.py 数据/源pbf/扬州.pbf -o 数据/扬州_OSM全量.json --radius 30

# 保留 PBF 全部要素（不做值过滤）
python pbf_to_json.py 数据/源pbf/扬州.pbf -o 数据/扬州_OSM全量.json --full
```

---

## 4. 命令行参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `input` | —（必填） | 输入的 `.pbf` 文件路径 |
| `-o, --output` | `数据/扬州_OSM全量.json` | 输出 JSON 路径 |
| `--name` | `扬州地图` | 输出 JSON 的 `name` 字段 |
| `--center-lon` | `119.4175` | `filter` 圆心经度 |
| `--center-lat` | `32.41` | `filter` 圆心纬度 |
| `--radius` | `0.0` | 圆形裁剪半径（公里）。`0` = 不裁剪，只把圆写进 `filter` 元数据 |
| `--full` | 关闭 | 关闭精选过滤，保留 PBF 里的全部要素 |

---

## 5. 输出格式

输出结构与 `数据/扬州_OSM精简.json` 完全一致：

```jsonc
{
  "name": "扬州地图",
  "version": 2,
  "source": "OpenStreetMap",
  "coordinate_system": "WGS84",
  "objects": [
    {
      "id": 244080766,              // int 或 null
      "name": "江都区",             // string 或 null
      "category": "place",          // 见第 6 节分类规则
      "geometry": {
        "type": "Point",            // Point | LineString | MultiPolygon
        "coordinates": [119.5647288, 32.4374578]
      },
      "tags": { "place": "city" }   // 只保留白名单内的 tag
    }
  ],
  "filter": {
    "type": "circle",
    "center": { "longitude": 119.4175, "latitude": 32.41 },
    "radius_km": 30.0
  }
}
```

### 几何规则（与目标文件一致）

| OSM 要素 | 输出 geometry | 输出 id |
|----------|---------------|---------|
| 带面状标签的闭合 way（建筑、水面、绿地…） | `MultiPolygon` | `null` |
| 其他 way（开线，或闭合但无面状标签） | `LineString` | way id |
| multipolygon 关系 | `MultiPolygon`（含洞） | 关系 id |
| 带标签的 node | `Point` | node id |

### 标签白名单

输出 `tags` 只保留以下 key，其余（`source`、`created_by`、`addr:*`、`name*` 等）全部丢弃：

```
highway, natural, building, bridge, boundary, amenity, surface,
leisure, water, railway, man_made, waterway, landuse, sport,
shop, place, height, tourism, tunnel, historic, office, military
```

`name` 字段单独取 OSM 的 `name` > `name:zh` > `name:en`。

---

## 6. 分类规则

`category` 由 `classify(tags, geometry_type)` 决定，逻辑集中在脚本顶部，改起来方便。

### 面（MultiPolygon）

| 判断顺序 | 条件 | category |
|----------|------|----------|
| 1 | `building` 存在 | `building` |
| 2 | `natural=water` 或 `water` 存在 | `water` |
| 3 | `natural` 存在（wood/scrub/wetland…） | `natural` |
| 4 | `landuse` 存在 | `landuse` |
| 5 | `leisure` 存在 | `leisure` |
| 6 | `amenity` 存在 | `poi_area` |
| 7 | `tourism` 存在 | `tourism` |
| 8 | `shop` 存在 | `area` |
| 9 | `historic` 存在 | `historic` |
| 10 | `boundary` 存在 | `boundary` |
| 11 | `place` 存在 | `area` |
| 12 | `man_made` 存在 | `area` |
| 13 | `highway` 存在 | `area` |
| 14 | `railway` 存在 | `area` |
| 兜底 | 其他 | `area` |

### 线（LineString）

| 判断顺序 | 条件 | category |
|----------|------|----------|
| 1 | `highway` 存在 | `road` |
| 2 | `railway` 存在 | `railway` |
| 3 | `waterway` 存在 | `waterway` |
| 4 | `boundary` 存在 | `line` |
| 5 | `natural` 存在 | `line` |
| 6 | `leisure` 存在 | `line` |
| 7 | `man_made` 存在 | `man_made` |
| 兜底 | 其他 | `line` |

### 点（Point）

| 判断顺序 | 条件 | category |
|----------|------|----------|
| 1 | `place` 存在 | `place` |
| 2 | `amenity` 存在 | `poi` |
| 3 | `shop` 存在 | `shop` |
| 4 | `tourism` 存在 | `tourism` |
| 5 | `historic` 存在 | `historic` |
| 6 | `man_made` 存在 | `man_made` |
| 7 | `railway` 存在 | `railway` |
| 8 | `natural` 存在 | `point` |
| 兜底 | 其他 | `poi` |

> 点只输出包含以下 key 之一的 node：`amenity / shop / tourism / historic / man_made / natural / railway / place`。
> 其余 tag 的点（如 `highway=bus_stop`、纯 `office`）会被丢弃——这与目标文件的 poi/shop/place 口径一致。

---

## 7. 精选过滤（默认开启）

`CURATED_FILTERS` 表按 tag 值做白名单过滤，对齐 `数据/扬州_OSM精简.json` 的口径。例如：

- **道路**只保留 `primary / secondary / tertiary / residential / unclassified / living_street / corridor / bridleway` 等，去掉 `service / footway / path / cycleway / track / motorway` 等。
- **建筑**只保留 `yes / apartments / house / residential / dormitory / …`，去掉 `storage_tank / barn / cabin` 等。
- **自然面**保留 `water / wood / scrub / wetland / tree_row / bare_rock / tree / peak`。
- **水系线**保留 `canal / river / ditch / drain / stream / dock / dam / weir`。

用 `--full` 可关闭这套过滤，保留 PBF 里的全部要素。

---

## 8. 圆形裁剪（`--radius`）

- `--radius 0`（默认）：**不裁剪**，只把圆信息写进输出 JSON 的 `filter` 字段。
- `--radius 30`：只保留「至少有一个顶点落在圆内」的要素。

> 判断口径是「要素是否与圆相交」的近似：点看是否在圆内，线/面看是否**有任一顶点**在圆内。
> 极少数「跨过圆但顶点都在圆外」的要素可能被漏掉，属于已知简化。

---

## 9. 实现细节与坑

### 9.1 中文文件名

`osmium` 的 C 扩展在 Windows 上打不开非 ASCII 路径（`数据/源pbf/扬州.pbf` 会报 `Open failed`）。
脚本检测到非 ASCII 文件名时，会自动复制到临时 ASCII 文件再读，读完不留垃圾。

### 9.2 中文编码（重要）

`osmium` 读出来的中文字符串**本来就是正确的 UTF-8**，脚本不做任何编码转换。

> ⚠️ 曾经踩过的坑：在 Windows 终端里 `print` 中文时，终端用 GBK 解码 UTF-8，
> 看到的是“乱码”，但那只是**终端显示问题**，数据是对的。早期版本据此误加了一个
> `s.encode('utf-8').decode('gb18030')` 的“修复”，结果反而把“岳阳楼区”这类正确地名
> 改成乱码（含私用区字符 U+E000–U+F8FF）。该函数已移除，请勿再加回来。

**验证数据对不对，不要看终端，要看码点**：

```python
import json
d = json.load(open("数据/扬州_OSM全量.json", encoding="utf-8"))
bad = [o["name"] for o in d["objects"]
       if o.get("name") and any(ord(c) == 0xFFFD or 0xE000 <= ord(c) <= 0xF8FF
                                 for c in o["name"])]
print("坏名字数量:", len(bad))   # 应为 0
```

想在本机终端正常看到中文，先切到 UTF-8：

```powershell
chcp 65001
```

### 9.3 multipolygon 处理

用 `osmium` 的 area manager 自动拼装外环/内环（洞），成员 way 不会重复输出。
`area.outer_rings()` / `inner_rings()` 保证洞挂在正确的外环上。

### 9.4 关系拼装失败的降级处理（重要）

**背景**：OSM 的矩形裁剪（`osmium extract`）会把跨界的大水体/边界关系切断。
例如 `岳阳.pbf` 是 osmium/1.16.0 生成的裁剪，而 OSM 的 **洞庭湖** 是一个
跨岳阳/益阳/常德的 multipolygon 关系 `r1462005`，共 **231 条边界 way**；
裁剪后文件里只剩 **97 条**（缺 134 条），环闭不上。

若转换器“只用关系面、直接丢掉成员 way”，就会把整个洞庭湖静默丢掉。
本工具的降级逻辑（`_ConvertHandler.finalize`）：

- 记录每个 multipolygon/boundary 关系是否被 area manager 成功拼装；
- **拼装失败**的关系，退回用现存成员几何输出：
  - 闭合成员 way → `shapely.unary_union` 合并成 `MultiPolygon`（id=关系 id，带关系 tags/name）
  - 开线成员 way → `shapely.linemerge` 合并成 `LineString`（洞庭湖这种会归为 `waterway`）
- 拼装成功的关系，成员 way 仍不重复输出。

效果：洞庭湖从“完全消失”变成“湖岸线 + 可恢复的闭合片段”。
但**缺的那 134 条 way 找不回来**，所以湖看起来仍比真实小很多：

| 量 | 数值 |
|----|------|
| 洞庭湖关系成员 way | 231 条（仅 97 条在文件里） |
| 现存湖岸线总长 | 约 951 km |
| 可恢复闭合水面 | 约 68 km² |
| 真实洞庭湖 | 约 2800 km²（东洞庭约 1300 km²） |

**想要完整的洞庭湖**，只能换数据源：用 Geofabrik 的 `china` 或 `hunan`
完整 extract（或含整个洞庭湖范围的 `osmium extract` 区域），再重跑本工具。

> ✅ **2026-09-18 已按此解决**：岳阳改用 **`数据/源pbf/湖南.pbf` 全量**（48 MB，8.2 M 节点），
> 关系 r1462005 **231/231 条成员 way 全在** → 拼出完整湖面 **1078 km²**（含 155 个洲岛内环）。
> 配置方式：`trpg-map/城市.py` 的 `CITIES["岳阳"]["pbf"] = "湖南"`，
> 然后 `python pbf_to_json.py 数据/源pbf/湖南.pbf --city 岳阳`。
> 旧的 `岳阳.pbf` **不要再用于生成**（只有 97/231）。

---

## 10. 绘制总览地图（draw_map.py）

`draw_map.py` 可以读任意本工具产出的 JSON，直接画成一张 PNG 总览图。

```bash
# 基本：自动取景 + 区县名
python draw_map.py 数据/岳阳_OSM全量.json -o 岳阳地图.png --width 2600 --title "岳阳市全域图"

# 详细版：加建筑、居民小路、乡镇名
python draw_map.py 数据/岳阳_OSM全量.json -o 详图.png --labels all

# 高亮标注某个名字（朱砂红点+红字+红轮廓）
python draw_map.py 数据/岳阳_OSM全量.json -o 标注.png --annotate "洞庭湖"

# 用紫色虚线框标出“应有范围”（可重复）
python draw_map.py 数据/岳阳_OSM全量.json -o 标注.png \
    --region "111.90,28.65,113.20,29.60|洞庭湖应有范围（估算，仅存部分）"

# 手动指定图幅范围
python draw_map.py 数据/岳阳_OSM全量.json -o crop.png --bbox 112.7,29.1,113.4,29.6
```

参数：`--width`、`--margin`、`--title`、`--labels none|major|all`、`--bbox`、`--full`、
`--annotate`（逗号分隔名字）、`--region`（`min_lon,min_lat,max_lon,max_lat|标题`，可重复）。

图层顺序：土地（林/草/农）→ 水 → 水系线 → 行政边界（虚线）→ 道路（主/次/支）→ 地名。
另带标题、指北针、比例尺、墨色边框。

---

## 11. 已知差异（与 数据/扬州_OSM精简.json 对比）

| 项目 | 本工具 | 数据/扬州_OSM精简.json |
|------|--------|------------------------|
| 对象数量（默认） | 约 6.1 万 | 14683 |
| 道路数量 | 精选后仍偏多 | 3979（明显按类型抽稀过） |
| 建筑数量 | 精选后仍偏多 | 3396（明显按类型抽稀过） |
| 水源 | 精选后 3 千+ | 3413（基本全量） |

原因：`数据/扬州_OSM精简.json` 本身已经是**另一套管线精选+抽稀后的结果**，不是单纯
「30km 圆裁剪」能复现的。本工具负责「PBF → 同结构 JSON」这一步；后续的抽稀、古代化、
古代化请继续走 `draw_tiles/build_world.py`（一键：`../生成.py`）。

如果你希望本工具再加一层「道路/建筑按类型抽稀」来逼近 14683 的口径，可以改
`CURATED_FILTERS`，或用 `--bbox/--city` 缩小画框。

---

## 12. 常见问题

| 现象 | 处理 |
|------|------|
| `Open failed for '����.pbf'` | 老版本 bug；本脚本已自动复制到 ASCII 文件名，直接升级脚本即可 |
| 终端里中文像乱码 | 终端编码问题，数据本身正确；`chcp 65001` 或在代码里校验码点 |
| 对象太多 | 加 `--radius 30` 裁剪，或收紧 `CURATED_FILTERS` |
| 想保留全部要素 | 加 `--full` |
| 想改分类 | 改脚本顶部 `classify()` 和 `CURATED_FILTERS`，不用动主流程 |
| 想加新地图 | 换 `input` 和 `--name`，圆心/半径用 `--center-lon/--center-lat/--radius` |

---

## 13. 文件位置

```
trpg-map/
├── 城市.py                      ★ 城市单一真相源（中心 / 画框 / map_id / 源 pbf / 落脚点）
├── 生成.py                      ★ 一键链路：pbf → 数据 → 数据库 + 瓦片 → 前端
├── 数据/源pbf/<城市>.pbf        原始 OSM 输入（岳阳用 湖南.pbf）
├── pbf_to_json.py             本工具
├── 数据/<城市>_OSM精简.json     输出（按城市画框裁过）
├── draw_tiles/                 下游：南宋转译、瓦片、空间库、图标
│   ├── build_world.py          世界生成（多城市 CITY_CONFIGS + 建筑群）
│   ├── export_clickable.py / export_walkable.py
│   ├── db/map_spatial_<map_id>.db
│   ├── tilegen/                瓦片（输出 tiles/<map_id>/）
│   └── icongen/                地图图标
└── draw_map.py                 总览 PNG 绘制（调试用）
```
