# 南宋地图 —— 瓦片生成 & 数据处理（多城市）

把 OpenStreetMap（OSM）的现代数据，加工成**南宋风格**：
1. **瓦片图**（z/x/y.png，宣纸水墨风）——react-leaflet 底图；
2. **转译数据**（剔除现代要素、设施改名、归类、布点），并导出前端可点击层；
3. **空间数据库**（`map_spatial_<map_id>.db`，R-tree + 完整几何）——给 LLM / 脚本做精确空间查询。

> **2026-09-18 起支持多城市**：扬州（`yangzhou`）/ 岳阳（`yueyang`）。
> 城市列表与画框的**单一真相源是 `trpg-map/城市.py`**；资产按 `<map_id>` 分目录。
> 一键链路：`cd trpg-map && python 生成.py --city <城市>`。
> 下文旧命令里没写 `TRPG_CITY` 的，默认都是扬州。

## 目录布局（monorepo）

```
<任意盘符>/trpg-project/            ← 三个项目并排
├── trpg-map/draw_tiles/           ← 本仓库（数据处理 & 瓦片）
├── trpg-client/                   ← 前端（react-leaflet）
└── trpg-server/                   ← 服务端（未接入地图数据）
```

下文命令默认在 `trpg-map/draw_tiles/` 内执行；前端在 `../../trpg-client`。

---

## 一、整体数据流

```
trpg-map/数据/源pbf/<城市>.pbf           （岳阳用 湖南.pbf 全量）
        │            ▲
        │            └ trpg-map/数据/<城市>_布点锚点.json（定点锚点）
        │              trpg-map/数据/<城市>_建筑群.json（宫观院落）
        ▼ build_world.py              ①丢弃现代要素 ②算法生成坊/民居/官道/坊巷/建筑群 ③打 ancient_kind
trpg-map/数据/<城市>_南宋世界.json      可玩世界
        │
        ├─► export_clickable.py ──► ../../trpg-client/public/data/<map_id>/clickable.geojson
        │                         ► ../../trpg-client/public/mapicons/manifest.txt
        ├─► db/create_spatial_db.py ► db/map_spatial_<map_id>.db（给 LLM 查）
        ├─► export_walkable.py ──► ../../trpg-client/public/data/<map_id>/walkable.geojson（碰撞+地形）
        └─► tilegen/generate_tiles.py ► tiles/<map_id>/{z}/{x}/{y}.png
                                        拷到 ../../trpg-client/public/tiles/<map_id>/
```

> `map_id`（英文目录名）在 `trpg-map/城市.py` 的 `CITIES[城市]["map_id"]`。

> **数据已统一收到 `trpg-map/数据/`**（与 `draw_tiles/` 同级），
> 命名约定与完整血缘见 [`../数据/README.md`](../数据/README.md)。
> 瓦片与点击层同源（都用 `扬州_南宋世界.json`），底图与可点击点一一对应；
> renderer 只画几何不画名字/点，改名字不用重生成瓦片。

---

## 二、目录结构与文件职责

```
draw_tiles/
├── 城市.py（在上一级 trpg-map/） 城市单一真相源
├── 生成.py（在上一级 trpg-map/） 一键链路
├── build_world.py            世界生成（多城市 CITY_CONFIGS；含建筑群）
├── export_clickable.py       导出前端 clickable.geojson + manifest
├── export_walkable.py        导出碰撞层 + 地形步速层
├── song_kinds.py             南宋 kind 词表（group/icon/zone/note）
├── tilegen/                  瓦片渲染簇（内部互相 import，单目录自洽）
│   ├── config.py             常量：路径/zoom/取景（城市画框）/颜色
│   ├── projection / geometry / classifier / spatial_index / styles
│   ├── texture.py / renderer.py（含建築绘制 _draw_buildings）
│   ├── preview.py            快速预览：只生成指定地点附近几张瓦片拼成一张图
│   └── generate_tiles.py     主入口：逐 zoom 逐瓦片生成 → tiles/<map_id>/
├── icongen/                 地图图标（day/night PNG，make_icons.py <键>）
├── db/                       数据库（一城市一套）
│   ├── create_spatial_db.py      建 map_spatial_<map_id>.db（含 tags 列）
│   ├── query_nearby_spatial.py   点/线/面精确范围查询（给 LLM/调试）
│   └── map_spatial_<map_id>.db   结果库
├── tiles/<map_id>/           瓦片输出（gitignore）
└── _preview/                 预览输出（latest/ 下是最新一组）

数据（全部在 trpg-map/数据/，见 ../数据/README.md）：
    <城市>_OSM精简.json / <城市>_布点锚点.json / <城市>_建筑群.json / <城市>_南宋世界.json
```

- 渲染管线文件职责：见各文件 docstring（classifier 分图层、renderer 画 256×256 + 宣纸纹理等）。
- **前端侧**：`trpg-client/src/in-game/Map.tsx`（bounds/zoom）、`ClickableLayer.tsx`（点击层/图标层）、`index.css`、`public/{tiles,data,mapicons}`。

---

## 三、瓦片生成

### 取景（自动 16:9）

`tilegen/config.py`：
- `CONTENT_CENTER`(119.4175, 32.41)、`CONTENT_MAX_KM=30`：只统计 30km 内对象的外接矩形；
- 以中心外扩成 `16:9`，四周留白 `MAP_MARGIN_FRACTION=3%`；
- zoom 11=总览，16=最大细节。

```bash
python tilegen/generate_tiles.py      # 输出到 tiles/（约 10–20 分钟）
# 然后拷贝瓦片到前端：
cp -r tiles/{11..16} ../../trpg-client/public/tiles/
```

前端限制：`minZoom=11, maxZoom=16, maxBounds, noWrap`；Vite 忽略 `public/tiles` 监视（见 vite.config.ts）。
> 改动 `CONTENT_MAX_KM`/留白/zoom 后需重生成瓦片，且 `Map.tsx` 的 `MAP_BOUNDS` 按 generate_tiles 打印的 bbox 更新。

---

## 四、世界生成（build_world.py）

**一步生成**：读 `trpg-map/数据/扬州_OSM精简.json` + `扬州_布点锚点.json`，
输出 `trpg-map/数据/扬州_南宋世界.json`。

核心思路：**推翻现代 OSM 城区，只保留自然地理 + 史实锚点，其余算法生成。**

分阶段（`--stage` 控制）：

| stage | 内容 |
|---|---|
| 1 | 保留层（自然地理 water/waterway/natural/landuse + 锚点）+ 城墙/城门 + 老城道路 + 坊面层 |
| 2 | + 坊内民居矩形 |
| 3 | + POI 布点 + 城外官道/聚落（**完整**，默认） |

**保留 vs 重建**（实测）：

| 处理 | 类别 |
|---|---|
| 原样搬运（几何逐字节相同） | water 3413、waterway 199、natural 204、landuse 88、place 81、tourism 17、historic 5 |
| 整体丢弃（现代要素） | railway / boundary / leisure / line / poi / poi_area / man_made / shop / point |
| 算法生成 | area 165（坊）、building 6230（坊内民居）、road 190（官道 88 + 坊巷 101 + 城墙 1）、custom 1744（POI） |

产出对象带 `ancient_kind`（8432 个），词表见 `song_kinds.py`。

```bash
python build_world.py --stage 1
python build_world.py            # 完整（默认）
```

> 旧的 `translate.py` / `place_ancient.py` / `merge_custom.py` 已被 `build_world.py` 取代，**已不在仓库里**。

---

## 五、可点击层 & 前端弹窗

`export_clickable.py` 从 song json 导出 `clickable.geojson`：
- **只收有名字的要素**，去掉 boundary/巨型几何；properties 含 `name / kind / group / icon / category / name_modern / tags(子集)`；
- 每个 kind 打 `group`（酒楼→饮食、书院→文教…，种子=song_kinds，兜底表补茶肆/官道/镇村等）；
- 同名要素（如一个景点的水面/绿地/景点三条）暂不去重，属已知项。

前端 `ClickableLayer.tsx`：
- **命中层**：全缩放可点（多边形按面、点按 16px 热区），弹窗墨色样式；
- **图标层**：`zoom≥15` 画图标（`/mapicons/<icon>.png`），缺图回退棕色小圆点；`kind=民居` 因数量多是否延后到 z16 待定（可在本组件加第二个阈值）；
- **弹窗徽章**：第 1 个=kind，第 2 个=group（不再显示 OSM category 的"地点/游处"等）。

---

## 六、数据库（一城市一套：`map_spatial_<map_id>.db`，给 LLM / 脚本精确查询）

```bash
TRPG_CITY=岳阳 python db/create_spatial_db.py   # 重建 db/map_spatial_yueyang.db（默认扬州）
python db/query_nearby_spatial.py --lon 119.4175 --lat 32.41 --r 1
```

- 表结构：
  ```
  maps(map_id, name)                        -- 一张地图一行
  features(fid, map_id, oid, name, name_modern, category, ancient_kind,
           geometry_type, coords, description, hours, tags)
  features_rtree(fid, minx, maxx, miny, maxy)  -- 原生 R-tree
  ```
- 点/线/面全部精确：R-tree 方框粗筛 → shapely 算最近距离。
- 内容与 `<城市>_南宋世界.json` 同源；`民居` 也在库里（瓦片不画，但 LLM 查得到）。
- 一城市一个库，**互不覆盖**；库名（`map_id`）由 `城市.py` 决定，一般不用手传 `--map`。
- `query_nearby_spatial.py` 读 `TRPG_MAP`（默认 yangzhou）。

### 给 LLM 的查询示例
```sql
-- 某类有多少个
SELECT COUNT(*) FROM features WHERE map_id='yangzhou' AND ancient_kind='书院';

-- 某点落在哪个建筑里（民居判定）：方框粗筛后取最近形
SELECT f.fid, f.ancient_kind, f.name FROM features f
JOIN features_rtree r ON f.fid = r.fid
WHERE f.map_id='yangzhou' AND f.category='building'
  AND r.minx<=? AND r.maxx>=? AND r.miny<=? AND r.maxy>=?;
```

将来更大：几十万条内 R-tree+shapely 足够；更大/并发平移 PostGIS/SpatiaLite，schema 概念一致。

---

## 七、常用命令（默认在 draw_tiles/ 内）

```bash
# —— 数据层（在 trpg-map/ 内）——
python pbf_to_json.py 数据/源pbf/扬州.pbf --city 扬州   # → 数据/扬州_OSM精简.json
python 生成.py --city 扬州                              # 一键跑完整链路（见 ../数据/README.md）
TRPG_CITY=扬州 python draw_tiles/build_world.py        # → 数据/扬州_南宋世界.json（单步默认扬州）

# —— 产物层（在 draw_tiles/ 内）——
python export_clickable.py                    # 点击层 + manifest
python tilegen/preview.py 16 119.4365 32.394 3   # 快速预览几张瓦片（几秒）
python tilegen/generate_tiles.py              # 全量瓦片（~10 分钟）
TRPG_CITY=岳阳 python db/create_spatial_db.py  # 重建 map_spatial_yueyang.db
python db/query_nearby_spatial.py --lon 119.4175 --lat 32.41 --r 1

# —— 前端 ——
cd ../../trpg-client && npm run dev
```

**顺序约束**：改世界生成（`build_world.py`）→ 先重跑它，再 export / 建库；
只改渲染设置（`tilegen/config.py` / `renderer.py`）→ 只需重生成瓦片。

---

## 八、常见问题

| 现象 | 处理 |
|------|------|
| 控制台中文乱码 | Windows 编码问题，数据正常；加 `PYTHONIOENCODING=utf-8` |
| 想还原原名 | 读 `name_modern` |
| 地图上点不开 | 只收有名字要素；建筑统一为"民居"（见五） |
| 改了 build_world 后 db 没变 | `python build_world.py && python db/create_spatial_db.py` |
| 民居图标太密 | 前端 ClickableLayer 给 `kind=民居` 加 z16 阈值（见五） |
