# 古代扬州地图 —— 瓦片生成 & 数据处理

把 OpenStreetMap（OSM）的扬州现代数据，加工成**南宋风格**：
1. **瓦片图**（z/x/y.png，宣纸水墨风）——react-leaflet 底图；
2. **转译数据**（剔除现代要素、设施改名、归类、布点），并导出前端可点击层；
3. **空间数据库**（`map_spatial.db`，R-tree + 完整几何）——给 LLM / 脚本做精确空间查询。

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
map_ancient_center.json         原始 OSM 快照（14683 对象；唯一源文件，勿改）
        │
        ▼ translate.py           ①剔除现代要素 ②打南宋 kind ③改名/泛化
map_ancient_song.json           南宋转译版（~13261 保留下，另 +76 人工布点 = 13337）
        │           ▲
        │           └ place_ancient.py(生成) → custom_ancient.json
        │               merge_custom.py 并入 song json 并自动导出
        │
        ├─► export_clickable.py ──► 前端 public/data/clickable.geojson（6163 要素）
        │                           前端 public/mapicons/manifest.txt
        ├─► db/create_spatial_db.py ► db/map_spatial.db（13337 行，给 LLM 查）
        └─► tilegen/generate_tiles.py ► tiles/{z}/{x}/{y}.png（~2.9 万张）
                                        拷到 ../../trpg-client/public/tiles/
```

> 瓦片与点击层同源（都用 `map_ancient_song.json`），底图与可点击点一一对应；
> renderer 只画几何不画名字/点，改名字不用重生成瓦片。

---

## 二、目录结构与文件职责

```
draw_tiles/
├── map_ancient_center.json   原始 OSM（唯一源，勿手改）
├── translate.py              转译：剔除/打 kind/改名；输出 song json + 审计
├── place_ancient.py          人工布点（生成 custom_ancient.json）
├── merge_custom.py           把布点并入 song json，并自动重导出
├── export_clickable.py       从 song json 导出前端 clickable.geojson + manifest
├── song_kinds.py             南宋 kind 词表（group/icon/zone/note）
├── custom_ancient.json       布点结果（merge 用）
├── map_ancient_song.json     转译中件（瓦片/导出/建库的输入）
├── _translate_review.txt / _place_review.txt   脚本审计输出
├── tilegen/                  瓦片渲染簇（内部互相 import，单目录自洽）
│   ├── config.py             常量：路径/zoom/16:9 取景/颜色
│   ├── projection / geometry / classifier / spatial_index / styles
│   ├── texture.py / renderer.py
│   └── generate_tiles.py     主入口：自动取景 → 逐 zoom 逐瓦片生成
├── db/                       数据库（唯一一套）
│   ├── create_spatial_db.py      建 map_spatial.db（R-tree + 完整几何）
│   ├── query_nearby_spatial.py   点/线/面精确范围查询（给 LLM/调试）
│   └── map_spatial.db            结果库
└── tiles/                    瓦片输出
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

## 四、转译（translate.py，当前 v0.5）

流水线顺序：**剔除 → 归类 → 改名**；原名一律留 `name_modern`。

1. **剔除现代要素**（REMOVE_RULES / REMOVE_NAME_KEYWORDS）：铁路、停车场、加油站、ATM、信号塔、驾校/车管、电信营业厅、按摩/轮胎/烟草/保健品等现代门店、客运站、灯塔/水厂、纪念地（陵园/纪念馆）、史可法等后世人物命名、大学点位…（整类删）。
2. **归类**：`KIND_BY_TAG` 把 OSM 标签映射成南宋 kind（书院/医馆/客栈/酒楼/钱铺/寺观/园苑…），含：
   - `building=temple → 寺观`（只有 building 标签的殿堂不再误归宅）；
   - `amenity=post_office/parcel_locker → 递铺`、`public_bath → 浴堂`、`shelter → 亭` 等补充映射。
3. **普通建筑处理**（重要）：
   - kind=宅 的**普通建筑（有名无名一律）→ 民居**：统一名字"民居"、house 图标、可点；原商户/机关名留 `name_modern`；
   - 历史地标白名单（五亭桥/普哈丁园/贾氏庭院/四望亭/挡军楼/树人堂）保留点名；
   - 学舍等无点意义建筑去名（几何保留，不可点）。
4. **名字清洗/泛化**：去"扬州/市/区/序数/人民/中心"等；校名先切"分校/校区/XX小学/中学"再补 kind（梅岭小学金辉分校→梅岭书院）；品牌按类型转（蜜雪冰城→饮品铺、兰州拉面→食铺、各家银行→钱铺、顺丰/菜鸟→递铺）；现代菜品后缀剥掉（蒋家桥饺面店→蒋家桥酒楼）；`EXACT_GENERIC` 表处理个别整名。
5. **现代公园清洗**：XX体育休闲/湿地公园→地名主干；人才/马拉松/五一/邻里等现代主题公园→去名（几何保留）。
6. **功能楼/杂点去名**：教学楼/传达室/文化宫/游客服务中心/公园出入口等→去名。
7. **输出**：`map_ancient_song.json` + `_translate_review.txt`（改名/去名清单与 kind 统计）。

每次改 translate/词表后重跑：
```bash
python translate.py
python merge_custom.py          # 重新并入 76 布点 + 自动 export
```

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

## 六、数据库（唯一：map_spatial.db，给 LLM / 脚本精确查询）

```bash
python db/create_spatial_db.py                 # 重建 db/map_spatial.db
python db/query_nearby_spatial.py --lon 119.4175 --lat 32.41 --r 1
```

- 表结构：
  ```
  maps(map_id, name)                        -- 一张地图一行
  features(fid, map_id, ..., name, ancient_kind, category, tags, coords)
  features_rtree(fid, minx, maxx, miny, maxy)  -- 原生 R-tree
  ```
- 点/线/面全部精确：R-tree 方框粗筛 → shapely 算最近距离。
- 内容与 song json 同源（13337 行），含 3310 个 `民居`（建筑多边形）。
- 加新地图：`--input 别的.json --map 新地图名 --map-name 新地图`，查询加 `--map 新地图名`。

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
python translate.py                             # 转译（改规则后必跑）
python place_ancient.py --hotspots 6 --per-hotspot 12 \
    --center-lon 119.438 --center-lat 32.398 --radius 1.3   # 布点预览
python merge_custom.py                          # 并入布点 + 重新导出
python export_clickable.py                      # 只导出点击层/manifest
python tilegen/generate_tiles.py                # 重生成瓦片（10–20 分钟）
python db/create_spatial_db.py                  # 重建 map_spatial.db
python db/query_nearby_spatial.py --lon 119.4175 --lat 32.41 --r 1

# 前端
cd ../../trpg-client && npm run dev
```

**顺序约束**：改 translate/词表 → `translate.py → merge_custom.py`（内含 export）；只有动渲染设置（renderer/config）才需重生成瓦片。

---

## 八、常见问题

| 现象 | 处理 |
|------|------|
| translate 控制台中文乱码 | 编码问题，数据正常；看 `_translate_review.txt` |
| 想还原原名 | 读 `name_modern` |
| 地图上点不开 | 只收有名字要素；建筑统一为"民居"（见五） |
| 改词表后 db 没变 | `python translate.py && python db/create_spatial_db.py` |
| 民居图标太密 | 前端 ClickableLayer 给 `kind=民居` 加 z16 阈值（见五） |
