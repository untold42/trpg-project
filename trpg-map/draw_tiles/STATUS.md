# STATUS.md — 项目交接状态

> 给新对话的快速入口：先读 `README.md`（架构/命令），再看本文件（当前进行到哪、下一步干什么）。

最后更新：2026-09-18（**多城市**）。扬州 / 岳阳两城共用一套机制：数据按 `<城市>_*.json`、
产物按 `<map_id>` 分目录；`城市.py` 是城市单一真相源；一键链路 `生成.py --city <城市>`。

---

## 一、当前数据流（地图 v4 · 多城市）

```
数据/源pbf/<城市>.pbf          （扬州.pbf；岳阳用 湖南.pbf 全量，否则洞庭湖拼不成面）
   │  pbf_to_json.py --city <城市>
   ▼
数据/<城市>_OSM精简.json       勿改
   │
   ├── build_world.py ────────► 数据/<城市>_南宋世界.json  勿手改
   │     读 <城市>_布点锚点.json（定点锚点）
   │        <城市>_建筑群.json（宫观院落：院墙/殿宇/廊庑/园圃）
   │        <城市>_POI.json   （POI 冻结表；存在则只读）
   │
   └─► export_clickable.py   ► ../trpg-client/public/data/<map_id>/clickable.geojson
       db/create_spatial_db.py ► db/map_spatial_<map_id>.db
       export_walkable.py    ► ../trpg-client/public/data/<map_id>/walkable.geojson（碰撞 + 地形）
       tilegen/generate_tiles.py ► tiles/<map_id>/ (z11–16)
                                    └─ 生成.py sync ► ../trpg-client/public/tiles/<map_id>/
```

> 数据统一在 **`trpg-map/数据/`**（与 `draw_tiles/` 同级），命名约定见 [`../数据/README.md`](../数据/README.md)。
> `map_id`（英文目录名）在 **`trpg-map/城市.py`** 的 `CITIES[城市]["map_id"]`。

前端（`trpg-project/trpg-client`，相对 draw_tiles 是 `../../trpg-client`）：
- 瓦片 `public/tiles/<map_id>/{z}/{x}/{y}.png`
- 点击层 `public/data/<map_id>/clickable.geojson`（扬州 2344 / 岳阳 2186 要素；民居已排除）
- 碰撞/地形层 `public/data/<map_id>/walkable.geojson`
- 图标 `public/mapicons/<键>/{day,night}.png`（**全局共用，不分城市**）
- 前端城市由 `src/in-game/mapId.ts` 的 `?map=` 决定；缺参时启动向 `GET /maps` 对齐

---

## 二、生成模型（build_world.py，SEED=42 可复现）

布局参数全在 **`CITY_CONFIGS`**（投影中心 / 老城 bbox / 坊名池 / 街巷改名 / 史实锚点 / 城外聚落 / 地名改名）。
⚠️ **扬州条目不许改**：SEED=42 下输出必须**逐字节不变**（本轮验证过 `git diff` 为空）。

**扬州（`yangzhou`）**（对象 13333）

| 层 | 来源 | 数量 | 说明 |
|----|------|------|------|
| 自然地理+锚点 | OSM 保留 | 4149 | water/waterway/natural/landuse + historic/tourism/place + 76 布点 |
| 城墙/城门 | 算法 | 6 | 大城 1 道城墙 + 东/南/西/北 4 门 + 水门；**城门=主街与城墙交点** |
| 老城道路 | OSM 老城内 | 123 | 历史街巷几何(四望亭街/国庆街/彩衣街…)，重新分级+改名 |
| 坊巷 | 算法 | 66 | 大块内补里坊棋盘格(间距~280m 抖动) |
| 坊面层 | 算法 | 165 | category=area，kind=坊，icon=ward；坊名全唯一 |
| 民居 | 算法 | 6231 | **瓦片不画**（classifier 跳过），仅保留 JSON/DB |
| POI | 算法 | 1663 | 按 song_kinds zone；命名池已扩，无重名 |

**岳阳（`yueyang`）**（对象 11692）：

| 层 | 数量 | 说明 |
|----|------|------|
| 洞庭湖 | 1 面（1078 km²） | 完整关系 r1462005（231/231 way，含 155 个洲岛内环） |
| 君山岛 / 君山茶园 | 各 1 | 岛 kind=洲（保留 `place=island`）；茶园=OSM 全岛 farmland 改名 |
| 坊 / 坊巷 / 官道 | 187 / 217 / 97 | 岳州古城（113.0865–113.1085, 29.3655–29.3875） |
| 民居 | 5801 | 不画 |
| POI | 1626 | |
| **锦香宫**（建筑群） | 16 个对象 | 院墙×4 / 宫门 / 正殿 / 东西厢 / 后殿 / **锦香阁** / 竹廊×2 / 果林×2 + 锚点 / 泊船处（550×400 m） |

> 两个城市的**城区算法是同一套**（坊巷棋盘 + 同种 POI 池），只是参数不同 → 风格差异未做（TODO §8.2）。

## 三、已完成（现状要点）

1. **build_world.py**：`--stage 1/2/3`，局部米制投影 + shapely；**多城市 CITY_CONFIGS**。
2. **城墙样式**：`tilegen/` 加 wall 层（config/classifier/spatial_index/renderer/generate_tiles）。
3. **民居瓦片隐藏**：`classifier.py` 对 `ancient_kind=民居` 返回 `other`（数据仍在 JSON/DB）。
4. **城门**：`build_gates()` 找 `primary/secondary` 主街与城墙交点放门；水门取水系穿墙处。
5. **坊名**：36 专名 + 两字吉祥字根组合（岳阳另有 16 个本地专名），均不重名。
6. **POI 命名**：前缀池组合扩到 1350，不再重名成裸"客栈"。
7. **城外**：无官道直线；仅真镇周边散落民居（按 `CITY_CONFIGS.towns`）。
8. **点击层/DB**：扬州 2344 / 岳阳 2186 要素；DB 与世界对象数一致。
9. **瓦片开始画建筑**（2026-09-18）：`renderer._draw_buildings`；民居仍不画。
10. **建筑群生成**（2026-09-18）：`build_compounds()` + `数据/<城市>_建筑群.json`。
11. **地形步速区**（2026-09-18）：`export_walkable.py` 的 `terrain` 层（带 `mult`）。

## 四、LLM 工具调用 + 玩家定位（trpg-server）

- `tools/map_query.py`：`query_nearby` / `query_place` / `list_map_kinds`；
  **多城市**：读 `db/map_spatial_<map_id>.db`，`map_id` 由 **玩家坐标** 推导（`tools/map_settings.py`）。
- **玩家定位**：`游戏数据/基本信息.json` 的 `位置`（`经度`/`纬度`）；`GET /location`。
- **新增路由**：`GET /maps`（可用地图 + 当前 + 各图 frame）、`POST /map`（记「上次看的图」，仅兑底）、
  `GET /search?q=`（跨城搜地点）、`GET /scene`（按地点给初始背景）。

## 五、待办 / 待你决定

- [ ] **后端启动依赖**：`main.py` 用 `get_collection("memory")`，若 chroma 无该集合会启动失败；
      首次需先跑 `python init_GM_DB.py`（或改 `get_or_create_collection`）。
- [ ] **美术图标**：`palace` 已新增；仍有其余缺图键会退化成棕色圆点。
- [ ] **扬州城墙史实微调**：大城为圆角矩形近似，城门名为通行称谓 —— 需查史料细化。
- [ ] **岳阳画框只含东洞庭**（取舍，见 README §17.4）。
- [ ] **地域差异化未做**：城区算法仍是同一套（见 TODO §8.2）。
- [ ] 布点调参（密度/POI 权重/坊巷间距）；瓦片文字标注（需中文字体）。

## 六、常用命令

```bash
# ---- 地图：一键链路（在 trpg-map 下，推荐）----
python 生成.py --city 岳阳                 # pbf → 世界 → 点击层/空间库/碰撞层 → 瓦片 → 拷前端
python 生成.py --city 扬州 --only tiles     # 只跑某一步：pbf/world/clickable/db/walkable/tiles/sync
python 生成.py --list

# ---- 地图：单步（在 draw_tiles 下，必须带 TRPG_CITY）----
TRPG_CITY=岳阳 python build_world.py
TRPG_CITY=岳阳 python export_clickable.py
TRPG_CITY=岳阳 python db/create_spatial_db.py
TRPG_CITY=岳阳 python export_walkable.py       # 碰撞 + 地形（依赖 db）
TRPG_CITY=岳阳 python tilegen/generate_tiles.py

# ---- 图标（在 icongen 下）----
python make_icons.py --report              # 哪些键缺图
python make_icons.py palace                # 只重生成一个键（产出 day/night）

# ---- 后端（在 trpg-server 下）----
python init_GM_DB.py                  # 首次：创建 chroma 集合
python main.py                        # 启动 Flask(5000)

# ---- 前端 ----
cd ../trpg-client && npm run dev       # ⚠️ 开发就用这个；**不要 npm run build**
npx tsc -b                             # 改完 TS/TSX 只跑类型检查
```

**顺序约束**：`build_world.py → export_clickable.py → create_spatial_db.py → export_walkable.py`。
改动进瓦片渲染（renderer/config/classifier/styles）时再重生成瓦片。

## 七、关键文件速查

| 文件 | 用途 |
|------|------|
| `../../README.md` / `../../TODO.md` | 总纲（架构/状态） / 待办 —— **先读这两个** |
| `../城市.py` | **城市单一真相源**：中心 / 画框 / `map_id` / 源 pbf / 落脚点 |
| `../生成.py` | 一键链路（pbf→world→clickable→db→walkable→tiles→sync） |
| `build_world.py` | **世界生成器**（保留层 + 城墙/道路/坊/民居/POI/城外 + **建筑群**） |
| `song_kinds.py` | 南宋 kind 词表（group/icon/zone/note） |
| `export_clickable.py` / `export_walkable.py` | 点击层 / 碰撞+地形层导出 |
| `db/create_spatial_db.py` + `query_nearby_spatial.py` | 空间库（含 `tags` 列） |
| `tilegen/` | 瓦片生成（分类/样式/空间索引/渲染；含城墙样式、民居隐藏、**建筑绘制**） |
| `icongen/` | 地图图标（day/night PNG）；`make_icons.py <键>` 单键重生成 |
| `../../数据/README.md` | 数据命名约定与血缘 |

| 数据位置 | 说明 |
|------|------|
| `../数据/源pbf/<城市>.pbf` | 原始 OSM（岳阳用 `湖南.pbf`） |
| `../数据/<城市>_OSM精简.json` | 按画框裁过（勿改） |
| `../数据/<城市>_布点锚点.json` | 定点锚点（勿改） |
| `../数据/<城市>_建筑群.json` | 宫观院落规格（院墙/殿宇/廊庑/园圃） |
| `../数据/<城市>_POI.json` | POI 冻结表（存在则只读） |
| `../数据/<城市>_南宋世界.json` | 生成产物（勿手改） |
| `db/map_spatial_<map_id>.db` | 空间库（LLM 查询） |

后端（`trpg-project/trpg-server`）：`tools/map_query.py`（地图查询 + 跨城搜索）/ `tools/map_settings.py`（当前城市=由坐标推导）/ `tools/location.py`（移动 + 跨城闸门）/ `main.py`（`/action` `/location` `/maps` `/map` `/search` `/scene`）

前端（`trpg-project/trpg-client`）：`src/in-game/mapId.ts`（`?map=`）/ `api.ts`（后端地址）/ `Map.tsx` / `ClickableLayer.tsx` / `walkable.ts`（碰撞+地形）/ `public/{mapicons,data/<map_id>,tiles/<map_id>}`

> 旧脚本 translate.py / place_ancient.py / merge_custom.py 已被 build_world.py 取代，**已不在仓库**。
> 旧 `map_spatial.db` / `public/data/*.geojson` / `public/tiles/{z}` 扁平路径**已迁移**到上面的一城一目录。
