# STATUS.md — 项目交接状态

> **快速入口**：先读本文件了解全局。
> - 架构决策与理由 → `ARCHITECTURE.md`
> - 待办规划 → `TODO.md`
> - 地图生成细节 → `trpg-map/draw_tiles/STATUS.md`

最后更新：记忆层已改为**两级**（动态档案为主 + §10 超 20 条 LRU→`char_memory`）；新增**地点见闻**（`place_notes`）与**方位注入**（八方位/城区方位）；前端**去掉 `data/`**、势力/设置改由后端供，并新增**前情回顾加载**（`GET /recap`）；**难度设置**（`难度设置.json`）与**归隐退出**；`游戏数据`/`天气数据`/`归档存档` 已从 `tools/` 搬到 `trpg-server/` 同级；过程日志统一叫 `current.jsonl`。总纲第 5 条 **「硬事实由代码裁决」** 继续贯穿（时间/距离/方位/城内城外/骰值）。

> ⚠️ **交接必读（第十二节）**：如果你是从一份旧会话接手，先看第十二节「当前进度与下一步」；
> 并注意：`trpg-server` 的代码改动**必须重启后端**才生效（改规则 md 则免重启）。

---

## 一、项目结构

| 目录 | 作用 |
|------|------|
| `trpg-map/` | 地图生成（`draw_tiles/`：世界生成器 + 瓦片 + 空间库） |
| `trpg-server/` | Flask 后端（大模型主持人 + 工具 + 小模型世界推演） |
| `trpg-client/` | React + Leaflet 前端（游戏界面 + 地图） |
| `trpg-world/` | 世界观文档（主持人规则 / 江湖势力 / 角色档案 / 世界推演） |
| `trpg-db/` | chroma 记忆库 + `init_GM_DB.py` |
| `ARCHITECTURE.md` | 架构决策记录 |
| `TODO.md` | 待办规划 |

---

## 二、后端架构（trpg-server）

```
main.py            bootstrap + 路由（薄，不再写工具循环）
engine.py          GameSession（history + current.jsonl + 开局快照）
                   TurnRunner（回合：LLM↔工具循环、状态现拼、事件流）
save_pipeline.py   POST /save 收尾管线（蒸馏→誊写→归档→重置）
llm.py             大模型客户端（DeepSeek）：send_messages(游戏 32 工具) + complete(无工具补全)
tools/registry.py  工具 schema + 实现的**单一真相源**（34 个：游戏 32 + 存档 2；存档专用的不发给游戏 GM）
tools/state_manager.py  trpg-server/游戏数据 的统一读写（state 单例）
tools/mem_store.py  chroma 访问层（懒加载）
tools/ui_events.py  工具→前端的 UI 事件旁路
tools/small_model.py  本地小模型 Qwen3-4B 封装
tools/ui_sim.py       小模型 UI 事件（背景 bg / 音乐 music）
tools/money.py       金钱：直接落账（modify_money 直接改钱）
tools/map_query.py  空间库查询 + city_context（城内/外、距城墙、最近城门）
tools/world_state.py  世界状态读写（游标/宏观/定时线/人物线程）
tools/world_sim.py    单日世界推演
tools/world_worker.py 异步推演 worker
tools/character_archive.py  角色动态档案写入 + §10 LRU 淘汰（update_character_archive）
tools/get_character.py      NPC 登场读档（静态 §1–§8 + 动态 §9–§13）
tools/factions.py           玩家可见势力（读 trpg-world/势力介绍.json）
tools/difficulty_settings.py  游戏设置（难度；trpg-server/游戏数据/难度设置.json）
tools/recap.py              前情回顾（大模型浓缩 + 小模型选 bg/音乐）
```

### 核心机制

- **history 只存纯叙事**；状态（`游戏数据/*.json`）在**每次 LLM 调用时现拼**，放 messages 末尾，只出现一份、永远最新。
- **过程日志**：`sessions/current.jsonl` 每轮追加（唯一"边玩边写"）；崩溃后可恢复。
- **统一事件流**：后端→前端只有一条契约 —— 叙事指令（`chat`/`narration`）+ UI 事件（`type:"ui"` 旁路）。
- **IC / OOC**：`POST /action` 带 `mode`（`action`=角色行动 / `gm`=对主持人说）；OOC 行存档时标 `梁峰（场外）`、**不蒸馏**。
- **模型分工**：大模型 = 叙事；小模型 = UI 事件 + off-screen 世界推演。
- **硬事实由代码裁决**（总纲第 5 条）：时间 / 距离 / 方位 / 城内城外 / 骰值由代码算并注入，模型只渲染、不臆断。
- **输入四模式**（`POST /action` 的 `mode`）：`action` 行动 / `say` 对 NPC 的台词 / `gm` 场外话 / `continue` 继续（`ke` 刻数）。
- **金钱直接落账**：`modify_money` **直接改钱**（增加/减少）；余额不足整笔拒绝。无确认环节、无账本。
- **账目已删 / 足迹不进 LLM**：`snapshot_state()` 排除 `足迹`（前端 `/state` 仍可读）。
- **世界状态裁剪**：人物线程按小模型的 `纳入上下文`（离玩家远近）裁剪后才进大模型；存储全量（`context_view()`）。
- **记忆两库**：`gm_memory`（客观，只增）/ `char_memory`（主观，必带 owner）；**id 由代码分配**。**主观近记忆先进动态档案**（`update_character_archive`），`char_memory` 只在动态档案溢出时由 LRU 写入。
- **存档 = 结束本局**：存档（提交）/ 放弃本轮（快照回滚）/ 中途退出（续玩）。

---

## 三、路由

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/location` | 玩家坐标 |
| GET | `/explored` | 玩家坐标 + 足迹 + 解锁半径（顺带记足迹） |
| GET | `/state` | 玩家真实状态（金钱/状态/背包/属性/基本信息） |
| GET | `/factions` | 玩家可见势力条目（画廊用，数据源 `trpg-world/势力介绍.json`） |
| GET | `/settings` | 游戏设置（难度；数据源 `游戏数据/难度设置.json`） |
| POST | `/settings` | 修改设置 `{"难度":"轻松|普通|困难|硬核"}` |
| GET | `/recap` | 前情回顾（≤10 段 narration + 最后一幕 bg/音乐；进入游戏前的加载） |
| GET | `/history` | 本局历史 `{active, lines, tail}`（面板 + 续玩） |
| POST | `/action` | 游戏主循环 `{input, mode, ke?}` → 事件流（`mode`：`action` 角色行动 / `say` 对 NPC 说的台词 / `gm` 场外话 / `continue` 继续（`ke` 刻数，0=只看信息）） |
| POST | `/save` | 存档收尾管线（蒸馏→誊写→归档→重置） |
| POST | `/abandon` | 放弃本轮（回滚玩家状态 + 世界状态，丢弃本局） |

---

## 四、工具清单（游戏中 32 个，`tools/registry.py`；另 2 个存档专用 = 共 34）

- **金钱/背包**：`modify_money` `get_money` `modify_item` `add_item` `remove_item` `get_inventory`
- **状态/属性**：`modify_hunger` `modify_health` `modify_injury` `modify_hp` `modify_tp` `get_state` `get_ability`
- **移动/时间/天气**：`update_location` `update_time` `update_weather` `get_weather`
- **骰子**：`roll_dice` `daily_event_dice` `travel_event_dice`
- **记忆库**：`DB_query_tool` `DB_add_and_update_tool` `DB_query_tool_in_saving`
- **地图查询**：`query_nearby` `query_place` `list_map_kinds`（`update_place_note` 为存档专用，游戏中不可见）
- **人物/表情**：`get_character` `check_expression`
- **文件（调试用，上线删）**：`list_directory` `read_file` `write_file` `edit_file`

> 新增工具：在 `registry.py` 的 `_ENTRIES` 加一行即可，不必再改 `llm.py` / `main.py`。
>
> **存档专用（游戏中的 GM 不可见，只在存档蒸馏回合下发）**：`update_character_archive`（角色档案）、`update_place_note`（地点见闻）。

---

## 五、数据与存档

```
trpg-server/游戏数据/              ← 与 tools/ 同级
    基本信息.json   人物 / 时间 / 位置(经纬度·区域·在城内/距城墙/最近城门/城区方位) / 天气
    状态.json       生命 / 精力 / 饥饿 / 伤势 / 健康
    背包.json       物品
    属性.json       基础属性 + 五行剑（只读，待写接口）
    金钱.json       金钱
    混乱度.json     0–100（骰子修正）
    难度设置.json   难度（轻松/普通/困难/硬核）——随状态现拼每轮发给 LLM
    足迹.json       探索足迹
    游戏存档.md     上一局逐字叙事（开局读作前情；存档时由代码覆盖）
    世界状态.json   世界推演（游标/宏观/定时线/人物线程）—— 首次推演时生成
trpg-server/天气数据/              ← weather_system 读取（4 区、每区 366 天）
    东部城市.json / 北部城市.json / 南部城市.json / 西部城市.json
trpg-server/归档存档/              ← 存档时归档的逐字叙事
    <起>~<止> 存档.md
trpg-server/sessions/           （.gitignore）
    current.jsonl         本局过程日志（每轮一行）
    run_start_state.json  本局开局快照（放弃本轮回滚用）
```

`游戏数据/` 是**领域自有存储区**：禁止通用文件工具写，只能走专用接口 + `state_manager`。

---

## 六、前端（trpg-client/src）

- **顶层按钮**：主持人 / 行动 / **说话**（对 NPC 的台词）/ **继续**（时间流逝、世界推进）/ 历史记录 / **数据**（弹金钱/背包/属性/状态）。
- **「菜单」**（左侧滑出）：存档游戏 / 放弃本轮 / 地图 / 势力 / 返回主菜单。
- **背景**：由 UI 事件 `kind:"bg"` 控制（`in-game/background.ts` 负责 地点+时辰→图），`GameScene` 只收 `background` prop。
- **音乐**：由 UI 事件 `kind:"music"` 控制（`in-game/music.ts`，曲库=`assets/音乐/*.mp3`，**只放一遍不循环**，播完即停；离开游戏停止）。
- **历史面板 / 续玩**：读 `GET /history`；不再有前端 `historyLog`。
- **地图**：`Map.tsx` 请求 `/explored`；`ClickableLayer.tsx` 探索迷雾 + IndexedDB 缓存 + 可视范围图标层。
- **势力画廊**：读 `GET /factions`（数据源 `trpg-world/势力介绍.json`）；**前端已无 `data/` 文件夹**。
- **环境设定 / 归隐山林**：「环境设定」调**难度**（`GET`/`POST /settings` → `游戏数据/难度设置.json`，每轮发给 LLM）；「归隐山林」直接退出（`window.close()`，无效时显示退出屏）。
- **前情回顾**：点「继续旅途」→ `GET /recap` → 主页面加载（主题曲继续）→ 加载完**直接进游戏**；前情提要在 **in game 内**点击推进（`GameScene`），播完进正常游戏；选定段落/bg/音乐经 `App` 传入 `Gaming`（`initialRecap`/`initialBg`/`initialMusic`）；无存档则跳过。

---

## 七、世界观文档（trpg-world）

- `主持人/`：`总览.md`（输出格式/铁律）、`世界.md`（时代背景）、`可能性骰.md`、`特定人物.md`、`天气系统.md`、`日常骰子事件.md`、`旅途骰子事件.md` → 由 `folder_to_prompt` 全量注入。
- `存档流程.md`：存档蒸馏规则（两库、「场外」不蒸馏、add 不编 id）。
- `世界推演/`：`宏观时间线.json`（19 条，1220-02~1224-09，参照南宋嘉定年间）+ `推演规则.md`（小模型提示）。
- `音乐清单.md`：**叙事**曲目（`曲名｜绑定：说明`）→ 供叙事小模型选背景音乐。
- `战斗音乐清单.md`：**战斗**曲目 → 只给战斗系统（叙事候选看不到）。
- `场景清单.md`：场景名 → 适用情境说明（供小模型选背景图）。
- `场景映射.md`：地点类型（`ancient_kind`）→ 允许的背景场景（约束小模型，防误判）。
- `角色静态档案/`：55 个人物正典档案。
- `角色动态档案/{活跃,不活跃}/`：世界推演的活跃名单（存档时**自动写入**，也支持手动放文件）。**所有角色地位平等**：有实质互动即建档（静态+动态），与预设角色同等。
- `江湖势力/`：13 份势力正典（含剧透，只进 LLM）。

---

## 八、地图（trpg-map/draw_tiles）

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
- 图标 `trpg-client/public/mapicons/*.png`（53 张；manifest 46 键仅 `ward` 未画，决定不画）
- 民居瓦片隐藏、数据留 JSON/DB；城门=主街穿墙处。
- **地点见闻**：`features.description`（静态，建库时带）+ `place_notes` 表（动态，**重建不删**）；`query_nearby`/`query_place` 合并返回。**存档时**由 `update_place_note`（存档专用工具）写入。

---

## 九、记忆库（trpg-db）

- `chroma_db/`：两个 collection `gm_memory` / `char_memory`，**当前为空结构**。
- `init_GM_DB.py`：
  ```bash
  python init_GM_DB.py            # 建结构（不写入任何内容）
  python init_GM_DB.py --reset    # 删库重建（彻底清空）
  ```
  不需要 LM Studio。**别在跑服务时用 DB Browser 打开它**（会卡死，见下）。

---

## 十、常用命令

```bash
# ---- 记忆库（trpg-db 下）----
python init_GM_DB.py [--reset]

# ---- 后端（trpg-server 下）----
python main.py                       # 启动 Flask(5000)

# ---- 前端（trpg-client 下）----
npm run dev

# ---- 地图（trpg-map/draw_tiles 下）----
python build_world.py                # 重新生成世界
python export_clickable.py           # 导出点击层 + 图标清单
python db/create_spatial_db.py       # 重建空间库
python tilegen/generate_tiles.py     # 重生成瓦片（10–20 分钟）
cp -r tiles/{11..16} ../../trpg-client/public/tiles/
```

**前置**：LM Studio 需加载两个模型 —— `Qwen/Qwen3-Embedding-0.6B`（记忆检索）+ `qwen/qwen3-4b-2507`（世界推演）。
可用 `TRPG_WORLD_SIM=0` 关闭世界推演。

---

## 十一、坑 / 注意事项

1. **别用外部工具（DB Browser 等）打开 `chroma_db`**：chromadb 的 Rust 内核启动要拿写锁，被占会**静默卡死、无任何输出**。
2. **chroma 的 `delete()` 是逻辑删除**：`count()` 归 0，但写前日志/向量段仍有痕迹；彻底清空只能 `init_GM_DB.py --reset`。
3. **时间必须权威**：任何"过夜/赶路"叙述必须调 `update_time`（已写入 `总览.md` 通用规则 10）；时间粒度：**十二时辰 × 每时辰 8 刻**（1 刻 ≈ 15 分钟）。`engine` 另有机械兜底（漏调则下一轮提醒）。
4. **`file_tools` 仅调试用**，正式上线删除；`游戏数据/` 只能走专用接口。
5. **活跃人物名单**：世界推演只扫 `角色动态档案/活跃/`；存档时由 `save_pipeline` 自动写入（`world_state.promote_active`）——**本局所有有实质互动的 NPC**（预设或新登场，地位平等）：动态档案由 `update_character_archive` 写、静态档案由 `ensure_static` 兼底；也支持手动放文件。
6. **规则文件热更新**：`engine._rules_text()` 按文件夹 mtime 热读 `trpg-world/主持人/*.md`，改规则**立即生效、无需重启**；但改**代码**（`*.py` / 前端 `*.ts`）仍需重启对应进程。
7. **`history` 无滑动窗口**：长局会让每轮携带的 history 变长（推高 token 花费 / 首字延迟）；用户表示上下文足够大，**暂缓**（TODO 第十一节）。
8. **金钱直接落账**：`modify_money` 直接改 `金钱.json`（余额不足整笔拒绝）；**已去掉请款/确认与账本**。
9. **足迹不发 LLM**：只存盘。
10. **只跑一个后端**：开两个 `python main.py` 会抢 5000 端口 / 一个跑旧代码旧路径，表现为"改了没生效 / 有的对有的不对"。
11. **数据目录在 `trpg-server/` 下**：`游戏数据` / `天气数据` / `归档存档` 与 `tools/` 同级（**不在 `tools/` 里**）；路径均由 `__file__` 绝对解析。

---

## 十二、交接：当前进度与下一步

### 本轮做了什么（最近一次开发）
- **UI 事件管线 ⑧**：bg/music 全由小模型选（`ui_sim.py`）——场景按 `场景映射.md` 地点类型约束；音乐分 `音乐清单.md`（叙事）/`战斗音乐清单.md`（战斗）双清单；专属曲按 `曲名｜绑定` 触发；默认底色曲 `山中好岁月`；**只放一遍不循环**；换曲门槛=换背景或当前曲失效。
- **时间加「刻」**（1 时辰=8 刻）；「继续」按钮可选 **0–4 刻**（0=不推进时间、只看信息）。
- **金钱直接落账**（去掉请款/确认环节与账本；`modify_money` 直接改钱）。
- **修 `query_nearby` 返回点**：改为几何体上**离查询点最近的点**（原为代表点，会让"跳窗"瞬移 184 米）。
- **台词回合时间护栏**：`say`/`gm` 模式下 `update_time` 最多推进 2 刻，推进时辰 / 改日期一律驳回（规则 12 机械兼底）。
- **动态档案为主 + LRU**：新增存档专用工具 `update_character_archive`（按模板写 §9–§13）；§10 超 20 条淘汰最旧→`char_memory`；存档不再直写 `char_memory`。
- **地点见闻**：`features.description`（静态）+ `place_notes` 表（动态，重建不丢）；新工具 `update_place_note`（**存档专用**，存档时蒸馏写入）；`query_nearby`/`query_place` 合并返回。
- **行动 vs 台词**：新增 `say` 模式（「说话」按钮）。
- **城内/城外**：`map_query.city_context` 判定；`update_location` 返回距离/耗时/城门/过墙提示。
- **规则热更新**；**总纲第 5 条「硬事实由代码裁决」**；疏漏审计与修复（见 ARCHITECTURE 实现记录）。
- **前端去 `data/` + 势力后端化**：删 `src/data/`；新增 `trpg-world/势力介绍.json` + `tools/factions.py` + `GET /factions`；画廊改 fetch。
- **前情回顾加载**：`tools/recap.py` + `GET /recap`；菜单「继续旅途」→ 加载/回顾 → 进游戏（`GameScene.onFinish` + `initialBg/initialMusic`）。
- **方位注入**：`map_query.bearing_name`/`distance_m`；`query_place`/`query_nearby` 带 `方位`+`距玩家`；`city_context.城区方位`；`update_location.移动方位`。修 GM 把「东北水门」说成「西水关」。
- **数据目录搬迁**：`tools/` 下的 `游戏数据` / `天气数据` / `归档存档` → `trpg-server/` 同级（代码路径全部改基于 `__file__`）；过程日志统一称 `current.jsonl`。
- **难度设置 + 归隐退出**：`tools/difficulty_settings.py` + `GET`/`POST /settings`；难度及各级含义存 `游戏数据/难度设置.json`（每轮发给 LLM）；「归隐山林」直接退出。

### ⚠️ 重启后才生效
`trpg-server` 代码（本轮）：`main.py`（新路由 `/settings`）/ `tools/difficulty_settings.py` / `tools/recap.py` / `tools/factions.py` / `tools/state_manager.py` / `tools/map_query.py` / `tools/location.py` / `tools/weather_system.py` / `tools/file_tools.py` / `engine.py` / `save_pipeline.py` / `llm.py`；以及前端（`App` / `Menu` / `GameController` / `GameScene` / css）。
> ⚠️ **只跑一个 `python main.py`**（开了两个会抢 5000 端口 / 一个跑旧代码，表现为"改了没生效"）。

### 下一步优先级（建议）
1. **大跨度时间流逝规则**：`总览.md` 补"住店只是订房，不等于睡到天亮"（规则热更免重启）。**很小**。
2. **§8.4 点选行程耗时**（以「刻」为单位、速度取决于体力/轻功）。
3. **属性养成**（`update_ability` / `train_skill`）——轻功前置。
4. **战斗系统（§四）**（建议先写数值设计再写码）。
5. 大工程（均**未动**）：**§九 信息边界（两段式调用）**、**§十 知识库层**。

> 暂缓：`history` 滑动窗口 / 摘要 —— 用户称模型上下文足够大，**暂不需要**（长局/成本敏感时再评估）。

### 未动的大块（对应 TODO 编号）
⑧剩余 ui_event 协议细化（music/minigame 已可）；⑨ 战斗 / 小游戏；属性养成；日历（农历）；地图扩展（`type` / 地域特色 / 世界地图 / 补史实城门）；点选行程（§8.4）；信息边界；知识库。

---

## 十三、关键文件速查

| 文件 | 用途 |
|------|------|
| `trpg-server/engine.py` | 引擎：会话 + 回合循环 + 状态现拼 + 过程日志 |
| `trpg-server/save_pipeline.py` | 存档收尾管线 |
| `trpg-server/main.py` | 路由 + bootstrap |
| `trpg-server/llm.py` | 大模型客户端 |
| `trpg-server/tools/registry.py` | 工具单一注册表（34：游戏 32 + 存档 2） |
| `trpg-server/tools/state_manager.py` | 游戏数据统一读写层 |
| `trpg-server/tools/mem_store.py` | chroma 访问层（懒加载） |
| `trpg-server/tools/character_archive.py` | 角色动态档案写入 + §10 LRU 淘汰 |
| `trpg-server/tools/get_character.py` | NPC 登场读档（静态 §1–§8 + 动态 §9–§13） |
| `trpg-server/tools/world_state.py` | 世界状态读写 + 活跃名单 + promote_active |
| `trpg-server/tools/ui_sim.py` | 小模型选背景/音乐 |
| `trpg-server/tools/factions.py` | 玩家可见势力（读 `trpg-world/势力介绍.json`） |
| `trpg-server/tools/difficulty_settings.py` | 游戏设置（难度；读`游戏数据/难度设置.json`） |
| `trpg-server/tools/recap.py` | 前情回顾（大模型浓缩 + 小模型选 bg/音乐） |
| `trpg-server/tools/world_sim.py` / `world_worker.py` | 世界推演 / 异步 worker |
| `trpg-server/游戏数据/` | 游戏状态 JSON + 世界状态（与 `tools/` 同级） |
| `trpg-server/sessions/` | 过程日志 + 开局快照 |
| `trpg-client/src/in-game/GameController.tsx` | 游戏主界面（按钮/浮层/事件分流） |
| `trpg-client/src/in-game/Map.tsx` / `ClickableLayer.tsx` | 地图 + 探索迷雾 |
| `trpg-map/draw_tiles/STATUS.md` | 地图生成细节 |
| `ARCHITECTURE.md` / `TODO.md` | 架构决策 / 待办 |

---

## 十四、数据链总览

> 总原则：**前端不存任何游戏内容**——势力 / 状态 / 历史 / 前情 / 事件流一律向后端请求；
> 后端从 `trpg-world`（正典·玩家可见数据）、`游戏数据/`（实时状态）、`sessions/`（过程日志）、
> chroma（长期记忆）、`map_spatial.db`（空间库）取。**硬事实由代码裁决**（总纲第 5 条）。

### 14.1 势力画廊（前端零内容）

```
trpg-world/势力介绍.json          ← 玩家可见源（已剔除剧透）
      │ tools/factions.py · list_factions()
      ▼
后端 GET /factions
      │ fetch → useMemo
      ▼
前端 GameController → AccordionGallery
（GM 正典 trpg-world/江湖势力/*.md 含剧透，不走此路）
```

### 14.2 前情回顾（进游戏前）

```
【存档时】save_pipeline ──写──► 游戏数据/游戏存档.md（逐字叙事）

【点「继续旅途」】前端 Menu ── GET /recap ──► tools/recap.py
     ├─ 读 游戏数据/游戏存档.md
     ├─ 大模型 llm.complete()          ─► segments（≤10 段 narration）
     └─ 小模型 ui_sim.generate(末段, 当前地点) ─► bg / 音乐
 ◄── {has_recap, segments, bg, music}
      │ onStartGame(...)
      ▼
 App.startData ─► Gaming(initialRecap / initialBg / initialMusic)
      │ 主题曲停（Menu 卸载）· 播所选音乐 · 背景 = 所选 bg
      ▼
 in game：GameScene 逐段点击推进（onFinish）→ 播完转正常游戏
```

### 14.3 游戏主循环（每回合）

```
玩家输入 POST /action {input, mode, ke}
   ▼ engine.TurnRunner
   ├─ 状态现拼 state.snapshot()（游戏数据/*.json，排除 足迹/账目）
   ├─ 大模型 ↔ 工具循环（registry：游戏 32 工具）
   └─ 小模型 ui_sim 选 bg / 音乐
   ▼ 统一事件流 [ ui 事件… , chat / narration… ]
前端 GameController：ui → 旁路（背景/音乐/…）；chat/narration → GameScene
```

### 14.4 状态 / 记忆 / 档案 / 见闻

```
读：GET /state   ◄─ state.snapshot()（游戏数据/*.json）
    GET /history ◄─ sessions/current.jsonl

存档：POST /save → save_pipeline
   ├─ 大模型蒸馏 → gm_memory（客观）
   ├─ update_character_archive → 角色动态档案 §9–§13
   │        └─ LRU：§10 超 20 条 → char_memory（冷库）
   ├─ update_place_note → 空间库 place_notes（地点见闻）
   └─ 代码：誊写 游戏存档.md + 归档 + 重置会话
```

### 14.5 模型分工一览

| 产物 | 大模型（DeepSeek） | 小模型（Qwen3-4B） | 代码 |
|---|:--:|:--:|:--:|
| 回合叙事 chat / narration | ✅ | | |
| 背景 bg / 音乐 music | | ✅ | |
| 世界推演（离散采样） | | ✅ | |
| 前情回顾文字 | ✅ | | |
| 前情回顾 bg / 音乐 | | ✅ | |
| 存档蒸馏（gm/char/档案/见闻） | ✅ | | |
| 距离 / 时间 / 方位 / 骰值 / 状态 | | | ✅ |

### 14.6 设置（难度）

```
菜单「环境设定」 ── GET/POST /settings ──► tools/difficulty_settings.py ──► 游戏数据/难度设置.json
      │
      └─（随「状态现拼」每轮注入状态块）──► 大模型按难度调整「世界如何回应」
                                             （不改硬事实：距离/时间/骰值仍由代码算）
```
