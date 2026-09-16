# trpg-map/数据/ —— 地图数据总目录

所有城市的地图数据都放这里。**命名约定：`<城市>_<用途>.json`**。

---

## 目录内容

```
数据/
├── 源pbf/
│   ├── 扬州.pbf                  原始 OSM 二进制
│   └── 岳阳.pbf
│
├── 扬州_OSM精简.json             ★ build_world.py 的输入（按城市画框裁过）
├── 扬州_布点锚点.json             ★ build_world.py 的输入（76 个人工锚点）
├── 扬州_POI.json                 ★ POI 冻结表（存在则 build_world 只读它，不再随机）
├── 扬州_南宋世界.json             ★ 下游唯一输入（瓦片/点击层/空间库）
│
├── 岳阳_OSM全量.json             （旧：未裁剪的全量，待重跑为 _OSM精简）
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
源pbf/扬州.pbf
   │  ① pbf_to_json.py --city 扬州      按「城市画框」矩形裁剪
   ▼
数据/扬州_OSM精简.json
   │  ② draw_tiles/build_world.py       保留地理层 + 算法生成城区
   ▼
数据/扬州_南宋世界.json
   ├─ ③ export_clickable.py   → trpg-client/public/data/clickable.geojson
   ├─ ④ db/create_spatial_db.py → draw_tiles/db/map_spatial.db
   └─ ⑤ tilegen/generate_tiles.py → draw_tiles/tiles/{z}/{x}/{y}.png
                                        └─ ⑥ 拷到 trpg-client/public/tiles/
```

单步重跑：`python 生成.py --only tiles`

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

### 1. 放原料

```
数据/源pbf/<城市>.pbf
```

### 2. 在 `trpg-map/城市.py` 加配置

```python
CITIES = {
    ...
    "苏州": {
        "center_lon": 120.62,
        "center_lat": 31.30,
        "frame_w_km": 100.7,
        "aspect": (16, 9),
    },
}
```

### 3. 跑前两步

```bash
cd trpg-map
python pbf_to_json.py 数据/源pbf/苏州.pbf --city 苏州   # → 数据/苏州_OSM精简.json
python 生成.py --city 苏州                             # 会自动停在第 ② 步并提示
```

### ⚠️ 第 ② 步目前只有「扬州」

`draw_tiles/build_world.py` 里的**坊 / 城墙 / 官道 / 坊巷 / POI 布局是扬州硬编码的**。
要支持新城市，需要：

1. **`数据/<城市>_布点锚点.json`** —— 人工/算法布点（扬州有 76 个锚点）
2. **把 build_world.py 里的扬州 LAYOUT 参数抽成城市配置**
   （老城范围 `OLD_CITY_BBOX`、投影中心 `PROJ_LON0/LAT0`、坊名池、城门位置…）

在此之前，新城市只能跑到第 ① 步（拿到裁剪好的 OSM）。

---

## 数据血缘（扬州当前状态）

```
扬州.pbf
   │  pbf_to_json.py --city 扬州        ← 画框 100.7×56.6 km
   ▼
扬州_OSM精简.json
   │  build_world.py
   │    · 保留：water / waterway / natural / landuse / place / historic / tourism
   │    · 丢弃：全部现代要素（boundary / railway / leisure / line / poi / man_made…）
   │    · 丢弃：building / road（改为算法生成）
   │    · 新增：水道 buffer 成面（长江 1500m）
   ▼
扬州_南宋世界.json  ──►  瓦片 / 点击层 / 空间库
```

`中间产物/扬州_未抽稀_旧管线.json` 是**旧管线**（已退役的 `cut.py` + 更早的转换工具）
留下的中间产物，**不可再生**（生成它的工具已不在仓库），仅作追溯用。
