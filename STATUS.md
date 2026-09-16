# STATUS.md — 项目交接状态

> **快速入口**：先读本文件了解全局。
> - 架构决策与理由 → `ARCHITECTURE.md`
> - 待办规划 → `TODO.md`
> - 地图生成细节 → `trpg-map/draw_tiles/STATUS.md`

最后更新：**连续时钟 v0.2 全套 + 三模式状态机**——`tools/game_clock.py`（单一「游戏秒」标量 + 三态 + **南宋全年号** + 战斗折算）、`tools/time_flow.py`（**跨时辰扣精力/熬夜、跨日切天气+世界推演、`sleep` 工具**）、`tools/derived.py`（体力→生命上限、內力→精力上限）、前端**古钟 HUD**（`Clock.tsx`/`useGameClock.ts`，rAF 插值）、**三模式状态机**（探索=整屏 zoom18 地图 + **WASD** 走；叙事=对话+立绘+古钟；战斗=战棋；进叙事由玩家输入、退叙事由主持人 `resume_exploration` 裁定）、宏观时间线扩到 **89 条（1220~1279）**。修：模拟战泄漏、`file_tools` 摘除、`state_manager` 并发写崩溃、背景误判乡村。详见 `README.md`、`ARCHITECTURE.md` **第十四/十五节**。此前：**战斗视觉/地形/AOE 增强**（等轴测棋盘 + 实体系统 + 地形阻挡 + BGM 小模型选曲 + AOE 选格）——战斗系统 v0.1（网格 n vs n · 阶段驱动 · 思路判定 · 模拟战斗 · 战斗 BGM；见 `trpg-world/战斗系统.md` / `ARCHITECTURE.md` 第十三节）。更早：记忆层改为**两级**（动态档案为主 + §10 超 20 条 LRU→`char_memory`）；新增**地点见闻**（`place_notes`）与**方位注入**（八方位/城区方位）；前端**去掉 `data/`**、势力/设置改由后端供，并新增**前情回顾加载**（`GET /recap`）；**难度设置**（`难度设置.json`）与**归隐退出**；`游戏数据`/`天气数据`/`归档存档` 已从 `tools/` 搬到 `trpg-server/` 同级；过程日志统一叫 `current.jsonl`。总纲第 5 条 **「硬事实由代码裁决」** 继续贯穿（时间/距离/方位/城内城外/骰值）。

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
llm.py             大模型客户端（DeepSeek）：send_messages(游戏 31 工具) + complete / complete_json
tools/registry.py  工具 schema + 实现的**单一真相源**（`_ENTRIES` 37；LLM 可见 33：游戏 31 + 存档 2；含 4 个默认禁用的调试文件工具）
tools/state_manager.py  trpg-server/游戏数据 的统一读写（state 单例）
tools/mem_store.py  chroma 访问层（懒加载）
tools/ui_events.py  工具→前端的 UI 事件旁路
tools/small_model.py  本地小模型 Qwen3-4B 封装（单次 10s 硬超时，超时 cancel 生成）
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
tools/battle.py             战斗数值核心（网格/6动作/命中伤害/五行/武器/Buff/胜负，纯代码）
tools/battle_tactics.py     NPC 代码战术层（L2 枚举+打分 + L3 一回合前瞻）
tools/battle_runner.py      战斗阶段驱动（回合阶段机 + 战局快照）
tools/battle_ai.py          战斗 AI（思路判定路由小/大模型 + 阵营决策 + 降级）
tools/battle_session.py     当前战斗单例 + 梯度查表 + 结束写回状态
tools/battle_settings.py    战斗设置（思路判定模型，存 sessions/battle_settings.json）
tools/game_clock.py   连续时钟（单一标量「游戏秒」+ 三态 + 年号/干支；唯一时间真相源）
tools/time_flow.py    时间流逝的后果（跨时辰扣精力 / 跨日切天气+推演 / sleep 恢复）
tools/derived.py      派生上限：体力→生命上限、內力→精力上限（属性.json 为真相源）
tools/modes.py        模式切换工具（resume_exploration：叙事→探索）
```

### 核心机制

- **history 只存纯叙事**；状态（`游戏数据/*.json`）在**每次 LLM 调用时现拼**，放 messages 末尾，只出现一份、永远最新。
- **过程日志**：`sessions/current.jsonl` 每轮追加（唯一"边玩边写"）；崩溃后可恢复。
- **统一事件流**：后端→前端只有一条契约 —— 叙事指令（`chat`/`narration`）+ UI 事件（`type:"ui"` 旁路）。
- **IC / OOC**：`POST /action` 带 `mode`（`action`=角色行动 / `gm`=对主持人说）；OOC 行存档时标 `梁峰（场外）`、**不蒸馏**。
- **模型分工**：大模型 = 叙事；小模型 = UI 事件 + off-screen 世界推演。
- **时间由时钟裁决**：`游戏秒` 单一标量；探索/叙事实时流动，`pause/resume/accrue` 三态；
  发给 LLM 的是**刻级** `基本信息.时间`（含 `纪年`/`干支`），前端拿 `/clock` 锚点本地插值。
- **时间流逝有后果**：`tools/time_flow.pump()`（`/clock`、`/state`、`/action` 时）——跨时辰扣精力
  （夜时辰熬夜更狠）、跨日切天气 + 触发世界推演；工具 `sleep` 推进时间并恢复精力。
- **上一轮状态 + 当前状态**：`state_stack = deque(maxlen=2)`（**长度上限 2、不累积**）——每轮末
  `append(engine.state_dict())`；下一轮把**栈顶**（= 上一轮）与现拼的「当前状态」一起发给 LLM。
- **三模式状态机**：`explore`（整屏地图 + WASD）/ `narrative`（对话+立绘+古钟）/ `battle`（战棋）；
  进叙事由玩家输入、退叙事由主持人裁定（`resume_exploration`）。
- **上限是派生值**：`属性.json` 是真相源（**体力 = 生命值上限，內力 = 精力值上限**）；
  `状态.json` 的上限是投影，由 `derived.sync()` 对齐（漂移时以属性为准，上限变小则夹取当前值）。
  故 `sleep` 的恢复量 = **內力 ÷ 睡眠回满时辰**，养成提高內力后自动变强。
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
| GET | `/clock` | **连续时钟锚点** `{游戏秒, 服务端墙钟, 状态, 倍率, 显示, 纪年, 干支}`（前端本地插值驱动古钟；顺带 `time_flow.pump()`） |
| POST | `/clock/pause` · `/clock/resume` | 前端暂停 / 恢复时钟（菜单、历史面板、窗口失焦） |
| POST | `/action` | 游戏主循环 `{input, mode, ke?, 坐标?, 上一坐标?}` → 事件流（`坐标` = 探索模式光标位置；更新位置 + 注入【移动】提醒） |
| POST | `/save` | 存档收尾管线（蒸馏→誊写→归档→重置） |
| POST | `/abandon` | 放弃本轮（回滚玩家状态 + 世界状态，丢弃本局） |
| GET | `/battle/state` | 当前战斗状态（无战斗 `{active:false}`） |
| POST | `/battle/action` | 战斗提交一个动作 `{动作,目标,招式,目标格,思路}` → 推进到下一次轮询 |
| GET/POST | `/battle/settings` | 思路判定模型（小/大模型，存 `sessions/battle_settings.json`） |
| GET | `/battle/roster` | 模拟战斗可选名单（55 人，来自 `武力排名.md`） |
| POST | `/battle/sim` | 模拟开局 `{友方,敌人}`（不回写存档） |
| POST | `/battle/abort` | 中止当前战斗 |

---

## 四、工具清单（游戏中 31 个，`tools/registry.py`；另 2 个存档专用 = LLM 可见 33；`_ENTRIES` 共 37，含 4 个默认禁用的调试文件工具）

- **金钱/背包**：`modify_money` `get_money` `modify_item` `add_item` `remove_item` `get_inventory`
- **状态/属性**：`modify_hunger` `modify_health` `modify_injury` `modify_hp` `modify_tp` `get_state` `get_ability`
- **移动/时间/天气**：`update_location` `update_time` `sleep`（睡觉推进+恢复精力） `update_weather` `get_weather`
- **模式**：`resume_exploration`（主持人裁定：叙事→探索）
- **骰子**：`roll_dice` `daily_event_dice` `travel_event_dice`
- **战斗**：`start_battle`（GM 判定开战 → 战斗界面）
- **记忆库**：`DB_query_tool` `DB_add_and_update_tool` `DB_query_tool_in_saving`
- **地图查询**：`query_nearby` `query_place` `list_map_kinds`（`update_place_note` 为存档专用，游戏中不可见）
- **人物/表情**：`get_character` `check_expression`
- **文件（已默认禁用，不下发给 LLM、也不可被调用；代码保留，`TRPG_FILE_TOOLS=1` 可临时启用）**：`list_directory` `read_file` `write_file` `edit_file`

> 新增工具：在 `registry.py` 的 `_ENTRIES` 加一行即可，不必再改 `llm.py` / `main.py`。
>
> **存档专用（游戏中的 GM 不可见，只在存档蒸馏回合下发）**：`update_character_archive`（角色档案）、`update_place_note`（地点见闻）。

---

## 五、数据与存档

```
trpg-server/时间影响.json            ← 时间流逝的数值参数（热改免重启）
    每时辰精力{昼,夜} / 睡眠回满时辰 / 夜时辰
trpg-server/游戏数据/              ← 与 tools/ 同级
    基本信息.json   人物 / **时间(日期·时辰·刻·纪年·干支)** / 位置(经纬度·区域·在城内/距城墙/最近城门/城区方位) / 天气
    时钟.json       **连续时钟真相源**（`{游戏秒, 状态}`）——不进 LLM 上下文
    状态.json       生命 / 精力 / 饥饿 / 伤势 / 健康（上限由 `属性` 派生）
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
    battle_settings.json  战斗设置（思路判定模型；模拟战斗也用它）
```

`游戏数据/` 是**领域自有存储区**：禁止通用文件工具写，只能走专用接口 + `state_manager`。

---

## 六、前端（trpg-client/src）

- **顶层按钮**：主持人 / 行动 / **说话**（对 NPC 的台词）/ **继续**（时间流逝、世界推进）/ 历史记录 / **数据**（弹金钱/背包/属性/状态）。
- **「菜单」**（左侧滑出）：存档游戏 / 放弃本轮 / 地图 / 势力 / 返回主菜单。
- **背景**：由 UI 事件 `kind:"bg"` 控制（`in-game/background.ts` 负责 地点+时辰→图），`GameScene` 只收 `background` prop。
- **音乐**：由 UI 事件 `kind:"music"` 控制（`in-game/music.ts`，曲库=`assets/音乐/*.mp3`，**循环播放**；同名不重启；`track="无"` 或离开游戏时停止）。
- **战斗**：`in-game/battle.tsx` + `styles/Battle.css` —— 10×6 网格 + **实心矩形 token**（阵营配色/名字/血内力条/buff）+ 动作菜单 + 目标点选 + 思路输入框 + 滚动日志 + 顶部**小/大模型开关** + 结算浮层；`GameController` 收 `kind:"battle"` 打开，战斗 BGM 由 `ui_sim.battle_track_for()` 选。
- **模拟战斗**：主菜单「环境设定」里选友军/敌人（`GET /battle/roster`）→ `POST /battle/sim` → 直接开战斗界面（不回写存档）；主页面主题曲自动暂停/恢复。
- **历史面板 / 续玩**：读 `GET /history`；不再有前端 `historyLog`。
- **地图**：`Map.tsx` 请求 `/explored`；`ClickableLayer.tsx` 探索迷雾 + IndexedDB 缓存 + 可视范围图标层。
- **势力画廊**：读 `GET /factions`（数据源 `trpg-world/势力介绍.json`）；**前端已无 `data/` 文件夹**。
- **环境设定 / 归隐山林**：「环境设定」调**难度**（`GET`/`POST /settings` → `游戏数据/难度设置.json`，每轮发给 LLM）；「归隐山林」直接退出（`window.close()`，无效时显示退出屏）。
- **前情回顾**：点「继续旅途」→ `GET /recap` → 主页面加载（主题曲继续）→ 加载完**直接进游戏**；前情提要在 **in game 内**点击推进（`GameScene`），播完进正常游戏；选定段落/bg/音乐经 `App` 传入 `Gaming`（`initialRecap`/`initialBg`/`initialMusic`）；无存档则跳过。

---

## 七、世界观文档（trpg-world）

- `主持人/`：`总览.md`（输出格式/铁律）、`世界.md`（时代背景）、`可能性骰.md`、`特定人物.md`、`天气系统.md`、`日常骰子事件.md`、`旅途骰子事件.md` → 由 `folder_to_prompt` 全量注入。
- `存档流程.md`：存档蒸馏规则（两库、「场外」不蒸馏、add 不编 id）。
- `世界推演/`：`宏观时间线.json`（**89 条，1220-02~1279-02，南宋全程、无空洞年份**）+ `推演规则.md`（小模型提示）。`ensure_timeline` 为**增量合并**（旧存档亦生效）。
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
trpg-map/数据/扬州_OSM精简.json (抽稀后 OSM 14683，勿改)
trpg-map/数据/扬州_布点锚点.json (76 布点锚点，勿改)
        └──► draw_tiles/build_world.py ──► trpg-map/数据/扬州_南宋世界.json (12336 对象)
                                     ├─► export_clickable.py ► 前端 clickable.geojson
                                     ├─► db/create_spatial_db.py ► map_spatial.db
                                     └─► tilegen/generate_tiles.py ► tiles/ (z11–16)
```

> 数据已统一收到 **`trpg-map/数据/`**（源 pbf / 全量 / 精简 / 布点 / 南宋世界），
> 命名约定与血缘见 `trpg-map/数据/README.md`。

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
4. **`file_tools` 已默认禁用**（不下发给 LLM、也不可被调用；代码保留，`TRPG_FILE_TOOLS=1` 可临时启用）；`游戏数据/` 只能走专用接口。
5. **活跃人物名单**：世界推演只扫 `角色动态档案/活跃/`；存档时由 `save_pipeline` 自动写入（`world_state.promote_active`）——**本局所有有实质互动的 NPC**（预设或新登场，地位平等）：动态档案由 `update_character_archive` 写、静态档案由 `ensure_static` 兼底；也支持手动放文件。
6. **规则文件热更新**：`engine._rules_text()` 按文件夹 mtime 热读 `trpg-world/主持人/*.md`，改规则**立即生效、无需重启**；但改**代码**（`*.py` / 前端 `*.ts`）仍需重启对应进程。
7. **`history` 无滑动窗口**：长局会让每轮携带的 history 变长（推高 token 花费 / 首字延迟）；用户表示上下文足够大，**暂缓**（TODO 第十一节）。
8. **金钱直接落账**：`modify_money` 直接改 `金钱.json`（余额不足整笔拒绝）；**已去掉请款/确认与账本**。
9. **足迹不发 LLM**：只存盘。
10. **只跑一个后端**：开两个 `python main.py` 会抢 5000 端口 / 一个跑旧代码旧路径，表现为"改了没生效 / 有的对有的不对"。
11. **数据目录在 `trpg-server/` 下**：`游戏数据` / `天气数据` / `归档存档` 与 `tools/` 同级（**不在 `tools/` 里**）；路径均由 `__file__` 绝对解析。
12. **小模型单次调用有 10s 硬超时**（`tools/small_model.ask_json`）：超时会 `stream.cancel()` **真中断**并返回 None（调用方降级）；可用 `TRPG_SMALL_TIMEOUT` 覆盖。注意 `lmstudio.set_sync_api_timeout()` **不管用**（它只管消息间隔，实测 33s 照样跑完）。
13. **`游戏数据` 文件的并发写**（2026-09-15 实战）：Flask 多线程下，一个线程 `open()` 读某 JSON（Windows 下不共享 delete）、另一线程恰好 `os.replace` 覆盖它 → **`PermissionError: [WinError 5] 拒绝访问`**（实测 `/state` 5xx）。已修：`state_manager` 的 `load`/`save` **用同一把 RLock 串行化**、临时文件名加 pid+线程号、`replace` 失败**重试 6 次**；`clock`/`derived`/`time_flow` 的写盘失败只记日志不抛；`/state`、`/clock` 的副作用包了 `_best_effort`（**永不 500**）。另外：**别用编辑器/数据库工具开着 `游戏数据/*.json`**（外部占用仍会失败，但有重试 + 不崩）。

---

## 十二、交接：当前进度与下一步

### ⭐ 本轮：连续时钟 v0.2 + 三模式状态机

> 蓝图见 `README.md`，架构决策见 `ARCHITECTURE.md` **第十四节（连续时钟）/ 第十五节（三模式）**。

**一句话**：把游戏从“聊天框”改成“**有时间在流动、能走进去的世界**”。
- **时钟是单一标量**（`游戏秒`）驱动一切（时间/年号/睡眠/熬夜/跨日）；
- **三模式**（探索 / 叙事 / 战斗）由前端 `gameMode` 驱动；
- **时间流逝有后果**：跨时辰扣精力（熬夜更狠）、跨日自动切天气 + 推演世界。

（下面是本轮完整记录，按时间倒序追加。）

**已完成（后端内核）**：
- `tools/game_clock.py`：`GameClock` 单例——单一整数「游戏秒」（epoch 1220-01-01 子时初刻）、
  三态 `running`/`paused`/`accruing`、惰性求值（不跑后台线程）、`advance`/`set_civil`、
  `pause`/`resume`（多原因）、`begin_battle`/`end_battle`（1 回合 = 1 游戏分钟）、锚点 + 节流落盘。
- `tools/time_weather.py`：`update_time` **转发**给时钟（推进/设置），常量再导出兼容旧 import。
- `engine.py`：`snapshot_state` 先 `clock.sync_state()` 且**排除 `时钟.json`**；`current_game_time` 用 `clock.render()`；
  `TurnRunner.run` / `run_save` 期间 `pause("turn"/"save")`；快照先落盘时钟、`_restore_snapshot` 后 `clock.reload()`。
- `main.py`：`GET /clock`（锚点）/ `POST /clock/pause` / `POST /clock/resume`。
- 数据：首次导入自动从 `基本信息.时间` 迁移建 `游戏数据/时钟.json`。
- 测试：28 项单元（换算 / 迁移 / 流动 / 暂停 / 投影 / `update_time` 转发 / 战斗折算 / 持久化）全过。

**已完成（前端古钟）**：
- `in-game/useGameClock.ts`（锚点 + rAF 本地插值 + 暂停/恢复 + 全局重同步）、
  `in-game/Clock.tsx`（十二时辰环 + 平滑指针 + 96 刻刻度 + 昼夜日月弧 + 中心时辰字 + 日期）、
  `styles/Clock.css`（青铜/木质配色，位置/层级/尺寸均为 CSS 变量）。
- `GameController`：渲染 `<Clock paused={showHistory} />`；每次 `/action` 后 `requestClockSync()`；历史面板暂停。
- `npm run build` 通过（顺手修 `BattleBoard.tsx` 的 React 19 全局 `JSX` 类型错误）。

**已完成（年号收归后端 + LLM 可见）**：
- `game_clock.ERAS` = **南宋全年号表**（1127 建炎 ~ 1279 祥兴，22 个）+ `era_name` / `ganzhi_year` /
  `cn_number` / `cn_day` / `chinese_date` / `render_era`（重叠年取「起始年最新」，每个年号都有元年；
  超出南宋退回 `公元1220年`）。
- **LLM**：`基本信息.时间` 增 `纪年` / `干支` → 随状态现拼自动注入。
- **前端**：`/clock` 锚点新增 `纪年` / `干支`；删掉前端自备年号表，`Civil` 只留时辰/刻。
- `recap` 改用 `render_era`；测试 38 项全过。

**已完成（宏观时间线扩充）**：
- `宏观时间线.json`：19 条（至 1224-09）→ **89 条（1220-02 ~ 1279-02，南宋全程）**，
  每年至少一条、无空洞年份（蒙金战争 → 端平入洛 → 蒙古南侵 → 襄阳围城 → 临安陷落 → 崖山）。
- `world_sim.ensure_timeline` 改为**增量合并**：作者新增条目按 `(date,text)` 去重补入，
  保留已有「已触发」标记 → **扩充能对旧存档生效且不丢进度**（实测 19→89，标记保留）。
- 已对真实 世界状态.json 完成迁移：定时线 19→89，游标/宏观不变。测试 14 项全过。

**已完成（跨日联动 + 时间影响数值）**：
- `tools/time_flow.py`：`pump()`（跨时辰 → 扣精力，夜时辰熬夜更狠；跨日 → 切当天天气 +
  触发世界推演）；`rest(时辰)`（工具 `sleep`：先结算清醒时段 → 推进 → 按睡眠恢复）。
- `clock.take_crossings()`：全局刻/日游标；首次只对齐不结算（重启/回滚不会凭空扣）、
  时间设回过去则重新对齐、大跨度只结算最近 96 时辰。
- 触发点：`main.py` 的 `/clock`（前端每 60s 轮询）、`/state`、`/action` 回合后 → **挂机也能跨日**。
- 调参 `trpg-server/时间影响.json`（改文件即时生效）：`每时辰精力.昼/夜=3/9`、
  `睡眠回满时辰=4`（每时辰恢复 = 精力上限÷该值，随养成自动变强）、`夜时辰=[子丑寅]`。
- 新工具 `sleep(shichen=4)`（游戏工具 29→30）；`say`/`gm` 回合被护栏驳回。
- 测试 15 项全过（对齐不结算 / 昼夜扣减 / 睡眠恢复封顶 / 跨日 / 天气联动 / cap）。

**已完成（派生上限）**：
- `tools/derived.py`：`属性.json` 为真相源（**体力=生命值上限，內力=精力值上限**），
  `状态.json` 的上限为投影；`sync()` 漂移时以属性为准回写（上限变小则夹当前值）。
- 接入 `engine.snapshot_state()` 与 `time_flow.pump()`；睡眠恢复量 = **內力 ÷ 睡眠回满时辰**（养成自动变强）。
- 测试 13 项全过（一致不动 / 养成变大 / 缩小夹取 / 属性缺失不动 / sleep 用派生上限）。

**已完成（三模式状态机：探索 / 叙事 / 战斗）**：
- 前端 `GameController.gameMode` 驱动三态；探索 = 整屏 `Map.tsx`（zoom18、WASD 移动、光标覆盖、
  即时迷雾），叙事 = `GameScene`（`display:none` 隐藏不卸载，进度不归零），战斗 = `BattleScene`。
- 切换：探索→叙事由**玩家输入**触发（`sendAction` 带 `坐标`/`上一坐标`）；叙事→探索**只由主持人裁定**
  （新工具 `resume_exploration` → UI 事件 `kind:"mode"`）。
- 后端 `main._apply_move`：收到坐标 → 调 `update_location`（位置/足迹/城内城外）并注入系统提醒
  **【移动】梁峰自「A」来到「B」，相距约 N 米。（耗时提示）**。实测：渡口→永化坊 1544 米、城内西北。
- `ui_events` 加 `mode` kind；`总览.md` 通用规则 14（模式规则）；游戏工具 30→31。

**已完成（WASD 连续移动 + 上一轮状态）**：
- `Map.tsx` 新增 `ExploreControls`：**命令式 Leaflet**（原生 `L.marker` + rAF 逐帧 `setLatLng` +
  `panTo` 相机跟随）——**不触发 React 重渲染**；速度 = 游戏内步速 `1.4 m/s` × 时钟倍率
  （时间快 N 倍 → 标记也快 N 倍，游戏内步速才真实）；输入框聚焦时不拦截 WASD。
- `engine`：`state_dict()` / `render_state()` 拆出；`state_stack = deque(maxlen=2)`（**只两份**）
  每轮末入栈，下一轮把栈顶 + 现拼当前一起发给 LLM（**代码不算差值**，模型自行对比时间/地点/数值）。
- 时钟在**所有模式**都显示（探索模式也有）。构建 + 语法全过。

**修复（文件并发写崩溃）**：
- 症状：`/state` 报 `PermissionError: [WinError 5]`（`os.replace` 覆盖 `基本信息.json` 被拒）。
- 根因：Flask 多线程下 `state_manager.load()`（持读句柄）与 `save()`（`os.replace`）**没加锁**，抢同一文件；且 `.tmp` 是固定名。
- 修：`load`/`save` 同锁串行化 + 唯一临时名（pid+线程号）+ `replace` 重试 6 次；
  `clock`/`derived`/`time_flow` 写盘失败只记日志；`/state`、`/clock` 副作用走 `_best_effort`（永不 500）。
- 测试：8 线程 × 300 轮并发读写 → **0 错误**、无残留 `.tmp`。

**修复（背景误判乡村）**：
- 症状：站在城里街上，小模型给出「乡村」背景。
- 根因：**路网要素没有名字**（`name` 为空、只有 `ancient_kind`），`query_place("大街")` → 0 条
  → `ui_sim._kind_of` 返回空 → `scene_candidates` 退回**全部 49 个场景** → 可选到乡村。
- 修：`_kind_of` 名字查不到时**退回玩家坐标附近最近的有类型要素**；`scene_candidates` 再加
  **城内排除荒野/乡村**的安全网（`_WILD_SCENES`）。实测：城内未知类型时候选 49→37，无乡村/田野。

**开关**：默认开启；`TRPG_CLOCK=0` 关闭、`TRPG_CLOCK_RATE` 调速率（默认 1 真实分钟 = 1 刻）。

**顺手修复**：
- 模拟战斗结果泄漏进游戏叙事（`/battle/action` 无条件注入 `pending_notes` → 主持人照模拟战叙述并经 `modify_hp`/`modify_injury` 改真状态）；现按 `模拟` 标志跳过。
- **`file_tools` 摘出 LLM**（`registry._DISABLED`：`list_directory`/`read_file`/`write_file`/`edit_file` 不下发、不可调用；代码保留，`TRPG_FILE_TOOLS=1` 可临时启用）。LLM 可见工具 33→29（游戏）。

**待做**：`_check_time_authority` 换语义；跨日联动（天气 / `world_worker`）。

### ⭐ 本轮（2026-09-16）：体积碰撞 + 地图性能定案

- **体积碰撞（WASD）**：新增 `trpg-client/src/in-game/walkable.ts`（前端矢量判定 + 网格索引）
  与 `trpg-map/draw_tiles/export_walkable.py`（从空间库导出 `trpg-client/public/data/walkable.geojson`，1.76MB）。
  规则：除**水域 / 城墙**外可走；**城门 25m** 为出城通道；**桥 100m** 可走；**路 ∩ 水** 默认路可走。
  `ExploreControls` 走不动时**沿障碍滑动**（先试 X、再试 Y）；被挡时棋子描边转灰；`?nowalk=1` 关闭碰撞。
  已接进 `trpg-map/生成.py` 的 `walkable` 步骤（须在 `db` 之后）。
- **地图性能定案**：逐层关测 → `?nohit=1` 不卡、`?nofog=1` 最流畅 ⇒ 主因是 `HitLayer`
  每次 `data` 变就整个重建（新建 canvas + `clearLayers` + `addData`）。已改为**图层只挂一次 + 增量增删**；
  同时修了「图标缓存键不含 URL → 先画兜底圆点后无法恢复」的 bug。逐层开关 `?noicons/nohit/nopan/nofog=1`。
  详见 `交接-地图性能.md` §11。
- 残余：`?nopan=1` 仍稍有掉帧（疑似瓦片首次加载 / 合成，未处理）。

### ⭐ 上一轮：战斗视觉 / 地形 / AOE

> 提交 `756ef1a`（+ 本次修复提交）；**均未 push**（本地领先 `origin/main`）。

- **等轴测棋盘**（`in-game/BattleBoard.tsx`）：居中 SVG 2.5D；视点在南，**玩家西南 / 敌人东北**；深度排序（x+y 大者先画）。
- **实体系统**：人物 = 三角锥+球；房屋/墙 = 长方体；河流 = 凹陷蓝色长方体；树 = 树干+绿锥。
- **地形**：`Battle.terrain` + `blocked()`（**房屋/墙阻挡**，河可涉水）+ `reachable_cells()`；`state()["地形"]`；模拟战斗带演示地形（河+房+树）。
- **BGM 小模型选曲**：`ui_sim.battle_track_model()`（**boss 绑定直取**，其余交小模型按「情绪+战况」选；失败回退代码随机）；3 首 boss 曲（王二壮/赵逵/刘鄂）从叙事清单**搬到战斗清单**。
- **技能 AOE 选格子**：`battle.py` 的 `skill_centers/skill_area/_is_aoe`；AOE = 以所选「格」为中心、半径 N 内的敌人；前端点格 + 区域预览（蓝=可选中心，橙=命中区）。
- **修复**：① `state.技能` → **`state.战场.技能`**（层级写错 → AOE 完全没生效）② 橙色区域被蓝色中心格盖住（绘制顺序）③ **`会心阈值` 未实现**（洞察的暴击加成是空的，现会心线 90→75）④ 自身增益技前端提示。
- **技能速记**：舞剑=普攻不耗内力；水天一色=自身·洞察（命中+30 / 会心线−15，2回合）；生生流转=自身·蓄力（≤3层，水行伤害招每层×1.33）；胧/冰=**选格 AOE**。

### 更早一轮（战斗系统 v0.1 及之前）
- **战斗系统 v0.1**：网格 n vs n（10×6，切比雪夫）+ **阶段制**（先手方→后手方）；6 动作（移动/舞剑/防守/技能（五行）/交流（队友或对手）/撤退）；HP/TP·五行相克·**武器类型**（利器流血 / 钝器眩晕 / 徒手）/ Buff（10 基础 + 蓄力/穿甲）；**思路判定小/大模型可切**，且**模型只出「评价」、修正由代码映射**（±10，只作用于伤害）；NPC 走小模型（每侧 1 次调用，幻觉降级）；`start_battle` 工具 + `/battle/*` 路由；2D 俯视桌面**矩形 token** 前端；**环境设定「模拟战斗」**；**战斗 BGM**（boss 绑定专属曲）。详见 `trpg-world/战斗系统.md`。
- **UI 事件管线 ⑧**：bg/music 全由小模型选（`ui_sim.py`）——场景按 `场景映射.md` 地点类型约束；音乐分 `音乐清单.md`（叙事）/`战斗音乐清单.md`（战斗）双清单；专属曲按 `曲名｜绑定` 触发；默认底色曲 `山中好岁月`；**循环播放**（同名不重启）；换曲门槛=换背景或当前曲失效。
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
**本轮改动的后端代码**（规则 md 免重启；改 `*.py` **必须重启**）：
`main.py`（新增 `/clock`、`/action` 收坐标 + `_best_effort`）/ `engine.py`（`state_dict`/`render_state`/`state_stack` 状态栈）/ `tools/game_clock.py`（时钟 + 年号）/ `time_flow.py` / `derived.py` / `modes.py` / `state_manager.py`（并发锁）/ `ui_sim.py`（场景约束回退）/ `registry.py`（`sleep`、`resume_exploration`、摘除 file_tools）/ `ui_events.py`（`mode`）/ `battle_session.py`（模拟战不注入）/ `world_sim.py`（时间线增量合并）/ `recap.py` / `time_weather.py`。
**前端**：`GameController.tsx`（三模式 + WASD + 坐标上传）/ `Map.tsx`（`ExploreControls`）/ `Clock.tsx` + `useGameClock.ts` + `styles/Clock.css`（新）/ `types/gametype.ts` / `styles/GameController.css` / `BattleBoard.tsx`。
**数据**：`游戏数据/时钟.json`（新）、`基本信息.json`（增 `纪年`/`干支`）、`世界状态.json`（定时线 19→89）、`trpg-server/时间影响.json`（新）。
**规则 md（热更，免重启）**：`主持人/总览.md`（规则 14 三模式 + 文体节）、`世界推演/宏观时间线.json`、`场景映射.md`。
> ⚠️ **只跑一个 `python main.py`**（开两个会抢 5000 端口 / 一个跑旧代码，表现为"改了没生效"）。
> ⚠️ **别用外部工具开着 `游戏数据/*.json`**（编辑器 / DB Browser）——会 `PermissionError WinError 5`（现已重试 + 不崩，但写不进去）。

### 下一步优先级（建议）
1. ~~**WASD 碰撞（可走网格）**~~ ✅ 已完成（2026-09-16）：改为**前端矢量碰撞**（`walkable.ts` + `export_walkable.py`）；水域/城墙阻挡，城门 25m / 桥 100m / 路∩水 为通道。
2. **战斗时间折算接入** —— `clock.begin_battle/end_battle` 已就绪，但战斗流程还没接
   （开战 `begin_battle()` → ACCRUING；结束 `end_battle(回合数)` → +回合×60 游戏秒）。
3. **`/move` 边走边同步**（可选）—— 现在坐标只在**输入时**提交给后端；加 `/move` 可让位置/迷雾实时跟上
   （代价：`上一坐标` 得由前端提供，因为后端位置已经等于当前）。
4. **属性养成**（`update_ability` / `train_skill`）—— 改完属性记得调 `derived.sync()`（或直接改 体力/内力）。
5. **战斗路线 B（真战棋）** —— 见 `trpg-world/战斗系统.md §10` / `TODO.md §四`：地形/寻路/ZOC/多目标/
   技能体系/动画音效/更多数值维度/战果写回。
6. 大工程（均**未动**）：**TODO §九 信息边界**、**§十 知识库层**。

> 暂缓：`history` 滑动窗口 / 摘要 —— 用户称模型上下文足够大，**暂不需要**（长局/成本敏感时再评估）。
> 暂缓：小模型润色文风 —— 结论是**别用 4B 改写叙事**（会改事实），已在 `总览.md` 加「文体」节让大模型直接写宋人白话。

### 未动的大块（对应 TODO 编号）
小游戏（未做）；属性养成；日历（**年号/干支已做**，农历/节气未做）；地图扩展（`type` / 地域特色 / 世界地图 / 补史实城门 / 行程耗时 §8.4）；信息边界（§九）；知识库（§十）。

---

## 十三、关键文件速查

| 文件 | 用途 |
|------|------|
| `trpg-server/engine.py` | 引擎：会话 + 回合循环 + 状态现拼 + 过程日志 |
| `trpg-server/save_pipeline.py` | 存档收尾管线 |
| `trpg-server/main.py` | 路由 + bootstrap |
| `trpg-server/llm.py` | 大模型客户端 |
| `trpg-server/tools/registry.py` | 工具单一注册表（LLM 可见 33：游戏 31 + 存档 2；`_ENTRIES` 37） |
| `trpg-server/tools/state_manager.py` | 游戏数据统一读写层（**读写同锁 + 唯一 tmp + 重试**，防并发写 WinError 5） |
| `trpg-server/tools/game_clock.py` | **连续时钟**（单一「游戏秒」标量 + RUNNING/PAUSED/ACCRUING + 南宋年号/干支 + 跨时辰/跨日检测） |
| `trpg-server/tools/time_flow.py` | **时间流逝的后果**（跨时辰扣精力、夜时辰熬夜更狠、跨日切天气+推演、`sleep` + 脱敏对齐） |
| `trpg-server/tools/derived.py` | **派生上限**（体力→生命上限、内力→精力上限；属性为真相源） |
| `trpg-server/tools/modes.py` | **模式切换工具**（`resume_exploration`：叙事→探索） |
| `trpg-server/时间影响.json` | 时间流逝参数（每时辰精力·昼/夜、睡眠回满时辰、夜时辰）——**热改免重启** |
| `trpg-server/tools/mem_store.py` | chroma 访问层（懒加载） |
| `trpg-server/tools/character_archive.py` | 角色动态档案写入 + §10 LRU 淘汰 |
| `trpg-server/tools/get_character.py` | NPC 登场读档（静态 §1–§8 + 动态 §9–§13） |
| `trpg-server/tools/world_state.py` | 世界状态读写 + 活跃名单 + promote_active |
| `trpg-server/tools/ui_sim.py` | 小模型选背景/音乐 |
| `trpg-server/tools/factions.py` | 玩家可见势力（读 `trpg-world/势力介绍.json`） |
| `trpg-server/tools/difficulty_settings.py` | 游戏设置（难度；读`游戏数据/难度设置.json`） |
| `trpg-server/tools/recap.py` | 前情回顾（大模型浓缩 + 小模型选 bg/音乐） |
| `trpg-server/tools/battle.py` | 战斗数值核心（网格/动作/命中伤害/五行/武器/Buff/胜负，纯代码） |
| `trpg-server/tools/battle_tactics.py` | NPC 代码战术层（L2 Utility + L3 前瞻） |
| `trpg-client/src/in-game/BattleBoard.tsx` | 等轴测棋盘 + 实体系统（SVG 2.5D） |
| `trpg-server/tools/battle_runner.py` | 战斗阶段驱动（回合阶段机 + 战局快照） |
| `trpg-server/tools/battle_ai.py` | 战斗 AI（思路判定 + 阵营决策） |
| `trpg-server/tools/battle_session.py` | 当前战斗单例 + 梯度查表 + 结束写回 |
| `trpg-server/tools/battle_settings.py` | 战斗设置（思路判定模型） |
| `trpg-client/src/in-game/battle.tsx` | 战斗界面（网格/矩形 token/日志/思路框/模型开关） |
| `trpg-server/tools/world_sim.py` / `world_worker.py` | 世界推演 / 异步 worker |
| `trpg-server/游戏数据/` | 游戏状态 JSON + 世界状态（与 `tools/` 同级） |
| `trpg-server/sessions/` | 过程日志 + 开局快照 |
| `trpg-client/src/in-game/Clock.tsx` / `useGameClock.ts` / `styles/Clock.css` | **古钟 HUD**（十二时辰环 / 日月弧；锚点 + rAF 本地插值） |
| `trpg-client/src/in-game/GameController.tsx` | 游戏主界面：**三模式状态机**（探索/叙事/战斗）+ 按钮/浮层/事件分流 + 坐标上传 |
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
   ├─ 大模型 ↔ 工具循环（registry：游戏 31 工具）
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
| 战斗：思路判定（可切大模型） | ✅ | ✅ | |
| 战斗：NPC 战术（默认，L2+L3） | | | ✅ |
| 战斗：NPC 阵营决策（`TRPG_BATTLE_AI=model` 时） | | ✅ | |
| 战斗：命中/伤害/HP/内力/Buff/胜负 | | | ✅ |

### 14.6 设置（难度）

```
菜单「环境设定」 ── GET/POST /settings ──► tools/difficulty_settings.py ──► 游戏数据/难度设置.json
      │
      └─（随「状态现拼」每轮注入状态块）──► 大模型按难度调整「世界如何回应」
                                             （不改硬事实：距离/时间/骰值仍由代码算）
```

### 14.7 战斗系统

```
【开战·正式】GM 判定动手
   └─ 工具 start_battle(敌人,友方,缘由) ──► battle_session.start()
         ├─ _tier_map() 读 trpg-world/江湖势力/武力排名.md（名→梯度）
         ├─ _build() → npc_combatant（缺梯度默认 T5）
         ├─ new_battle()：player_combatant() 读 状态/属性/基本信息 + 招式表 → Battle
         ├─ BattleRunner.start()：begin_round → 走 NPC（小模型）→ 停在玩家
         └─ 选战斗 BGM：ui_sim.battle_track_for(敌人, 地点)
   ◄── UI 事件 kind:"battle"（含 战场/日志/音乐）
   前端 GameController.handleUiEvents → setBattleState → BattleScene 打开 + playMusic

【开战·模拟】菜单「环境设定」→ GET /battle/roster（55 人）
   └─ POST /battle/sim {友方,敌人} ──► start(模拟=True) → 同一 BattleScene（不回写存档）

【一回合】
   POST /battle/action {动作,目标,招式,目标格,思路}
     ▼ battle_session.submit
       ├─ judge_thought(战局快照, …, 思路)   ← 小/大模型，只出「评价」→代码映射修正
       ├─ Battle.perform(玩家, 动作, 修正)   ← 纯代码结算 + 写日志
       └─ advance()：友方小模型一次 → 敌方小模型一次 → end_round → begin_round
     ◄── 新战场 + 日志 + 最后的思路判定

【结束】
   battle.ended → battle_session._finalize()
     ├─ 玩家 生命/精力/伤势 → 游戏数据/状态.json（模拟战斗跳过）
     └─ 结果摘要 → main.py 拼「【战斗结果】…」→ session.pending_notes
            └─（下一轮 /action）随「状态现拼」注入 → 大模型叙事后效

【读写】
   读：状态.json / 属性.json / 基本信息.json / 招式表.json / 武力排名.md / 战斗音乐清单.md
   写：状态.json（结束）；sessions/battle_settings.json（切模型）
   战斗状态本身只在内存（battle_session._RUNNER）
```

### 14.8 连续时钟 + 三模式状态机（本轮新增）

```
【时钟】游戏数据/时钟.json = 唯一标量「游戏秒」+ 状态
   │  running 时 now = 锚点秒 + (墙钟 − 锚点墙钟) × 倍率(TRPG_CLOCK_RATE，默认 15)
   │  惰性求值（不跑后台线程）；三态 RUNNING / PAUSED / ACCRUING
   ├─→ 投影 基本信息.时间 = {日期, 时辰, 刻, 纪年, 干支}     ← 随「状态现拼」进 LLM
   ├─→ GET /clock 锚点 → 前端本地插值 → 古钟 HUD（rAF，不轮询）
   └─→ time_flow.pump()（在 /clock、/state、/action 里调用）
         ├─ 跨时辰 → 精力按昼夜扣（夜时辰 子/丑/寅 = 熬夜，更狠）
         └─ 跨日   → weather_system.get_weather(当天) + world_worker.on_turn_end()

【数值】属性.json（体力/内力）--derived.sync()--> 状态.json（生命上限/精力上限）
       睡眠恢复量 = 精力上限 ÷ 睡眠回满时辰（随养成自动变强）

【模式】GameController.gameMode（explore / narrative / battle）
   探索 ──玩家输入（带 坐标/上一坐标）──► 叙事
          （后端 main._apply_move → update_location 更新位置/足迹/城内城外 + 注入【移动】提醒）
   叙事 ──工具 resume_exploration → ui_event("mode","explore")──► 探索
   任一 ──start_battle → ui_event("battle")──► 战斗 ──结束──► 叙事

【发给 LLM 的状态】每次 build_messages：规则 + 前情 + ...history + 工具消息
                  + 【上一轮状态?】 + 【当前状态】
   上一轮状态 = state_stack（deque(maxlen=2)）栈顶；每轮末 append 本轮状态（只两份、不累积）。
```
