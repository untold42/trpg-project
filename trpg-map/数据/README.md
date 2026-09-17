# trpg-map/数据/ —— 地图数据总目录

所有城市的地图数据都放这里。**命名约定：`<城市>_<用途>.json`**。

---

## 目录内容

```
数据/
├── 源pbf/
│   ├── 扬州.pbf                  原始 OSM 二进制
│   ├── 岳阳.pbf                  ⚠️ **旧的、被矩形裁断的**（洞庭湖关系缺 134 条 way）
│   └── 湖南.pbf                  ★ 岳阳现在是**用它全量裁**（才能拿到完整洞庭湖）
│
├── 扬州_OSM精简.json             ★ build_world.py 的输入（按城市画框裁过）
├── 扬州_布点锚点.json             ★ build_world.py 的输入（76 个人工锚点）
├── 扬州_POI.json                 ★ POI 冻结表（存在则 build_world 只读它，不再随机）
├── 扬州_南宋世界.json             ★ 下游唯一输入（瓦片/点击层/空间库）
│
├── 岳阳_OSM精简.json             ★ 同上（35831 对象）
├── 岳阳_布点锚点.json             ★ 锦香宫 + 岳阳楼/慈氏塔/文庙/南津古渡/岳州关/崇胜寺…
├── 岳阳_建筑群.json               ★ 锦香宫院落规格（院墙/殿宇/廊庑/园圃/泊船处）
├── 岳阳_POI.json                 ★（首次生成时冻结）
├── 岳阳_南宋世界.json             ★（11692 对象）
│
├── 岳阳_OSM全量.json             （旧：来自被裁断的 岳阳.pbf，已弃用）
│
└── 中间产物/                      历史中间产物（已 gitignore）
    └── 扬州_未抽稀_旧管线.json
```

---

## 完整链路（一条命令）

```bash
cd trpg-map
python 生成.py --city 扬州
```

它依次跑：

```
源pbf/<源>.pbf                       （岳阳的源是 湖南.pbf，由 城市.py 的 "pbf" 字段指定）
   │  ① pbf_to_json.py --city <城市>   按「城市画框」矩形裁剪
   ▼
数据/<城市>_OSM精简.json
   │  ② draw_tiles/build_world.py      保留地理层 + 算法生成城区 + 建筑群
   ▼
数据/<城市>_南宋世界.json
   ├─ ③ export_clickable.py   → trpg-client/public/data/<map_id>/clickable.geojson
   ├─ ④ db/create_spatial_db.py → draw_tiles/db/map_spatial_<map_id>.db
   ├─ ⑤ export_walkable.py    → trpg-client/public/data/<map_id>/walkable.geojson
   └─ ⑥ tilegen/generate_tiles.py → draw_tiles/tiles/<map_id>/{z}/{x}/{y}.png
                                        └─ ⑦ 拷到 trpg-client/public/tiles/<map_id>/
```

`<map_id>` 是英文目录名（`扬州`→`yangzhou`，`岳阳`→`yueyang`），真相源在 `trpg-map/城市.py`。

单步重跑：`python 生成.py --city 岳阳 --only tiles`

---

## 命名约定

| 文件 | 含义 | 谁生成 | 谁消费 |
|---|---|---|---|
| `<城市>.pbf` | 原始 OSM 二进制 | OSM 官网 / Geofabrik | `pbf_to_json.py` |
| `<城市>_OSM精简.json` | **按画框裁过**的 OSM | `pbf_to_json.py --city` | `build_world.py` |
| `<城市>_布点锚点.json` | 人工布点（POI 种子） | 人工 / 脚本 | `build_world.py` |
| `<城市>_POI.json` | **POI 冻结表**（名字+位置） | `冻结POI.py` | `build_world.py` |
| `<城市>_南宋世界.json` | **可玩世界** | `build_world.py` | 瓦片 / 点击层 / 空间库 |

### ⚠️ 为什么必须有 POI 冻结表

`build_world.build_pois()` 原本每次运行都**重新随机生成**约 2200 个 POI
（`rng` 采样位置 + `rng.choice(名池)` + 类别）。于是：

| 来源 | 数量 | 稳定性 |
|---|---|---|
| `_布点锚点.json` 固定锚点 | 76 | ✅ 稳定 |
| 运行时生成的 POI | ~1700 | ❌ **重跑保留率仅 16%** |

实测后果：存档里的「怀茂青楼」「聚乐邸店」「泰济酒肆」等名字全部对不上，
连带 `place_notes`（地点见闻）出现孤儿条目、`足迹.json` 引用失效。

**修法**：用 `冻结POI.py` 把 POI 冻成 `_POI.json`，`build_world` 之后只读它。

```bash
# 从当前世界冻结（首次）
python 冻结POI.py --city 扬州

# 想恢复某一版的名字：用那一版的世界文件作为来源
python 冻结POI.py --from <旧世界>.json --city 扬州
```

冻结后 POI 名字/位置**永久稳定**，还能手工改单个 POI（改名 / 挪位置 / 删）。

> 注：冻结表里落到水面的 POI 极少（扬州 9/1744 ≈ 0.5%，多数是「画舫」——本来就该在水上）。

> 下游（`tilegen/`、`export_clickable.py`、`db/create_spatial_db.py`）**只读 `_南宋世界.json`**。

---

## 核心原则：裁剪与取景用同一份画框

**画框定义在 `trpg-map/城市.py`**（中心 + 画框宽 + 16:9），两边共用：

| 使用者 | 怎么用 |
|---|---|
| `pbf_to_json.py --city 扬州` | `城市.frame_bbox("扬州")` → 矩形裁剪 |
| `draw_tiles/tilegen/config.py` | 同一份 `FRAME` → 决定生成哪些瓦片 |

**为什么必须一致**：以前 PBF 不裁（数据覆盖 190×170 km），瓦片却自己从数据里算一个
16:9 画框 —— 结果**77 MB 的数据里只有 63% 会被画出来**，其余纯浪费。

> ⚠️ **不要再用 `--radius`**。圆形裁剪有两个坑：
> ① 对象级裁剪（一个顶点在圆内就整段保留），长要素要么全进要么全丢；
> ② 半径选小了会丢关键要素 —— 实测 `--radius 15` 会把**长江整条裁掉**
> （长江离扬州城中心最近 16–17 km）。

---

## 新增一座城市

> ✅ 2026-09-18 起：**build_world.py 已多城市化**（`CITY_CONFIGS`），新城市不再需要改代码，只需加配置 + 布点。

### 1. 放原料

```
数据/源pbf/<城市>.pbf        （或 <省>.pbf 全量 —— 如果该城的关键大要素（如大湖）
                              会在矩形裁切时被切断，就用全量，并在城市配置里写 "pbf": "<省>"）
```

### 2. 在 `trpg-map/城市.py` 加配置

```python
CITIES = {
    ...
    "苏州": {
        "map_id": "suzhou",                      # 英文目录名（资产分目录用）
        "center_lon": 120.62,
        "center_lat": 31.30,
        "frame_w_km": 100.7,
        "aspect": (16, 9),
        # "pbf": "江苏",                         # 可选：源 pbf 名 ≠ 城市名时
        # "start": {"lon": ..., "lat": ..., "name": "..."},   # 落脚点
    },
}
```

### 3. 在 `draw_tiles/build_world.py` 的 `CITY_CONFIGS` 加一条

必填：`center`（投影中心）/ `old_city_bbox`（老城范围）/ `ward_names` / `road_rename` /
`anchor_kind` / `towns`；可选 `content_radius_m`（默认 30 km）/ `rename`（地名改名）。

### 4. 准备布点（可选但强烈建议）

```
数据/<城市>_布点锚点.json     {objects: [{name, kind, lon, lat}]}     ← 史实/剧情定点
数据/<城市>_建筑群.json       {compounds: [{name, layout, lon, lat, w_m, h_m, ...}]} ← 宫观院落
```

### 5. 一键跑

```bash
cd trpg-map
python 生成.py --city 苏州          # pbf → 世界 → 点击层/空间库/碰撞层 → 瓦片 → 拷前端
```

跑之前建议先 `python 生成.py --city 苏州 --only world` 验证世界生成。

### ⚠️ 仍需注意

- **城区算法是同一套**（坊巷棋盘 + 同种 POI 池）—— 每个城会“长得像”，只是参数不同。
  风格差异（江南水乡/北方中原/山地关隘…）**尚未做**（见 `TODO.md` §8.2）。
- **扬州条目不许改**（SEED=42 逐字节一致性）。
- 新城的 **`CITIES` 条目 + `CITY_CONFIGS` 条目两边都要加**（前者管资产/画框/裁剪，后者管城区布局）。

---

## 数据血缘（扬州）

```
扬州.pbf
   │  pbf_to_json.py --city 扬州        ← 画框 100.7×56.6 km
   ▼
扬州_OSM精简.json
   │  build_world.py
   │    · 保留：water / waterway / natural / landuse / place / historic / tourism
   │          + 名字在 ANCHOR_KIND 里的锚点 + `place=island` 的岛
   │    · 丢弃：全部现代要素（boundary / railway / leisure / line / poi / man_made…）
   │    · 丢弃：building / road（改为算法生成）
   │    · 新增：水道 buffer 成面（长江 1500m）
   │    · 新增：城墙/城门/坊/坊巷/民居/POI/城外聚落 + 建筑群
   ▼
扬州_南宋世界.json  ──►  瓦片 / 点击层 / 空间库
```

## 数据血缘（岳阳）

```
湖南.pbf  （⚠️ 不是被裁断的 岳阳.pbf）
   │  pbf_to_json.py --city 岳阳        ← 画框 100.7×56.6 km（只含东洞庭）
   ▼
岳阳_OSM精简.json （35831 对象）
   │  build_world.py
   │    · 洞庭湖 r1462005 是**关系面**：任一顶点在框内就整块保留 → 框外的西/南洞庭也在数据里
   │    · 新增：岳州古城 + 坊/民居/POI + **锦香宫建筑群** + 君山茶园改名
   ▼
岳阳_南宋世界.json （11692 对象）──► 瓦片 / 点击层 / 空间库
```

`中间产物/扬州_未抽稀_旧管线.json` 是**旧管线**（已退役的 `cut.py` + 更早的转换工具）
留下的中间产物，**不可再生**（生成它的工具已不在仓库），仅作追溯用。
