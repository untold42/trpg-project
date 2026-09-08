# STATUS.md — 项目交接状态

> 给新对话的快速入口：先读 `README.md`（架构/命令），再看本文件（当前进行到哪、下一步干什么）。

最后更新：城区算法生成完成；民居瓦片隐藏、数据留 DB；城门改到"道路穿墙处"；POI 重名已修；新增 LLM 地图查询工具 + 前端玩家红点定位。

---

## 一、当前数据流（地图 v3）

```
map_ancient_center.json   (原始 OSM 14683，勿改)
custom_ancient.json       (76 布点锚点，勿改)
        │
        └──► build_world.py ──────────► map_ancient_song.json (12402 对象，勿手改)
                                           │  [保留层 4149 + 生成层 ~8253]
                                           │
                                           ├─► export_clickable.py ► 前端 clickable.geojson (2202 要素)
                                           ├─► db/create_spatial_db.py ► db/map_spatial.db (12402 行)
                                           └─► tilegen/generate_tiles.py ► tiles/ (z11–16)
```

前端（`trpg-project/trpg-client`，相对 draw_tiles 是 `../../trpg-client`）：
- 瓦片 `public/tiles/{z}/{x}/{y}.png`
- 点击层 `public/data/clickable.geojson`（2202 要素；民居已排除）
- 图标 `public/mapicons/*.png`（**现有 22 张，manifest 要求 46 键，缺 ~24 键，缺的显示棕色圆点**）
- `ClickableLayer.tsx`：隐形命中层(全缩放可点) + 图标层(zoom≥15)
- `Map.tsx`：打开即定位到玩家坐标(zoom 16)并画红色圆点

---

## 二、生成模型（build_world.py，SEED=42 可复现）

| 层 | 来源 | 数量 | 说明 |
|----|------|------|------|
| 自然地理+锚点 | OSM 保留 | 4149 | water/waterway/natural/landuse + historic/tourism/place + 76 布点 |
| 城墙/城门 | 算法 | 6 | 大城 1 道城墙 + 东/南/西/北 4 门 + 水门；**城门=主街与城墙交点** |
| 老城道路 | OSM 老城内 | 123 | 历史街巷几何(四望亭街/国庆街/彩衣街…)，重新分级+改名 |
| 坊巷 | 算法 | 66 | 大块内补里坊棋盘格(间距~280m 抖动) |
| 坊面层 | 算法 | 165 | category=area，kind=坊，icon=ward（瓦片不画，仅前端/DB）；**坊名 165 个全唯一** |
| 民居 | 算法 | 6231 | 坊内小矩形(城 6046 + 城外聚落 184 + 锚点 1)；**瓦片不画**（classifier 跳过），仅保留 JSON/DB |
| POI | 算法 | 1663 | 按 song_kinds zone：core/water/general/edge，81 种 kind；**命名池已扩，无重名** |

总数 **12402**（城内密、城外自然衰减）。瓦片可见层 = 水/道路/城墙/非民居建筑；点与民居不画。

## 三、已完成（现状要点）

1. **build_world.py**：`--stage 1/2/3`，局部米制投影 + shapely。
2. **城墙样式**：`tilegen/` 加 wall 层（config/classifier/spatial_index/renderer/generate_tiles）。
3. **民居瓦片隐藏**：`classifier.py` 对 `ancient_kind=民居` 返回 `other`（数据仍在 JSON/DB）。
4. **城门**：`build_gates()` 找 `primary/secondary` 主街与城墙交点放门；水门取水系穿墙处。
5. **坊名**：36 专名 + 两字吉祥字根组合，165 坊不重名。
6. **POI 命名**：前缀池组合扩到 1350，客栈/茶坊等不再重名成裸"客栈"。
7. **城外**：无官道直线；仅真镇周边散落民居。
8. **点击层/DB**：export 2202 要素、DB 12402 行，均正常。

## 四、LLM 工具调用 + 玩家定位（trpg-server）

- `llm.py` 新增 `map_query` 3 个工具 schema，已并入 `all_tools`：
  - `query_nearby`：坐标附近精确查询（默认排除"民居"噪音）
  - `query_place`：按名称/类别查地点
  - `list_map_kinds`：列出所有地点类别及数量
- `tools/map_query.py`：实现上述工具，读 `../trpg-map/draw_tiles/db/map_spatial.db`。
- `main.py`：`tools_map` 已接 `query_nearby / query_place / list_map_kinds`。
- **玩家定位**：
  - `tools/游戏数据/基本信息.json` 的 `位置` 增加 `经度`/`纬度`（当前=文昌阁 119.4282, 32.3964）。
  - `main.py` 新增 `GET /location` → `{lon, lat, 地点, 区域}`。
  - 前端 `Map.tsx`：打开地图先取 `/location`，以玩家坐标为中心并画红色圆点。

## 五、待办 / 待你决定

- [ ] **后端启动依赖（已知问题）**：`main.py` 用 `get_collection("memory")`，若 chroma 里没有该集合会启动失败 `NotFoundError: Collection [memory] does not exist`。首次需先跑 `python init_GM_DB.py` 建库（或在 main.py 改 `get_or_create_collection`）。
- [ ] **美术图标**：manifest 要求 46 键 PNG，缺 ~24 键（`public/mapicons/manifest.txt`，跑 export 会刷新）。
- [ ] **城墙史实微调**：大城为圆角矩形近似，城门名为通行称谓，可查史料细化。
- [ ] 布点调参（密度/POI 权重/坊巷间距）；瓦片文字标注（需中文字体）。
- [ ] 玩家位置更新工具（`update_location`）尚未做；目前手动改 JSON 后重开地图。

## 六、常用命令

```bash
# ---- 地图（在 draw_tiles 下）----
python build_world.py                 # 重新生成世界
python export_clickable.py            # 导出点击层 + 图标清单
python db/create_spatial_db.py        # 重建空间库

# 重生成瓦片（10–20 分钟），再拷贝到前端
python tilegen/generate_tiles.py
cp -r tiles/{11..16} ../../trpg-client/public/tiles/

# ---- 后端（在 trpg-server 下）----
cd ../trpg-server
python init_GM_DB.py                  # 首次：创建 chroma 集合 memory
python main.py                        # 启动 Flask(5000)

# ---- 前端 ----
cd ../trpg-client && npm run dev
```

**顺序约束**：改 `build_world.py` → `build_world.py → export_clickable.py → create_spatial_db.py`。改动进瓦片渲染（renderer/config/classifier）时再重生成瓦片。

## 七、关键文件速查

| 文件 | 用途 |
|------|------|
| README.md | 完整架构与命令 |
| build_world.py | **世界生成器**（保留层+城墙/道路/坊/民居/POI/城外） |
| song_kinds.py | 南宋 kind 词表（group/icon/zone/note） |
| map_ancient_center.json | OSM 原始（勿改） |
| custom_ancient.json | 76 布点锚点（勿改） |
| map_ancient_song.json | 生成产物（勿手改） |
| export_clickable.py | 点击层导出 |
| tilegen/config.py + renderer.py + classifier.py + spatial_index.py | 瓦片生成（含城墙样式/民居隐藏） |
| db/create_spatial_db.py + query_nearby_spatial.py + map_spatial.db | 空间库（LLM 查询） |

后端（`trpg-project/trpg-server`）：llm.py（工具 schema）/ tools/map_query.py（地图查询）/ main.py（/action、/location）/ tools/游戏数据/基本信息.json（玩家经纬度）

前端（`trpg-project/trpg-client`）：Map.tsx（红点+定位）/ ClickableLayer.tsx / index.css / public(mapicons,data,tiles)

> 旧脚本 translate.py / place_ancient.py / merge_custom.py 已被 build_world.py 取代，保留作参考。
