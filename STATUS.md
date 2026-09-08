# STATUS.md — 项目交接状态（trpg-project 根目录）

> 给新对话的快速入口：先读本文件了解全局，再按需进入各子项目。
> 地图生成细节见 `trpg-map/draw_tiles/STATUS.md`。

最后更新：StateManager 统一状态读写、工具消息塌缩、文件工具写保护、工具描述修复；新增 TODO.md；小游戏调研（TRPG2 现成实现）。

---

## 一、项目结构

| 目录 | 作用 |
|------|------|
| `trpg-map/` | 地图生成（`draw_tiles/`：世界生成器 + 瓦片 + 空间库） |
| `trpg-server/` | Flask 后端（LLM 主持人 + 全部游戏工具） |
| `trpg-client/` | React + Leaflet 前端（游戏界面 + 地图） |
| `trpg-world/` | 世界观文档（主持人规则 / 江湖势力 / 角色档案） |
| `trpg-db/` | chroma 向量库（LLM 记忆） |

---

## 二、地图（trpg-map/draw_tiles）

数据流（v3，已稳定，勿手改中间产物）：

```
map_ancient_center.json (原始 OSM，勿改)
custom_ancient.json (76 布点锚点，勿改)
        └──► build_world.py ──► map_ancient_song.json (12402 对象)
                                     ├─► export_clickable.py ► 前端 clickable.geojson (2202 要素)
                                     ├─► db/create_spatial_db.py ► map_spatial.db (12402 行)
                                     └─► tilegen/generate_tiles.py ► tiles/ (z11–16)
```

- 瓦片 `trpg-client/public/tiles/{z}/{x}/{y}.png`
- 点击层 `trpg-client/public/data/clickable.geojson`
- 图标 `trpg-client/public/mapicons/*.png`：**现有 53 张；manifest 46 键只剩 `ward` 未画（决定不画，坊面不显示图标）**
- 民居瓦片隐藏、数据留 JSON/DB；城门=主街穿墙处；POI 与坊名无重名。

---

## 三、后端工具清单（trpg-server）

`main.py` 的 `tools_map` 注册了以下工具（schema 在 `llm.py` 的 `all_tools`）：

### 本次新增（核心游戏循环）
| 工具 | 文件 | 作用 |
|------|------|------|
| `update_location` | `tools/location.py` | 移动玩家：地名（查空间库）或经纬度 → 写 `基本信息.json` 位置 + 自动记足迹 |
| `update_time` | `tools/time_weather.py` | 设置/推进时间（日期 + 十二时辰，`advance_hours` 自动跨天） |
| `update_weather` | `tools/time_weather.py` | 手动改天气字段 |
| `get_weather` | `tools/weather_system.py` | 按日期+区域查 `tools/天气数据/*.json` 写回天气；极端天气掷 d100 |
| `daily_event_dice` | `tools/event_dice.py` | 城市内「投骰子」：一级骰定类型 + 二级骰定烈度（混乱修正） |
| `travel_event_dice` | `tools/event_dice.py` | 旅途掷骰：单骰 + 混乱修正，低顺高不顺 |

### 原有工具
- 金钱 `modify_money` / `get_money`；背包 `modify_item/add_item/remove_item/get_inventory`
- 状态 `modify_hunger/health/injury/hp/tp` / `get_state`；属性 `get_ability`
- 文件 `list_directory/read_file/write_file/edit_file`；查人 `check_expression/find_specific_character`
- 骰子 `roll_dice`；机制 `save_game`；记忆库 `DB_query_tool_in_saving/DB_add_and_update_tool/DB_query_tool/check_DB_length`
- 地图查询 `query_nearby/query_place/list_map_kinds`（读 `trpg-map/draw_tiles/db/map_spatial.db`）

### 数据文件（tools/游戏数据/）
- `基本信息.json`：人物 / 时间 / 位置（含经纬度）/ 天气
- `足迹.json`：探索足迹（探索迷雾用）
- `混乱度.json`：混乱值 0–100（骰子修正用，当前 0）
- 另有：金钱/状态/背包/属性 等 JSON

**统一读写层**：所有游戏数据 JSON 都通过 `tools/state_manager.py` 的 `state` 单例读写（`load`/`save`/`update`），不再各自 open 文件。路径集中、容错、原子写、加锁。

### 路由
- `GET /location` → 玩家坐标
- `GET /explored` → 玩家坐标 + 足迹列表 + 解锁半径（每次调用把当前位置记入足迹）
- `POST /action` → 游戏主循环（LLM function calling）

### 上下文与性能
- `main.py` 的 `collapse_tool_messages()`：每轮 action 结束后清除工具中间消息（tool 结果 + 纯 tool_calls），history 只保留 system/user/assistant 正文
- `file_tools.py` 的 `_guard_game_data()`：文件工具禁止写 `游戏数据/` 目录，状态只能走专用工具
- 待做：history 滑动窗口/摘要（需记忆系统接住关键信息后才安全）

---

## 四、前端地图（trpg-client/src/in-game）

- `Map.tsx`：请求 `/explored`，玩家红点 + 足迹传给点击层；后端没起时降级为「显示全部」
- `ClickableLayer.tsx`：
  - **探索迷雾**：只渲染落在任一脚迹点半径内的 POI（`isExplored` + `visibleFeatures`）
  - **geojson 本地缓存**：IndexedDB（`GEO_VERSION="v1"`，重新导出后需 bump）
  - **图标层只渲染可视范围**（原一次渲染 2202 个 DOM marker 是卡顿主因）
  - `HitLayer`（全缩放可点）+ `IconsLayer`（zoom≥15）
- `vite.config.ts`：瓦片/图标加 `Cache-Control: immutable`（浏览器磁盘缓存，二次打开秒开）

---

## 五、世界观机制文档（trpg-world/主持人/）

`main.py` 通过 `folder_to_prompt("../trpg-world/主持人")` 自动注入 system prompt：

- `总览.md`（输出格式/铁律）、`世界.md`（时代背景）、`可用场景.md`、`可能性骰.md`、`特定人物.md`、`存档流程.md`（在 trpg-world/ 根）
- **本次新增**：`天气系统.md`、`日常骰子事件.md`、`旅途骰子事件.md`

---

## 六、待办 / 待决定

规划性待办见根目录 `TODO.md`（战斗系统 / 小游戏 / 背景音乐 / 返回结构重构 / 属性工具）。即时待办：

- [ ] **后端启动依赖**：`main.py` 用 `client.get_collection("memory")`，chroma 缺集合会启动失败。首次先跑 `python init_GM_DB.py`（或改 `get_or_create_collection`）。
- [ ] **混乱值评估自动化**：骰子会读 `混乱度.json`，但「收工时评估涨跌」（TRPG2 存档流程第 6 步）未搬入，目前手动改。可做 `evaluate_chaos` 工具。
- [ ] **history 滑动窗口/摘要**：需等记忆系统接住关键信息后再做（避免逻辑断裂）。已做：工具消息塌缩。
- [ ] **属性修改工具**：`属性.json` 目前只能读不能改（文件工具已禁写游戏数据），养成系统需要 `update_ability`/`train_skill`。
- [ ] 瓦片文字标注（需中文字体）；城墙史实微调。
- [ ] 图标 `ward.png` 决定不画，坊面在前端无图标（可接受）。

---

## 七、小游戏调研（TRPG2 现成实现）

`C:/Users/20866/Desktop/TRPG2/tools/` 有五个小游戏的完整 tkinter 实现，逻辑可复用：

| 文件 | 玩法 | 迁移要点 |
|------|------|---------|
| `围棋.py + gnugo.exe` | GNU Go 引擎（GTP 协议），5 档难度 | `GnuGoAI`/`Board` 类纯逻辑可搬后端，GUI 用 React Canvas 重写 |
| `投壶.py` | 力度 + 角度双阶段控制 | 状态机逻辑可搬后端 |
| `斗蟋蟀.py` | 蟋蟀自动对战 + 下注 | 最轻，直接挂 `modify_money` |
| `科举.py + 科举题库.json` | 答题 | 题库现成 |
| `生成天气.py` | 已迁移为本项目天气系统 | — |

统一迁移策略：**逻辑类搬后端 + Flask 路由，GUI 用 React 重画，结果从「存 JSON 文件」改为「回流游戏状态 + LLM 叙事」。** 建议先迁斗蟋蟀打通链路。

---

## 八、常用命令

```bash
# ---- 地图（trpg-map/draw_tiles 下）----
python build_world.py                 # 重新生成世界
python export_clickable.py            # 导出点击层 + 图标清单（刷新 manifest.txt）
python db/create_spatial_db.py        # 重建空间库
python tilegen/generate_tiles.py      # 重生成瓦片（10–20 分钟）
cp -r tiles/{11..16} ../../trpg-client/public/tiles/

# ---- 后端（trpg-server 下）----
python init_GM_DB.py                  # 首次：创建 chroma 集合 memory
python main.py                        # 启动 Flask(5000)

# ---- 前端（trpg-client 下）----
npm run dev
```

**顺序约束**：改 `build_world.py` → `build_world.py → export_clickable.py → create_spatial_db.py`；改瓦片渲染（tilegen/）才需重生成瓦片。

---

## 九、关键文件速查

| 文件 | 用途 |
|------|------|
| `trpg-server/main.py` | Flask 入口：路由 + tools_map 注册 + system 提示 |
| `trpg-server/llm.py` | 全部工具 schema + `send_messages`（DeepSeek） |
| `trpg-server/tools/location.py` | 玩家移动（update_location） |
| `trpg-server/tools/time_weather.py` | 时间/天气手动工具 |
| `trpg-server/tools/weather_system.py` | 天气查表系统 |
| `trpg-server/tools/event_dice.py` | 日常/旅途骰子 |
| `trpg-server/tools/explore.py` | 探索足迹 |
| `trpg-server/tools/state_manager.py` | 游戏状态统一读写层（state 单例） |
| `trpg-server/tools/file_tools.py` | 文件工具（禁写游戏数据目录） |
| `trpg-server/tools/游戏数据/*.json` | 基本信息 / 足迹 / 混乱度 |
| `TODO.md` | 待办规划（战斗/小游戏/音乐/结构/属性） |
| `trpg-client/src/in-game/Map.tsx` | 地图容器 + 红点 + /explored |
| `trpg-client/src/in-game/ClickableLayer.tsx` | 迷雾过滤 + 缓存 + 图标层 |
| `trpg-client/vite.config.ts` | 静态资源缓存头 |
| `trpg-map/draw_tiles/STATUS.md` | 地图生成细节（原状态文件） |
| `trpg-world/主持人/*.md` | 主持人规则（天气/骰子/世界观等） |
