# ARCHITECTURE.md — 架构决策记录

> 本文档记录 trpg-project 的**架构决策**与**实现状态**，以及**尚未定论的问题**。
> 只写架构与契约，不写实现代码。随时可推翻重议——推翻时请在此文件留下记录。
>
> 状态图例：✅ 已定/已完成 ｜ 🚧 待实现 ｜ 🔧 待修改 ｜ ❓ 待定

最后更新：**战斗系统 v0.1 落地**（网格 n vs n + 阶段驱动 + 小/大模型思路判定 + 模拟战斗 + 战斗 BGM；第十三节）。此前：记忆层**两级**（动态档案 + LRU）、**地点见闻**、**方位注入**；前端去 `data/`、势力/设置后端化、**前情回顾加载**、**难度设置与归隐退出**；数据目录搬到 `trpg-server/` 同级、日志统一 `current.jsonl`。设计待建：**信息边界（第十节）**、**知识库层（第十一节）**；总纲第 5 条 **「硬事实由代码裁决」** 贯穿。

---

## 0. 一句话总纲

把系统从"一堆脚本各写各的"收敛成**分层的、单一真相源的、事件驱动的**结构：

```
内容层（正典） ──► 引擎层（回合） ──► 表现层（事件流）
        ▲                 │
        │                 ▼
      记忆层（存档蒸馏）  状态层（实时）
```

核心原则：

1. **单一真相源**：每类信息只有一个源，其余都是投影。
2. **类型化接口**：领域数据只能通过专用接口读写，禁止裸文件 I/O。
3. **状态实时、记忆离线**：状态每次现拼；记忆在存档时批量蒸馏。
4. **信息边界（可见性）**：可见性是一等公民。GM 所知 ⊋ 玩家所知 ⊋ 各 NPC 所知；NPC 的言行**只能**基于其知悉集，靠机械隔离而非提示词自觉（第十节）。
5. **硬事实由代码裁决，模型只渲染**：**距离 / 方位 / 城内城外 / 时间 / 数量 / 骰值**等可计算的事实，一律由**代码算出并注入**，**绝不让大模型臆断**——模型只负责“是什么感觉 / 发生什么”，不负责“是多少 / 在哪里 / 何时”。
   （与第 3 条同源：状态现拼、`update_location` 返回距离与城门、`city_context` 判定城内/外、顺利度代码掷骰、时间轴 `update_time` —— 都是这一条的应用。）

**“硬事实”清单（均由代码产出，模型只能引用、不得臆断）**：

| 硬事实 | 产出方 |
|---|---|
| 时间（日期 / 时辰 / 刻） | `time_weather.update_time` |
| 位置、移动距离 / **方位**、耗时提示 | `location.update_location` |
| 城内/城外、**城区方位**、距城墙、最近城门 | `map_query.city_context` |
| 某地相对玩家的**方位 / 距离** | `map_query.query_place` / `query_nearby` |
| 天气 | `weather_system.get_weather` |
| 骰值 / 事件顺利度 | `dice` / `world_sim` |
| 金钱 / 物品 / 生命精力 / 属性 | 各 `state` 工具 |

> 推论：凡新版规则想写“请主持人估算距离/时间/方位/数量”的，应先问“这一步能不能由代码算？”——能则改代码注入。

---

## 一、分层总览

| 层 | 内容 | 源在哪 | 访问方式 | 状态 |
|---|---|---|---|---|
| **规则层** | `trpg-world/主持人/*.md`、`总览.md` | md | 全量注入 system | ✅ |
| **正典层** | `trpg-world/角色静态档案/`(55)、`江湖势力/`、`世界.md` | md | 按需检索 | 🚧 检索接口未做 |
| **记忆层** | chroma（`gm_memory` / `char_memory`） | chroma | 局内只读检索；存档时写入 | ✅ |
| **人物视图** | `trpg-world/角色动态档案/{活跃,不活跃}/*.md` | 推演投影 | NPC 登场时读档 | ✅ |
| **状态层** | `trpg-server/游戏数据/*.json`（含 `世界状态.json`） | JSON | 每次 LLM 调用现拼 | ✅ |
| **过程日志** | `trpg-server/sessions/current.jsonl` | 日志 | 每轮追加，唯一"边玩边写" | ✅ |
| **世界推演** | 宏观时间线 + 活跃人物线程 | 小模型（Qwen3-4B） | 异步，每游戏日一次（第七节） | ✅ |
| **知识库层** | `trpg-world/考据/*.md` + 现有正典 | chroma（`lore`，**可重建投影**） | `KB_query_tool` 按需检索（第十一节） | 🚧 |
| **信息边界** | 跨层可见性（`owner` / `在场·知悉·公开度` / `visibility`） | — | 贯穿记忆/历史/知识三层（第十节） | 🚧 |
| **表现层（前端）** | `trpg-client/`（`GameScene` / `GameController` / `Map` / `AccordionGallery` / 菜单回顾） | **全部来自后端** | 只请求后端接口（`/action` `/state` `/history` `/factions` `/recap` …），**不存游戏内容** | ✅ |

---

## 二、状态层 ✅

### 决策

- **`history` 是真状态**（过程），必须持久化。
- **状态在每次 LLM 调用时现拼，且上下文中只出现一次、永远最新**。
  理由：状态必然影响叙述（"有一万两却不知道"会写偏），但快照会过期，不能塞进 `history`。
- **`history` 只保留纯叙事**（user / assistant 正文），状态与工具中间消息都不进 `history`。
- **`current.jsonl` 每轮追加**：唯一"边玩边做"的更新；一次磁盘 append 成本可忽略，换崩溃安全。
  落盘（每轮，廉价）≠ 蒸馏（存档，昂贵）。
- **`世界状态.json` 放在 `游戏数据/` 下**，因此也被"状态现拼"自动纳入每次调用（第七节）。

### 机制（已实现）

```python
# 每次调用 LLM 都重新拼装，工具循环里也重拼
messages = [
    {"role": "system", "content": 规则},
    {"role": "system", "content": 前情},        # 上一局存档（若有）
    *history,                                    # 纯叙事
    {"role": "system", "content": 当前状态},      # 现拼，只此一份，放末尾
]
```

- 状态块放 messages **末尾**（稳定前缀利于上下文缓存）。
- 工具循环里**每次 `send_messages` 都重拼状态** → 写最终叙述前看到的一定是刚落地的值。
- 实现：`engine.py` 的 `snapshot_state()` / `GameSession.build_messages()`。

### 边界规则

- `游戏数据/` 是**领域自有存储区**：禁止通用文件工具写（`_guard_game_data()`），只能走专用接口 + `state_manager`。
- **`file_tools` 仅供调试，正式上线删除**。删除后 LLM 的知识入口只剩：提示注入 + 类型化工具。
- **凡进 `游戏数据/` 的文件，必须有类型化接口**，否则视为设计漏洞。
- **不是所有 `游戏数据/` 文件都进 LLM 上下文**：`snapshot_state()` 会**排除** `足迹`（探索点）——它们只供前端 `/state` 读，**不发给大模型**；`世界状态` 则按「纳入上下文」裁剪后注入。

### 待办 🔧

"孤儿"（有文件、无写接口）**由代码补接口**：

| 文件 | 补的接口 | 状态 |
|---|---|---|
| `属性.json` | `update_ability` / `train_skill` | 🚧 未做 |
| `混乱度.json` | `evaluate_chaos` | 🚧 未做 |
| `游戏存档.md` | 存档时由代码誊写 | ✅ 已完成 |

---

## 三、记忆层 ✅

### 两级记忆

```
工作记忆（热）                              长期记忆（冷，chroma）
角色动态档案/活跃/*.md  ──LRU 淘汰条目──►   char_memory（角色/潜意识）
客观事实 ────────────────────────────────►  gm_memory（主持人/客观）
```

- **不对称**：主持人记忆**只增不淘汰**（事实不会遗忘）；角色记忆有容量、会淘汰。
- **淘汰即遗忘，遗忘即潜意识**：角色记忆淘汰后进 chroma，需要时被检索回来，以模糊印象形式回到上下文。

### 两个 collection（已实现）

```
chroma（trpg-db/chroma_db）  访问层：tools/mem_store.py（懒加载）
├─ gm_memory（主持人）
│    客观事实（世界到底发生了什么）
│    metadata: { time, kind? }
│    写：存档时 LLM 蒸馏，只增
│    读：全局，无过滤
│
└─ char_memory（角色）
     主观记忆（记忆/感情/认知）
     metadata: { owner, time, kind? }
     写：存档时，动态档案 LRU 溢出的条目
     读：局内按需，强制 where owner = 当前视角角色
```

- collection 名必须 ASCII（chroma 限制），故用 `gm_memory` / `char_memory`。
- 工具：`DB_query_tool` / `DB_add_and_update_tool` / `DB_query_tool_in_saving`，均按 `collection` 寻址，角色必带 `owner`。**id 由代码分配**（`_next_id`=max+1），LLM 不编 id（`check_DB_length` 已退出工具集）。

### 检索铁律

> 查 `char_memory` **必须带 `owner`**；查 `gm_memory` 才全局。跨 owner 检索视为 bug。

这条同时是**信息边界机制**：

- `gm_memory` = 客观真相 → GM 主持世界用；
- `char_memory[owner]` = 该角色主观认知 → 扮演该角色用；
- 两者之差 = "角色不知道 / 记错了 / 误解了"，即戏剧张力来源。

### 时机

- **局内**：允许只读查 chroma（查询轻，无感）。不写任何记忆。
- **存档时**（`save_pipeline.run_save`）：
  1. LLM 蒸馏本局 → `gm_memory`（客观）+ 角色动态档案（主观）
  2. 角色档案 LRU 淘汰 → `char_memory`（✅ 已实现：`tools/character_archive.py`，§10 情感记忆超 20 条时淘汰最旧）
  3. 代码誊写 `游戏存档.md` + 归档
  4. 重置**会话**（history + current.jsonl）；**玩家状态保留**（故事连续）

> 注：「动态档案 = 存档时快照」已被**世界推演**修订——活跃档案随推演每游戏日更新（第七节）。

### 旧格式映射（`存档流程.md` 已照此重写）

| 旧 type | 新归属 |
|---|---|
| `event`（客观事实） | `gm_memory` |
| `information`（谁得知/认为/打算什么） | `char_memory`，`owner` = 那个人 |
| `relationship` | **拆两半**：客观结盟/敌对→`gm_memory`；A 对 B 的好恶→`char_memory[owner=A]` |

### 关键规则

- **IC / OOC**：`梁峰（场外）` 行是玩家对主持人的元对话，**不蒸馏**（见第六节）。
- **id 命名**：`gm_N` / `char_N`，两库各自计数。

---

## 四、内容层 ✅

### 决策

- **`trpg-world/` 是正典唯一来源**。对 LLM 只以两种方式进入：提示注入 / 类型化检索。
  （`file_tools` 的 `WORKSPACE` 只到 `tools/`，本来就够不到 `trpg-world`。）
- **规则层全量注入**：`主持人/*.md`（小、必须每轮在场）。
- **正典层按需检索**：角色静态档案(55)、势力档案、世界设定（大、引用型，全量注入会稀释注意力）。🚧 检索接口未做 → 方案见第十一节「知识库层」。
- **势力介绍：玩家可见数据独立成文件** `trpg-world/势力介绍.json`（已剔除剧透），前端经 `GET /factions`（`tools/factions.py`）读取。**前端不再有 `data/` 文件夹**——所有游戏数据一律向后端请求，后端从 `trpg-world` 对应文件返回。

> **动态 ≠ 把 GM 笔记给玩家看。** `trpg-world/江湖势力/*.md` 含剧透（锦香宫实为泥教人间道、释明暗算唐门等），仍是 **GM 正典（真相）**，只进 LLM、**不经接口暴露**。

```
trpg-world/江湖势力/*.md    ← GM 正典（真相），只进 LLM
trpg-world/势力介绍.json     ← 玩家可见（已剔除剧透）
        │ tools/factions.py · GET /factions
        ▼
前端画廊 { name, desc, detail, image }
```

### 角色档案

- `角色静态档案/`（55 个 md，带 `node_type: memory` frontmatter）= 正典。
- `角色动态档案/{活跃,不活跃}/` = 记忆的近端投影；随世界推演每游戏日更新（第七节）。存档时自动写入活跃名单（第八节 #14）。
  **所有角色地位平等**：临时登场而有实质互动的角色一经建档（存档时自动建静态档案），即与预设角色同等对待；不再区分「正典 / 临时」。
  **静态与动态档案都不进开局上下文**，一律 `get_character(name)` 按需读（见第五节）。
- **档案模板**（`trpg-world/档案模板/`）：`静态模板.md`（原模板 §1–§8，正典）+ `动态模板.md`（§9–§13，近记忆），拆自 `TRPG2/memory/游戏机制/角色档案模板.md`。现有 55 档待逐步对齐。

### 待办 🔧

- ~~`势力介绍.ts`~~ ✅ 已删；改为 `trpg-world/势力介绍.json` + `GET /factions`（`tools/factions.py`），前端 `GameController` 按需 fetch。
- ~~`find_specific_character.py` 路径写错~~ ✅ 已升级为 **`get_character`**（静态正典 + 动态近记忆；`tools/get_character.py`）。

---

## 五、引擎层 ✅

### 结构（已实现）

```
engine.py
  ├─ GameSession       : history + current.jsonl + 开局快照 + 前情
  ├─ TurnRunner.run(input, mode) -> list[Event]
  ├─ TurnRunner.run_save(transcript, rules)   # 存档蒸馏专用回合
  └─ 事件流组装        : 叙事指令 + 工具 UI 事件
save_pipeline.py       : POST /save 的收尾管线
tools/registry.py      : 工具 schema + 实现的单一真相源
main.py                : bootstrap + 路由
```

- `main.py` 退回纯路由 + bootstrap；不再持有 history、不再写工具循环。

### 已定 ✅

1. **开局上下文**：`规则 + 状态(现拼)`；**静态与动态档案都不进开局上下文**，改由工具 `get_character(name)` 按需读（✅ 已实现）。
2. **"存档"是引擎的特殊命令**：`POST /save` 独立收尾管线（→ 第六节的"本局生命周期"）。
3. **状态块位置**：messages **末尾**。

### 单一工具注册表（已实现）

- `tools/registry.py`：`_ENTRIES` 一处定义 `(name, schema, fn)`，派生：
  - `TOOLS = {name: (schema, fn)}`
  - `ALL_TOOLS`（`llm.send_messages` 用）
  - `TOOLS_MAP`（`engine.TurnRunner` 用）
- 当前 **35 个工具**（游戏中 33 + 存档专用 2：`update_character_archive` / `update_place_note`）；新增工具只需在 `_ENTRIES` 加一行，不必再改 `llm.py` / `main.py`。

### 本局生命周期（已实现）

```
本局进行中 ──┬── 存档 POST /save       → 蒸馏 + 誊写/归档 + reset（状态保留）
             ├── 放弃本轮 POST /abandon → 回滚状态到本局开始 + 丢弃日志 + reset
             └── 中途退出/刷新         → 本局保留；GET /history 续玩
```

- **开局快照**：`GameSession` 在本局开始时把 `游戏数据/*.json` 存到 `sessions/run_start_state.json`；`abandon` 用它回滚。
- `reset`（存档用）保留现状；`abandon`（放弃用）先回滚快照。两者都重拍快照、重读前情、清空 `current.jsonl`。
- "重开新档"（清空记忆/状态/前情）暂不做。

### 存档管线（已实现）

```
POST /save
 1. 代码：current.jsonl ──► 逐字叙事 transcript（按游戏内时间分段）
 2. LLM ：读《存档流程.md》蒸馏 ──► gm_memory / char_memory
 3. 代码：transcript ──► 游戏数据/游戏存档.md（下一局读作前情）
 4. 代码：归档 ──► 归档存档/<起>~<止> 存档.md
 5. 代码：重置会话（玩家状态保留）
```

- 分工：**代码负责机械部分（誊写/归档/重置），LLM 只负责语义蒸馏**。
- 修正了原存档流程的 off-by-one（现在蒸馏并归档的是**本局**）。

---

## 六、表现层 / 事件流 ✅（背景迁移除外）

### 决策

后端→前端只保留**一条契约**：有序事件流。事件分两类：

| 类别 | 类型 | 前端行为 |
|---|---|---|
| 叙事指令 | `chat` / `narration` | 线性、点击推进 |
| UI 事件 | `type:"ui"`（`kind`: `bg`/`music`/`minigame` …） | 旁路；`minigame` 可阻塞叙事 |

- **工具副作用**（切背景、放音乐、开小游戏）通过 **UI 事件旁路**送到前端——解决工具中间消息被清理后副作用传不出去的问题。
- **历史面板 / 续玩**走 `GET /history`（读 `current.jsonl`）；前端不再维护平行的 `historyLog`。
- **元操作走界面按钮**：存档、放弃本轮、地图、势力、返回主菜单均**不由 LLM 工具触发**（确定性 + 二次确认）。
- **模型分工**：大模型只产 `chat`/`narration`；`ui_event` 由**本地小模型**产出。
- 原 `bg` 类型已从 `instruction` 删除。

### 事件信封（已实现）

工具侧：

```python
from tools.ui_events import ui_event, UI_EVENTS_KEY

def some_tool(...):
    return {"success": True, "message": "...",
            UI_EVENTS_KEY: [ui_event("music", track="市井")]}
```

引擎侧（`engine.TurnRunner`）：取出 `_ui_events` → 收集成流 → **从给 LLM 的结果中剥离** →
返回 `[...UI 事件, ...LLM 叙事指令]`（工具事件在前）。

前端侧：`GameController.sendAction` 拆为叙事（进 `GameScene`）与 UI 事件（走 `handleUiEvents` 旁路）。

### 输入模式（IC / OOC）（已实现）

`POST /action` 接收 `{input, mode}`：

- `mode:"action"` → 角色行动（IC）。后端组装 `梁峰：<input>` 给大模型。
- `mode:"say"` → **对 NPC 说的话（IC 台词）**。后端组装 `梁峰开口说：「<input>」`，让 NPC 回应，**不作为行动执行**（不得据此跳时间）。
- `mode:"gm"` → 玩家对主持人的场外话（OOC）。后端组装 `玩家的对主持人说的话：<input>`。
- `mode:"continue"` → **「继续」按钮**（可选 `ke` 刻数）：`ke=0` **不推进时间**、只看更多场景信息；`ke>=1` 推进 N 刻。后端用 `engine.continue_cue(ke)` 组装提示语（静观其变、推进场景/NPC、勿替玩家决定、`update_time(advance_ke=N)`）。

`mode` 存进 `current.jsonl`。存档誊写时**只改前缀**、不改内容：
IC → `梁峰：…` / `梁峰说：「…」`；OOC → `梁峰（场外）：…`（**禁止蒸馏**）；
旁白 → `GM：…`；NPC 台词 → `GM（人名）：…`。

> 为什么：前缀字符串是脆弱的 UI 约定；"是不是 OOC"必须是**数据**，不能靠猜。
> OOC 是元对话，**不是世界内发生的事**，混进 `gm_memory` 会造假事实。

### 界面布局（已实现）

```
左侧 [菜单] ─► 存档游戏 / 放弃本轮 / 地图 / 势力 / 返回主菜单
右侧（竖排）  数据 / 历史记录 / 行动 / 主持人
```

- 「数据」弹出金钱/背包/属性/状态（读 `/state`）。
- 「菜单」= `StaggeredMenu`（`closeOnContentClick`，点击项后自动收起）。
- 存档/放弃是**界面按钮**；`save_game` 工具已退役。

### 背景 / 音乐（小模型 UI 事件）✅

- `bg` / `music` 均由 UI 事件控制：`{"type":"ui","kind":"bg","data":{position,time}}`、`{"type":"ui","kind":"music","data":{track}}`。
- 前端：收 `kind:"bg"` → `in-game/background.ts`（地点+时辰→图）；收 `kind:"music"` → `in-game/music.ts`（曲库 = `assets/音乐/*.mp3`）。
- **已迁移**：背景/音乐改由**小模型**产出（`tools/ui_sim.py`）——
  - 大模型只产 `chat`/`narration`；`总览.md` 已删掉 bg 示例并明令禁止输出 UI 事件。
  - 场景枚举 = 前端 `assets/背景/` 子目录（**场景说明见 `trpg-world/场景清单.md`**）；音乐候选 = **两个独立清单**：`音乐清单.md`（叙事）与 `战斗音乐清单.md`（战斗），条目格式 `曲名｜绑定：说明`。均只含实际存在的 mp3。小模型只从候选里选（+「无」），无幻觉面。**叙事默认底色曲 = `山中好岁月`**（无更贴合者时用它）。
  - **背景按地点类型约束**（`ui_sim.scene_candidates(location)`）：查玩家所在地点的地图类型（`ancient_kind`），只在该类允许的场景内选（映射见 `trpg-world/场景映射.md`）；未映射则不限制。防"在城里被切到乡村"。
  - 叙事选曲（`ui_sim.narrative_tracks(location, present)`）= 读 `音乐清单.md`，**有绑定**的仅当对象在场（命中「地点名 / **地点类型**（`ancient_kind`）/ 登场人物」任一；人物需**本轮登场**），**无绑定**则始终可用。**战斗曲在 `战斗音乐清单.md`（`ui_sim.battle_tracks()`），叙事候选天然看不到——两者互斥。**
  - 引擎做**去重**（与上次相同不发）。
  - 小模型输入 = 本轮叙事 + **当前地点** + **当前背景/音乐** + 枚举清单（各带说明）；输出 `{场景, 音乐}`。
  - **换曲规则（引擎强制）**：背景变化 **或 当前曲已不适用于本地点/在场**时，才允许换曲（当前曲不再适用且模型未给新曲 → 发「停乐」`track:"无"`）；否则同一背景保持当前曲目。

### 待定 ❓

- 小游戏事件类型与暂停/恢复语义。
- 前端浮层结构（`MiniGameHost` + 懒加载注册表）。

---

## 七、小模型层（ui_event + 世界推演）

本地小模型：**Qwen3-4B**（LM Studio，`qwen/qwen3-4b-2507`，已加载）。与大模型**并列**的另一条生成链路。

**统一约束（`tools/small_model.ask_json`）**：

- **单次 10s 硬超时**：超时 `stream.cancel()` **真中断**生成并返回 None，调用方降级（可用 `TRPG_SMALL_TIMEOUT` 覆盖）。`lmstudio.set_sync_api_timeout()` **无效**。
- 判定 / 分类类系统提示**必须** `/no_think` 且限 `max_tokens`，否则 4B 会陷入长思考。
- 失败一律返回 None（调用方降级，不崩）。

### 7.1 两条管线

| | `ui_event` | 世界推演 |
|---|---|---|
| 时机 | 同步，每轮 | 异步，随游戏日 |
| 延迟敏感 | 高（背景/音乐随场景） | 无（off-screen） |
| 输出 | 极小（kind + 字段） | **两个枚举值** |
| 触发 | 当前叙事 / 场景 | 推进一个游戏日 |
| 状态 | ✅ 已实现（bg/music） | ✅ 已实现 |

**模型分工**：大模型产 `chat`/`narration`（玩家眼前）；小模型产 `ui_event` + off-screen 推演。

### 7.2 世界推演的核心决策（已实现）

> **小模型只做离散采样，具体叙事交给大模型。**

```
每游戏日，对每个活跃人物：
    小模型 ──► { 地点, 事件类型, 纳入上下文 }   ← 都是离散值，幻觉面趋近于零
    代码   ──► 顺利度（加权掷骰，顺+平 ≈ 90%）
        └──► 写入 世界状态.人物线程

玩家遇到该人物时：
    大模型 ──► get_character(name) 读 静态档案 + 动态近记忆
            ──► 自行演绎出既具体、又合正典的叙事
```

**为什么只出极少的离散值**：4B 生成"具体事实"必然与正典冲突，且会被固化成假事实；
抽象成离散状态后它**无从编错**，由读过全部正典的大模型负责演成情节。
（实测：不逼它极简时，它会把字段写成整段小说、单次 19s+；严格提示后降到 0.5-2s。）

- **事件类型**（8 选 1）：营生 / 修行 / 社交 / 赶路 / 生活 / 公务 / 寻医 / 变故
- **顺利度**（代码掷骰，5 档）：大顺 5 / 顺 45 / 平 45 / 不顺 4 / 大挫 1
- **地点**：自由文本（信任小模型不会让人日行千里）
- **纳入上下文**（bool）：按**离玩家远近**判断此事是否该进大模型视野。
  **不改变推演内容，只决定注入裁剪**（见 7.5）；存储仍是全量。

### 7.3 触发与异步（已实现）

```
每次 /action 结束 ──► world_worker.on_turn_end()
    比对「已入队游标」与当前游戏日期
    跨 N 天 ──► 入队 N 个「日任务」（超过 MAX_TICKS=10 则跳过早先的）
                        │  daemon 线程（不阻塞玩家）
                        ▼
   单日：触发宏观 → 对每个活跃人物采样（是否进上下文由小模型决定）→ 写回 → 游标推进
```

- **入队游标与推演游标分离**：避免"没跑完就被重复入队"；进程重启后自动补缺口。
- **世代号 + `clear(wait)`**：`clear()` 递增世代，队列里/在途的旧任务出队即作废；`abandon` 在**回滚快照前**调 `clear(wait=True)`，保证在途写入也被回滚。
- **写入单一化**：所有 `世界状态.json` 写入只在 daemon 线程发生（`fast_forward` 也入队），消除请求线程与 daemon 的写竞争。
- **总开关**：`TRPG_WORLD_SIM=0` 关闭（小模型不可用时也不影响玩）。
- **降级**：小模型调用失败 → 跳过该人物，不写脏数据。

### 7.4 宏观层（已实现）

- 作者时间线 `trpg-world/世界推演/宏观时间线.json`（19 条，1220-02 ~ 1224-09，参照南宋嘉定年间史实）。
- 代码按日期触发，**小模型不介入**（宏观不能编歪）。
- 种子进 `世界状态.定时线`（而非直接读文件），使「已触发」标记也能随开局快照回滚。

### 7.5 存储

```
游戏数据/世界状态.json        ← live，结构化（在 游戏数据/ 下 ⇒ 自动进入"状态现拼"与开局快照）
    { 模拟游标, 宏观:[...], 定时线:[{date,text,已触发}],
      人物线程: {名: {地点, 最新:{日期,地点,类型,顺利度,纳入上下文}, 流水:[...上限5]}} }
trpg-world/角色动态档案/{活跃,不活跃}/*.md   ← 近记忆文本（大模型读）
trpg-world/世界推演/宏观时间线.json + 推演规则.md
chroma                        ← 存档时蒸馏（大模型，重）
```

- **注入裁剪**：大模型看到的是 `world_state.context_view()` —— 人物线程只保留
  `纳入上下文` 为真的条目，某人物若全被裁掉则不出现；`宏观`/`定时线`/`模拟游标` 不裁。
  **存储始终全量**（存档时全量采纳）。

> **修订**：此前「动态档案 = 存档时快照」改为——活跃档案随推演更新。
> 「存档时才写」约束的是**蒸馏**（重 LLM），不是档案文件（轻磁盘写）。

### 7.6 大模型如何获知世界

1. **`世界状态.json` 及时可见**：在 `游戏数据/` 下，被「状态现拼」自动纳入每次 LLM 调用 ⇒ 永远最新。
2. **NPC 登场即读档**：调工具 `get_character(name)`（✅），返回 `角色静态档案/<名>.md`（静态）+ `角色动态档案/{活跃,不活跃}/<名>.md`（动态）。**深层记忆（`char_memory[owner]`）不由本工具取**——由 LLM 按需再调 `DB_query_tool`。

### 7.7 硬依赖

- ✅ **时间必须权威**：规则已写入 `总览.md` 通用规则 10；`engine` 另加**机械兜底**——叙述若含时间推进标记（`翌日/次日/数日后/赶了N天/…`）却未调用 `update_time`，则在下一轮注入「时间提醒」直到补上。

### 待定 ❓

- ✅ **活跃人物名单来源**：存档管线自动写入（见第八节 #14）。
- 活跃 → 不活跃的淘汰规则。🅿️ 搁置（等活跃 NPC 增多后再定）
- ✅ `get_character(name)` 工具（静态 + 动态；深层记忆交 LLM 按需查）。
- ✅ `ui_event` 的 kind 清单与协议（bg / music / minigame）。

---

## 八、已知问题 / 不一致清单

| # | 问题 | 位置 | 状态 |
|---|---|---|---|
| 1 | 系统提示里的状态是开机快照，永不刷新 | `main.py` | ✅ 由"状态现拼"解决 |
| 2 | `find_specific_character` 路径写错（永远返回“没找到”） | `tools/find_specific_character.py` | ✅ 已修并被 `get_character` 取代（`tools/get_character.py`，静态+动态；2026-09-13） |
| 3 | chroma 初始化路径与读取路径不一致 | `init_GM_DB.py` vs `main.py` | ✅ 已修正，统一到 `trpg-db/chroma_db` |
| 4 | embedding 模型三处不一致 | `main.py`/`init_GM_DB.py`/`DB.py` | ✅ 统一用 `lms.embedding_model` |
| 5 | 存档流程用 file 工具写 `游戏数据/`，被 guard 拦 | `存档流程.md` | ✅ 改为代码誊写 |
| 6 | 存档流程 off-by-one（蒸馏上一局） | `存档流程.md` | ✅ 已修正：蒸馏本局 |
| 7 | 前端属性/金钱是写死的假数据 | `GameController.tsx` | ✅ 已接 `/state` |
| 8 | 工具双份登记 | `llm.py` + `main.py` | ✅ 已合并为 `tools/registry.py` |
| 9 | 内容双写（势力介绍） | `势力介绍.ts` vs `trpg-world` | ✅ 已修：删前端 `data/`，改为 `trpg-world/势力介绍.json` + `GET /factions` |
| 10 | `角色动态档案/` 为空且无机制 | `trpg-world/角色动态档案/` | 🚧 待第 ⑦ 步 |
| 11 | `属性.json` / `混乱度.json` 无写接口 | `游戏数据/` | 🚧 待补 `update_ability` / `evaluate_chaos` |
| 12 | 放弃确认用原生 `window.confirm`，与 UI 不搭 | `GameController.tsx` | 🚧 待换自定义浮层 |
| 13 | 工具返回类型不统一（str / dict / int / list） | `tools/*.py` | 🔧 目前都能被 `json.dumps`，新工具需注意 |
| 14 | 活跃人物名单无人写入（`角色动态档案/活跃/`） | `trpg-world/角色动态档案/` | ✅ 已修：存档管线自动写入（三来源抽取，幂等，可从不活跃迁回） |
| 15 | **外部程序打开 `chroma_db` 会让 chromadb 静默卡死** | `trpg-db/chroma_db` | ⚠️ 已知坑：Rust 内核启动要拿写锁，被占则无输出死等（如 DB Browser for SQLite）。运行前先关掉 |
| 16 | **`check_DB_length` 式编 id：删过条目后会撞 id，而 chroma 对重复 id 静默丢弃 → 记忆悄失** | `tools/DB.py` | ✅ 已修：id 由代码 `_next_id`（max+1）分配，LLM 不再编 id（32 工具） |
| 17 | **NPC 全知**：单一 `history` 被 LLM 当作"人人知道"，NPC 说出梁峰私下所为 | `engine.py` / `current.jsonl` | 🚧 第十节「信息边界」：加知情字段 + 两段式调用 |
| 18 | 正典层（角色/势力/世界）无检索接口，只能全量注入或靠 `file_tools` | `trpg-world/` | 🚧 第十一节「知识库层」 |

---

## 九、迁移顺序

```
地基（互相咬合）：
  ① engine.py + GameSession + current.jsonl 落盘        ✅
  ② 统一事件流（含 /state、/history）                 ✅
  ③ 单一工具注册表                                    ✅

记忆层：
  ④ 两 collection + owner；修 init 路径与 embedding   ✅
  ⑤ 存档流程重写（代码誊写 + LLM 蒸馏 + 归档）          ✅（动态档案 + LRU 已补齐）
  本局生命周期（存档 / 放弃 / 续玩）                    ✅

内容层：
  ⑥ /factions 投影 + 玩家可见势力接口                  ✅（2026-09-13）

小模型层：
  ⑦ 世界状态.json + 日推演异步 worker + 宏观时间线      ✅
  ⑧ ui_event 管线（bg/music 由小模型产出）              ✅

能力扩展（此时都只是"加事件类型"）：
  ⑨ 小游戏 / 音乐 / 战斗                               🚧（战斗 ✅ v0.1）

新增方向（编号待定，登记在 TODO.md 第七/八节）：
  历法：新历＋农历双历、节气/节日/月相，与天气/推演联动    🚧
  地图：`features` 加 `description`/`type`（时空化定时事件） 🚧
  地图：地域特色重制（江南/北方/山地/沿海 差异化）          🚧
  地图：世界地图 / 多 `map_id` / 旅行机制                  🚧
```

### 实现记录（简）

- **① 引擎拆分 + 过程日志**：`engine.py`（`GameSession` / `TurnRunner`）；`state_manager` 加 `snapshot()`；日志 `sessions/current.jsonl`。
- **② 统一事件流**：`tools/ui_events.py`；`TurnRunner` 收集并剥离 `_ui_events`；`GET /state`；前端 `ui_event` 类型 + 拆分 UI 事件。
- **bg 迁移**：删 `bg` 类型；新增 `in-game/background.ts`；`GameScene` 改为接收 `background` prop；`GameController` 处理 `kind:"bg"`。
- **③ 单一工具注册表**：`tools/registry.py`（脚本从旧代码生成，零错配）；`llm.py` 缩到客户端；`main.py` 去工具导入。
- **④ 记忆层双库**：`gm_memory` / `char_memory`；`tools/mem_store.py`（懒加载）；`DB.py` 按 collection+owner；修 init 路径与 embedding。初始化脚本改为**只建结构、不写入任何内容**（`--reset` 可重建）。**id 由代码分配**（`_next_id` = max+1），LLM 不再编 id；`check_DB_length` 退出工具集。
  - ⚠️ chroma 的 `delete()` 是**逻辑删除 + 打墓碑**：`count()` 归 0，但写前日志 `embeddings_queue` 与 HNSW 向量段仍留痕迹。**彻底清空只能 `init_GM_DB.py --reset`**。
- **⑤ 存档流程**：`save_pipeline.py`；`TurnRunner.run_save`；`存档流程.md` 重写；`POST /save`；IC/OOC 输入模式与「场外」标记不蒸馏。
- **历史面板 + 续玩**：`GET /history`（`{active, lines, tail}`）；删 `historyLog`；进入游戏自动续上最后一幕。
- **放弃本轮**：开局快照 `sessions/run_start_state.json`；`POST /abandon` 回滚状态。
- **UI 重构**：顶层按钮收敛为 主持人/行动/**继续**/历史记录/数据；存档/放弃/地图/势力/返回入「菜单」；`save_game` 工具退役（32 工具）。
- **工具审计**（当时 33 个，现 32）：schema↔函数签名静态对齐 **0 问题**；运行时逐个调用（含负例）全部正常。
  修复 `DB_add_and_update_tool`：不带 `time` 时 metadata 为空被 chroma 拒绝（已在存档蒸馏路径上）——改为 `time` 始终写入。
  `find_specific_character` 路径 bug 已修（绝对路径 + 目录，返回 dict）→ **已升级为 `get_character`**（见下）。
- **⑦ 世界推演**（2026-09-13）
  - `tools/small_model.py`：Qwen3-4B 封装，`respond(response_format=<JSON Schema>)` + `res.parsed`；严格提示后 0.5-2s/次。
  - `tools/world_state.py`：世界状态读写（游标 / 宏观 / 定时线 / 人物线程）、日期差、活跃名单（扫 `角色动态档案/活跃/`）。
  - `tools/world_sim.py`：单日推演——小模型只出 `{地点,事件类型,纳入上下文}`，顺利度**代码加权掷骰**（顺+平≈90%）；宏观按日期触发。**不做代码级「在场豁免」**（早期按地点字符串跳过，导致同区域 NPC 线程被永久冻结）——所有活跃人物一律采样，是否进上下文交给小模型的 `纳入上下文`。
  - `tools/world_worker.py`：异步队列 + daemon 线程；入队/推演游标分离；MAX_TICKS=10 大跨度跳过；`clear()`；`TRPG_WORLD_SIM=0` 总开关。
  - `engine.py`：每轮结束调 `on_turn_end()`；`reset`/`abandon` 清队；开局快照含 `世界状态`（首次不存在时补空白）。
  - 内容：`世界推演/宏观时间线.json`（19 条，1220-02~1224-09，参照南宋嘉定年间）+ `推演规则.md`。
  - 已测：宏观按日期触发、掷骰分布（顺+平=90.2%）、入队/去重/清队/大跨度跳过、快照含世界状态。
  - **worker 线程模型完善**（2026-09-13）：`_lock` 保护 `_enqueued_to`/`_generation`；任务带世代号，`clear()` 递增世代作废队列与在途旧任务；`fast_forward` 改为入队（所有状态写入只在 daemon 线程）；`engine.reset/abandon` 改为在**回滚前**调 `clear(wait=True)`。已测：正常入队顺序、大跨度快进、clear 作废队列、clear(wait) 等在途。
  - **活跃名单自动化**（2026-09-13）：`save_pipeline.contacted_characters` 从 `chat` 发言人 / `get_character` 解析名 / `char_memory.owner` 三处确定性抽取本局接触的正典人物，`world_state.promote_active` 写入 `活跃/<名>.md`（幂等；曾淘汰者迁回保留近记忆）。解决 #14（世界推演空转）。
  - **动态档案为主、char_memory 只在溢出时写入（LRU）**（2026-09-13，按用户要求，阈值 N=20）：此前存档流程直接叫 LLM 把主观记忆写 `char_memory`（冷库），而设计本应是「热=动态档案 §9–§13」→「冷=char_memory（仅 LRU 溢出）」，且根本没有写动态档案的工具（LRU 也没实现）。新增 `tools/character_archive.py` + 存档专用工具 `update_character_archive`（仅 `SAVE_TOOLS` 可见，游戏中的 GM 看不到）：按模板更新某 NPC 的动态档案（§9 里程碑/最近互动/态度、§10 情感记忆、§11 情绪、§12 信息边界），首次登场可带 `static` 字段建静态档案；§10 超 20 行 → 最旧的写入 `char_memory[owner]`（写入成功才从档案移除，chroma 不可用则不删）。`存档流程.md` 重写：客观 → `gm_memory`，主观 → `update_character_archive`，**不再写 `char_memory`**。`registry` 拆出 `ALL_TOOLS`（游戏，排除 save-only）与 `SAVE_TOOLS`（存档，含全部）；`llm.send_messages` 加 `tools=` 参数；`engine.run_save` 用 `SAVE_TOOLS`。实测：模板字段写入、§10 25 行→20 行、真实 chroma 写入失败时保留不删。
  - **新登场 NPC 也建档、地位平等**（2026-09-13，按用户明确要求）：原先 `contacted_characters` 只保留**有静态档案**的人物，导致实战里 阿沅 / 怀茂青楼老妇 / 挑炭人 这类新角色全被丢弃、世界推演空转。改为：凡本局有实质互动的 NPC 都建档——**静态档案**（存档蒸馏时 `update_character_archive` 的 `static` 字段，或 `character_archive.ensure_static` 兼底，不存在则按 `静态模板` §1–§8 建）+ **动态档案**（§9–§13）；经 `world_state.promote_active` 入活跃名单。**所有角色地位平等**（新角色一经建档即与预设角色同等），代码/文档不再区分「正典 / 临时」。配套：`get_character` 静态缺失时退回动态（兼底）；`world_sim._profile` 无静态时读动态。`存档流程.md` 加「人物命名要统一、用规范名」与「【场外】整段回答不蒸馏」。
  - **建档逻辑显式化**（2026-09-13）：`update_character_archive` 先查静态档案：**已存在**（老角色）→ 只更新动态（静态正典不覆盖）；**不存在**（新角色）→ 建静态（用 `static` 或 stub）+ 动态。返回值加 `new_character` 标志。实测：老角色静态 hash 不变、新角色两档均建。
  - **前端去 `data/`，势力改由后端供**（2026-09-13，按用户要求）：删 `trpg-client/src/data/`（`previous.ts` + `势力介绍.ts`）；玩家可见势力落到 `trpg-world/势力介绍.json`（从原 TS 导出，13 条），新增 `tools/factions.py` + `GET /factions`，`GameController` 改 `fetch` + `useMemo` 构建画廊（不再用模块常量）。原则：**前端要的游戏数据一律向后端请求，后端从 `trpg-world` 对应文件返回**。
  - **前情回顾加载（`GET /recap`）**（2026-09-13，按用户要求）：点「继续旅途」→ 主页面加载（主题曲继续放）→ `tools/recap.py` 读 `游戏数据/游戏存档.md`，大模型浓缩成 **≤10 段 narration**（末段无缝衔接当前地点/时间），小模型为最后一幕选 **bg + 音乐**（复用 `ui_sim.generate`）→ 拿到后**直接进游戏**；前情提要在 **in game 内**用 `GameScene` 点击推进（新增 `onFinish`、防空历史），播完才进正常游戏。进入游戏时主题曲停、播放所选 bg/音乐（`App` 经 `initialBg`/`initialMusic`/`initialRecap` 传入 `Gaming`）。无存档 → 跳过回顾直接进游戏。
  - **方位注入（修 GM 方位翻车）**（2026-09-14，实战发现）：GM 把城**东北**的「水门」当成「**西**水关」，叙述了一整套西边地理（因地图只有一座「水门」，无「西水关」，GM 凭地名臆断）。根因：代码从不告知方位。修：`map_query.bearing_name()`（八方位）+ `distance_m()`；`query_place`/`query_nearby` 每个结果带 `方位` + `距玩家（米）`；`city_context` 加 `城区方位`（如「城内东北」）；`update_location` 加 `移动方位` + `位置.城区方位`。`总览.md`「叙事节奏与移动」规则 6 改为「方位以数据为准，不得凭地名臆断」。仍待办：地图缺「西水关」等史实城门（需改地图源并重建）。
  - **难度设置 + 归隐退出**（2026-09-14）：新增 `tools/difficulty_settings.py` + `GET`/`POST /settings`；难度**及其各级含义 `难度说明`** 均存 `游戏数据/难度设置.json`（**数据源**，随状态现拼每轮发给 LLM，可手工编辑扩充）——四档「轻松/普通/困难/硬核」；`总览.md` 通用规则 13 仅指向状态块 `难度设置.json`（按难度调整世界回应，不改硬事实）。前端「环境设定」面板可选难度、「归隐山林」直接退出（`window.close()` + 退出屏兼底）。
  - **数据目录搬到 `trpg-server/` 同级 + 日志重命名**（2026-09-14）：`tools/游戏数据` / `tools/天气数据` / `tools/归档存档` → `trpg-server/游戏数据` / `天气数据` / `归档存档`（`git mv`）；所有路径改基于 `__file__` 绝对解析（`state_manager` / `weather_system` / `recap` / `file_tools` / `engine` / `save_pipeline`）。过程日志 `turns.jsonl` → **`current.jsonl`**（注释/文档全量更名；代码标识 `CURRENT_LOG` 不变）。
  - **`get_character`**（2026-09-13）：`tools/get_character.py` 取代 `find_specific_character`——NPC 登场时返回**静态正典 + 动态近记忆**（活跃优先、退不活跃）；**深层记忆（chroma）不取**，交 LLM 按需调 `DB_query_tool`。模糊匹配改进：文件名精确 > 文件名包含 > 身份标识（称号/绰号）> 正文包含（`龙王刀`→上官隼）。已测全路径。
  - **时间权威**（2026-09-13）：`总览.md` 通用规则 10（时间流逝必须调 `update_time`）；`engine` 加 `_time_advanced`（正则检出 `翌日/次日/数日后/赶了N天/…`）+ `_check_time_authority`：叙述推进了时间却未调 `update_time` → 写 `session.pending_time_note`，注入下一轮，补上后清除。已测正/负例。
  - **时间统一为十二时辰**（2026-09-13）：`update_time` 参数 `hour`→`shichen`、`advance_hours`→`advance_shichen`；`time_weather.HOURS`→`SHICHEN`；tool schema / `总览.md` / `engine` 提醒同步。不再出现"小时 / 24 小时"概念（12 时辰 = 1 天）。
  - **UI 事件管线 ⑧**（2026-09-13）：`tools/ui_sim.py`（小模型据此产 `bg`/`music`，枚举=前端资源，场景/音乐各带 `场景清单.md`/`音乐清单.md` 的情境说明）；`ui_events.py` 加 `bg_event`/`music_event` + kind 清单；`engine._scene_ui_events` 接线 + 去重；`总览.md` 删 bg 并禁止 UI 事件，删 `主持人/可用场景.md`；前端 `in-game/music.ts` + `assets/音乐/index.ts`，`GameController` 接 `kind:"music"`。小模型输入含**当前地点 + 当前背景/音乐**；`engine` 换曲门槛：**背景变化 或 当前曲不再适用于本地点/在场**（不再适用且模型未给新曲→停乐）。**音乐拆为两份清单** `音乐清单.md`（叙事）`战斗音乐清单.md`（战斗，叙事看不到），条目 `曲名｜绑定：说明`；叙事**默认底色曲** `山中好岁月`（无更贴合者时用）。**背景按玩家地点的 `ancient_kind` 约束**（`场景映射.md`）；**坐标移动会回填最近地名**（`update_location`），避免地点变成坐标串。已测：小模型选场景/音乐、纯对话+地点选背景、引擎去重/换曲门槛、曲目适用性换/停、绑定匹配、地点约束、坐标回填、双清单互斥、`tsc` 通过。
  - **修「在场豁免」冻结 bug + 区域不更新**（2026-09-13）：`world_sim.run_day` 删掉"与玩家同地点/区域者豁免"（该分支只 `continue` 不补写，导致同区域 NPC 线程被**永久冻结**）——改为**所有活跃人物一律采样**，是否进上下文交小模型 `纳入上下文`；`推演规则.md` 加"与玩家同处勿挪走"参考。`update_location` 补写 `位置.区域`（`map_query.DEFAULT_REGION`，此前从不写 → `current_region()` 恒为旧值）。
  - **「说话」按钮（行动 vs 台词）**（2026-09-13）：`POST /action` 新增 `mode:"say"`（`梁峰开口说：「…」`）；修 GM 把玩家台词误当行动（"住一晚"→当场睡到天亮）；`总览.md` 规则 12（区分行动与台词）；前端加「说话」按钮 + 台词输入框。
  - **金钱「请款→确认→账目」**（2026-09-13）：`modify_money` 改为**请款**（不直接改钱，登记待确认 + 产出 `kind:"money"` UI 事件）；`POST /money/confirm` 落账并记 `游戏数据/账目.json`，`/money/reject` 取消（并在下一轮注入"玩家拒绝"系统提醒，`GameSession.pending_notes`）；前端加**金钱确认浮层**（确认/取消）；`账目.json` 仅存档、**不在前端显示**、也不进 LLM 上下文（`账目`/`足迹` 已从状态快照排除）。另：`总览.md` 规则 11（金钱必须确认、禁自动记账）、语言锚定改为"只锁中文、不输出元话术"。
  - **疏漏审计与修复**（2026-09-13）：修 `money` 待确认**未在 `reset/abandon` 清空**（会跨局生效）；`/state` 附 `待确认金钱`（前端刷新后重弹确认框）；`ability.py` 相对路径→`state`；`_TIME_NOTE` 措辞、`money._now` 中文刻、`ui_events.KINDS` 补 `money`。审计结论：32 工具 schema↔签名 0 问题、无相对路径 / 裸 open / 调试 print。
  - **城池内外判定（修 GM 方位翻车）**（2026-09-13）：实测 GM 为判断"城里城外"连调 17 次地图工具、还自相矛盾（先"没出城"后"出了城"）。新增 `map_query.city_context(lon,lat)`（城墙 Ring → Polygon 点内外 + 距城墙 + 最近城门）；`update_location` 写入 `位置.在城内/距城墙/最近城门`、检测**过城墙**并在返回提示；`总览.md` 加规则（以数据为准、跨城墙必须叙述过城门）。
  - **「世界不围着你转」规则 + 规则热更新**（2026-09-13）：`总览.md` 主持人铁律加第 4 条（默认无人注意你；钩子来自世界自身事件，不硬塞盯玩家的人）；`engine._rules_text()` 按文件夹 mtime 缓存、每回合热读 `trpg-world/主持人/*.md`，改规则**免重启**（`main.py` 传 `rules_dir`）。
  - **「继续」按钮 + 「刻」**（2026-09-13）：`POST /action` 新增 `mode:"continue"` + `ke`（0=不推进时间只看信息，N=推进 N 刻；`engine.continue_cue(ke)`）；时间模型加 **刻**（1 时辰 = 8 刻，1 刻 ≈ 15 分钟），`time_weather.update_time` 支持 `ke`/`advance_ke`，`engine.current_game_time` 显示"酉时二刻"；前端「继续」展开 0/1/2/3 刻选项。实测：ke=0 不推进时间（改去查地图细节）、ke=2 只走 2 刻。
  - **修主持人"替玩家跑远/时间跳太多"**（2026-09-13）：实测 GM 把"往东南走"直接 `update_location(大东门坊)`（~850m）并 `update_time(+1时辰=2h)`。修法：`总览.md` 新增「叙事节奏与移动」（一次一拍、不替玩家决定走多远、移动落库、**短距离不推时辰**、旁白 1–3 句）；`update_location` 返回**移动距离（米）+ 耗时提示**（供 GM 判断是否 `update_time`）；tool schema 同步。
  - **金钱去掉请款/确认，改为直接落账**（推翻 2026-09-13 请款方案）：`modify_money` 又**直接改钱**（增加/减少，余额不足整笔拒绝）并记 `账目.json`；删 `/money/confirm`、`/money/reject`、`money._PENDING`/`pending`/`apply_pending`/`cancel_pending`、UI 事件 `kind:"money"`、前端确认浮层、`/state.待确认金钱`、`reset/abandon` 里的 `cancel_pending`。`总览.md` 规则 11 改为「金钱直接落账」。**推翻理由**：确认环节把一次变动拆成两个非原子步骤（请款→确认），其间 LLM 的 history 与真实余额已脱节，且确认/拒绍还得额外注入系统提醒才能维持同步（否则出现"扣了钱 LLM 不认"），复杂度高、易账目不一致；直接落账后「改钱」一步完成，单一真相源重回 `金钱.json`。
  - **金钱再删账本 `账目.json`**：删 `tools/money.py` 的 `ledger`/`_append_ledger`/`_now`/`LEDGER_LIMIT`、删文件 `游戏数据/账目.json`、`snapshot_state()` 的排除名单只剩 `足迹`。**理由**：直接落账后 `金钱.json` 已是单一真相源，账本只是重复投影且会与实际余额脱节；需要流水时以 `金钱.json` 为准。
  - **修 `query_nearby` 返回代表点导致瞬移**（2026-09-13，实战发现）：GM 按 `query_nearby` 返回的 `lon/lat` 移动，但那是**代表点**（线=中点 / 面=内部点）；实测一条从青楼旁 1 米处过的坊巷，其返回坐标离玩家 **184 米**，`distance_km` 却是 0.001，于是"跳窗"被瞬移 184 米。修：`query_nearby` 改为返回**几何体上离查询点最近的点**（`nearest_points`，在米制投影下求后再换回经纬度）；`query_place` 仍用代表点（无查询点）。已测：返回点实距与 `distance_km` 对齐（0.6m vs 0.001km）。
  - **地点见闻（`description` / `place_notes`）**（2026-09-13，按用户要求）：`features` 加静态 `description` 列；新增独立表 `place_notes`（重建地图**不删**）存「某地发生过的事」；新工具 `update_place_note(place,note,time)`——**存档专用**（在 `_SAVE_ONLY`，游戏中 GM 看不见），由存档蒸馏回合按地点写入（见 `存档流程.md`）；`query_nearby`/`query_place` 命中地名时合并静态 description 与动态见闻，返回 `description`（合并串）+ `notes`（结构化）。`create_spatial_db.py` schema 同步（重建不回退）；`map_query._ensure_place_schema` 懒迁移旧库。已播种本局事件：怀茂青楼（强暴/赖账跳窗）、太阳坊（撞翻炭担/浓雾）。
  - **台词回合时间护栏（规则 12 机械兼底）**（2026-09-13，实战发现）：GM 拿一句 **台词**（`say`，`"我准备歇了"`）直接 `update_time(advance_shichen=6)` 快进一整夜——却正是规则 12 要拦的。新增 `engine.TurnRunner._say_time_guard`：`say`/`gm` 模式下 `update_time` 只允许 ≤ `SAY_MAX_KE=2` 刻的 `advance_ke`，任何推进时辰 / 改日期 / 设时辰都**驳回并回错给 LLM**；`action` 不受限。`总览.md` 规则 12 补充说明。已测 8 例（驳回/放行）。

---

## 十、信息边界（跨层原则）🚧

### 问题

`history` 是全世界的真相，但**一个大模型同时扮 GM 与所有 NPC**，会把"梁峰私下做过的事"当成"NPC 也知道"。表现为 **NPC 全知 / 上下文泄漏 / 元游戏**（实测：出一趟远门回来，NPC 却知道你在外地干了什么）。

### 原则：可见性是一条跨层统一的轴

| 层 | 隔离键 |
|---|---|
| `char_memory` | `owner` |
| `history` / `current.jsonl` | `在场` / `知悉` / `公开度` |
| `lore` 知识库 | `visibility: public / gm_only / char:<名>` |

### 关键澄清：`在场` ≠ `知悉`

受害者、被事后告知者、听传闻者都构成知悉。故需三个概念：

| 字段 | 含义 |
|---|---|
| `在场` | 亲眼所见者 |
| `知悉` | 事后被告知/推断得知者 |
| `公开度` | `私密` / `传闻` / `公开` |

NPC X 的知悉集 = `在场∋X` ∪ `知悉∋X` ∪ `公开度≥传闻且能传到 X` ∪ `char_memory[owner=X]`；满足 **GM ⊇ 玩家/梁峰 ⊇ 每个 NPC**。

### 已定 ✅：GM 叙述与 NPC 对白拆成两次调用（两段式）

理由：这是唯一能**物理隔离**知悉集的办法，不依赖提示词自觉（与第二节"假硬核"同源——约束必须机械化）。

```
玩家输入
   │
   ├─ Pass 1  GM（客观）  上下文 = 全量规则 + 全量 history + 状态 + 本场在场人
   │           产出 = narration（世界/环境/后果）+ 舞台调度（谁在场、谁开口、立场）
   │           ✗ 不产出 NPC 直接引语
   │
   └─ Pass 2  NPC（主观，每个开口者一次，可并行）
               上下文 = 规则 + 该 NPC 知悉集（过滤后的 history + char_memory[owner]）
                        + Pass 1 给出的"本场事实/自身立场"
               产出 = 该 NPC 的 chat（台词 + 表情）
   │
   ▼
合并：按舞台调度排序 → [narration..., chat...] 事件流
```

- 代价：每轮 N+1 次 LLM 调用（N = 本场开口的 NPC 数）。缓解：只对**实际开口**的 NPC 调 Pass 2。
- **GM 知道全部真相以推动世界，但不得让 NPC 说出其知悉集之外的细节**——两者在两段式里天然分离。

### 待定 ❓

- **tag 从哪来**：让大模型输出 `{"type":"scene", ...}` 控制事件（便宜但会漏标，犯错的就是它）；或**小模型异步标注**（倾向：抽取而非生成，并入 `world_worker`）。
- **Pass 2 用哪个模型**：复用大模型保人物深度 vs 换更快模型。
- **传播机制**：`公开度` 随 `world_sim` 日推演演化（私密→传闻→公开，沿地理/关系网扩散 `知悉`）——"回扬州发现人尽皆知"应是**系统算出来**的。
- **校验**：重要 NPC 对话事后用小模型核对是否引用知悉集外事实（不阻塞）。

### 数据模型

`current.jsonl` 增加 `在场` / `知悉` / `公开度` / `scene_id`（把连续回合归为同一幕）。

---

## 十一、知识库层（正典检索投影）🚧

### 定位：与记忆层性质相反

记忆是"世界**发生过**什么"（chroma 即真相源）；知识库是"世界**本来**是什么样"（**md 是真相源，chroma 是可重建投影**）。

| | 记忆层 | 知识库层 |
|---|---|---|
| 内容 | 本局发生的事实/认知 | 史实/正典/日常参考 |
| 真相源 | chroma 本身 | `trpg-world/考据/*.md` + 正典 |
| 写入者 | 存档蒸馏（LLM） | 构建脚本（代码） |
| 变化 | 每局增长/淘汰 | 稳定，人工维护 |
| 检索过滤 | `owner` | `domain` / `era` / `visibility` |
| 可否进游戏状态 | 可 | **绝对不可** |

### 已定

- **独立库** `trpg-db/chroma_lore/` + `ingest_lore.py`（与 `init_GM_DB.py --reset` 隔离，互不误清）。
- **单 collection `lore` + metadata 过滤**（不拆多库，免 LLM 选库）：

  | metadata | 取值 |
  |---|---|
  | `source` | 出处（`梦粱录·卷十三` / `江湖势力/锦香宫.md`） |
  | `domain` | `daily` / `canon` / `history` / `geography` |
  | `era` | 适用年代（按当前游戏年过滤） |
  | `visibility` | 同第十节（`public` / `gm_only` / `char:<名>`） |
  | `confidence` | `史料` / `二创` / `推测` |

- **chunk 按标题切 + context 前缀**（`《梦粱录》卷二十·夜市 > …`），单块 200–500 字。
- **事实卡片，不倒原文**（原文文体会带跑 LLM，且长段命中率低）。
- **只读工具** `KB_query_tool(query, domain, era, visibility, n)` → 返回**带出处**的片段；注册进 `tools/registry.py`。
- **触发双轨**：LLM 主动调 + 引擎每轮预检索注入（规则层仍全量；正典只走检索）。

### 铁律 🔒

1. KB 结果**永不写入** `gm_memory` / `char_memory`（否则 GM 把"临安有夜市"记成"梁峰逛过夜市"）。
2. 注入时标注"这是**设定/史实参考**，不是本局发生的事"。
3. **无命中 → 明确兜底**（"考据未收录，按南宋常识处理"），**不允许编造**。

### 与 web search

KB 优先（离线、可溯源、无年代泄漏、无剧透失控）。真接 web search 须独立管线、结果不进 chroma/游戏状态、强制年代过滤；默认不接。

### 内容源

新建 `trpg-world/考据/`，从《梦粱录》《武林旧事》《蒙元入侵前夜的中国日常生活》等整理**事实卡片**；先索引现有 `trpg-world/` 正典跑通全链路。

---

## 十二、待定问题汇总

### 阻塞项

- 无（embedding 已定：统一 `lms.embedding_model`）。

### ⚑ 交接（本轮遗留 / 下一步）

- [ ] **⭐ `history` 滑动窗口 / 摘要** —— 长局撑爆上下文，**当前最大技术债**（TODO 第十一节）
- [x] ~~**待确认金钱持久化**~~ —— 已去掉请款/确认环节（`modify_money` 直接落账），不再适用
- [ ] **大跨度时间流逝规则** —— `总览.md` 补"住店/投宿只是订房，不等于睡到天亮；过夜须玩家明说"（规则热更免重启）
- [ ] **重启生效提醒** —— `trpg-server` 代码改动（money/engine/main/location/map_query/registry/ability/ui_events）+ 前端，**必须重启**（详见 STATUS.md 第十二节）
- [ ] **信息边界 / 知识库** —— 两大工程均**未动**（第十 / 十一节）

### 待定

- [x] **⑥** 玩家可见势力：独立文件 `trpg-world/势力介绍.json`（人工维护、已剔除剧透），后端 `GET /factions` 返回（✅ 2026-09-13）
- [ ] **⑦** `世界状态.json` 体积与注入策略（全量 vs 摘要 + 工具）
- [ ] **⑦** 活跃 → 不活跃 淘汰规则 🅿️ 搁置
- [x] **⑦** `get_character(name)` 工具（静态 + 动态；✅ 2026-09-13）
- [x] **⑧** `总览.md` 迁移到小模型上下文（`可用场景.md` 已删；场景枚举改扫前端资源）
- [x] **⑧** `ui_event` 的 kind 清单与协议（bg / music / money / minigame）
- [ ] **⑨** 小游戏事件类型与暂停/恢复语义
- [ ] **⑨** 音乐/战斗如何复用事件流
- [ ] **二** `update_ability` / `train_skill` / `evaluate_chaos`
- [ ] **历法** 新历＋农历双历、节气/节日/月相，与天气/世界推演/骰子事件联动
- [ ] **地图** `features` 表加 `description`（自由文本）+ `type`（语义分类），记录定时活动
- [ ] **地图** 地域特色重制（避免所有城市同一算法生成，江南/北方…各异）
- [ ] **地图** 世界地图（多 `map_id`、跨城距离/官道水路/旅行耗时）
- [ ] **信息边界** `current.jsonl` 加 `在场`/`知悉`/`公开度`/`scene_id`；两段式调用（GM 叙述 / NPC 对白）
- [ ] **信息边界** tag 来源（小模型异步标注 vs 大模型 `scene` 控制事件）
- [ ] **信息边界** `公开度` 随 `world_sim` 传播（私密→传闻→公开）
- [ ] **知识库** `chroma_lore` + `ingest_lore.py` + `KB_query_tool` + 引擎预检索
- [ ] **知识库** 建 `trpg-world/考据/`，整理史实/日常事实卡片
- [ ] **UI** 放弃确认换成自定义浮层（替换 `window.confirm`）

### 你的补充区

（在此处继续记录新的决策、推翻的理由、或新发现的问题）

---

## 十三、战斗系统 ✅（v0.1）

> 设计详见 `trpg-world/战斗系统.md`；本节记**架构决策与数据链**。

### 决策

- **战斗是独立子状态机，不复用 GM 工具循环**：`/battle/*` 自成一套（HTTP），战斗推进不经 `/action`。
- **事件边界**：GM 只在两处介入——①开战（工具 `start_battle` → UI 事件 `kind:"battle"`）②结束（结果 → `pending_notes` → 下一轮 GM）。**战斗过程不调用大模型叙事**（快）。
- **硬事实全归代码**（承总纲第 5 条）：命中 / 伤害 / HP / 内力 / buff / 移动 / 射程 / 胜负 全在 `tools/battle.py`；**模型没有任何数字输出权**。
- **AI 只做两件事**：①判玩家「思路」→ 只出「评价」枚举，代码查表成修正（只作用于伤害）；②阵营决策 → 只出 `{动作,目标,移动}`，代码校验降级。
- **模型可切**：思路判定默认小模型、战斗界面内可切大模型；设置存 `sessions/battle_settings.json`（**不进 `游戏数据/`、不进每轮状态块**）。
- **模拟战斗**：环境设定里直接开局，`模拟=True` 时不回写真实 `状态.json`。
- **定位：战棋**（TRPG 主干 + 战棋战斗模块）；**选定路线 B「深化为真战棋」**——补地形/寻路/借机攻击/多目标/技能体系/养成/战果写回（见 `战斗系统.md` §10、`TODO.md` §四）。
- **NPC AI 全归代码**（战术层 L2 枚举+打分 + L3 `clone` 前瞻）；小模型只负责玩家「思路」判定与 UI/推演。

### 分层与数据链

```
前端 battle.tsx ──HTTP──► main.py /battle/* ──► battle_session（单例/生命周期/写回）
                                                      │
                                        battle_runner（阶段机 + 战局快照）
                                                      │
                                   ┌──────────────────┴──────────────────┐
                                   ▼                                     ▼
                            battle_ai（AI）                        battle（数值·纯代码）
                                   │                                     │
                            小模型 / 大模型                    读：状态/属性/基本信息/招式表/武力排名
```

### 一回合

```
begin_round（定先手 + DoT + 内力回复）
  → 先手方阶段：玩家先动（判思路）→ 该侧 NPC 小模型一次
  → 后手方阶段：另一侧
  → end_round（buff 计时）
```

**每回合 ≤ 3 次模型调用**（玩家判定 1 + 友方 1 + 敌方 1；思路为空则 0 次判定调用）。

### 命中 / 伤害（实现版）

```
命中 = d100 + clamp(round((攻方兵器 − 守方轻功)/5), ±25) + 命中buff + 位置(背袭+15/夹击+8)
       <20 落空｜20–59 ×0.8｜60–89 ×1.0｜≥90 会心 ×1.5
伤害 = 威力 × 兵器/100 × 梯度系数 × 武器类型(利器1.25/钝器1.0/徒手0.9)
     × 五行克制(克1.3/被克0.8) × 位置(背袭1.3/夹击1.15)
     × (1 + 思路修正/100) × buff − 减伤
```

### 数据写回

- 战斗状态**只在内存**（`battle_session._RUNNER`），不落盘。
- 结束 → 玩家 生命/精力/伤势 → `游戏数据/状态.json`（模拟战斗跳过）；结果摘要 → `session.pending_notes` → 下一轮注入 GM。

### 实现记录（简）

- 模块：`tools/battle.py`（纯数值）、`battle_tactics.py`（**NPC 代码战术层 L2 Utility + L3 前瞻**）、`battle_runner.py`（阶段机）、`battle_ai.py`（玩家思路判定 + 可选小模型决策）、`battle_settings.py`（战斗设置）、`battle_session.py`（单例/梯度/写回）。
- 工具 `start_battle`（游戏工具 32→33）；UI 事件 kind `battle`；路由 `/battle/{state,action,settings,roster,sim,abort}`。
- 前端 `in-game/battle.tsx` + `styles/Battle.css` + `out-game/Menu.tsx`（模拟战斗）+ `GameController` 接入。
- 战斗 BGM：`ui_sim.battle_track_for()`（boss 绑定优先，否则通用战斗曲）。
- 实测：武器系数（利器 16 / 钝器 13 / 徒手 12）、流血上限 3、蓄力 3 层 ×2、背袭/夹击、防守 40% 减伤、思路判定小/大模型均顶住注入、梯度查表（`武力排名.md`，55 人）。
- 修复：循环导入（`battle_ai` 惰性导入 `llm`）、函数 `state()` 遮蔽单例（改 `game_state`）、背袭方向、移动后朝向、蓄力未定义、自动布位。
- **棋盘视觉**：等轴测 `BattleBoard.tsx`（居中 SVG、玩家西南/敌人东北）；实体系统（人物=锥+球、房/墙=长方体、河=凹陷、树）。
- **地形**：`Battle.terrain` + `blocked()`（房屋/墙阻挡）+ `reachable_cells()` + `state()["地形"]`；模拟战斗带演示地形。
- **BGM 选曲**：`ui_sim.battle_track_model()`（boss 绑定直取 + 小模型按「情绪+战况」选 + 代码回退）；3 首 boss 曲移入战斗清单。
- **AOE 选格子**：`skill_centers/skill_area/_is_aoe`；`state()["技能"]`；前端点格 + 区域预览。
- **修复**：`state.技能`→`state.战场.技能`（AOE 前端全失效）、橙色区域被蓝盖住、`会心阈值` 未实现（洞察暴击加成）。
- **NPC AI**：默认走**代码战术层**（`battle_tactics`：枚举 + 打分 + 一回合前瞻）；`TRPG_BATTLE_AI=model` 切回小模型。
  4B 曾把攻击目标填成自己 → 弃用其选招；代码 AI 能逼近 / 包抄背袭 / 夹击 / 集火 / 残血撤，`0.02s/回合`。
- **小模型 10s 硬超时**：`ask_json`（流式 + 看门狗）超时 `stream.cancel()` 真中断并返回 None；`TRPG_SMALL_TIMEOUT` 可调。
- **战斗稳定性**：`battle_session.submit` 防重入锁；玩家倒下/撤离即结束；`advance` 自走上限 2 回合；`decide_side` 限 `maxItems`。
