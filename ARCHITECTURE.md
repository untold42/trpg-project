# ARCHITECTURE.md — 架构决策记录

> 本文档记录 trpg-project 的**架构决策**与**实现状态**，以及**尚未定论的问题**。
> 只写架构与契约，不写实现代码。随时可推翻重议——推翻时请在此文件留下记录。
>
> 状态图例：✅ 已定/已完成 ｜ 🚧 待实现 ｜ 🔧 待修改 ｜ ❓ 待定

最后更新：地基（引擎 / 事件流 / 工具注册表 / 记忆层 / 存档）与本局生命周期、UI 重构已完成。

---

## 0. 一句话总纲

把系统从"一堆脚本各写各的"收敛成**分层的、单一真相源的、事件驱动的**结构：

```
内容层（正典） ──► 引擎层（回合） ──► 表现层（事件流）
        ▲                 │
        │                 ▼
      记忆层（存档蒸馏）  状态层（实时）
```

核心原则三条：

1. **单一真相源**：每类信息只有一个源，其余都是投影。
2. **类型化接口**：领域数据只能通过专用接口读写，禁止裸文件 I/O。
3. **状态实时、记忆离线**：状态每次现拼；记忆在存档时批量蒸馏。

---

## 一、分层总览

| 层 | 内容 | 源在哪 | 访问方式 | 状态 |
|---|---|---|---|---|
| **规则层** | `trpg-world/主持人/*.md`、`总览.md` | md | 全量注入 system | ✅ |
| **正典层** | `trpg-world/角色静态档案/`(55)、`江湖势力/`、`世界.md` | md | 按需检索 | 🚧 检索接口未做 |
| **记忆层** | chroma（`gm_memory` / `char_memory`） | chroma | 局内只读检索；存档时写入 | ✅ |
| **人物视图** | `trpg-world/角色动态档案/{活跃,不活跃}/*.md` | 推演投影 | NPC 登场时读档 | 🚧 |
| **状态层** | `trpg-server/tools/游戏数据/*.json`（含 `世界状态.json`） | JSON | 每次 LLM 调用现拼 | ✅ |
| **过程日志** | `trpg-server/sessions/current.jsonl` | 日志 | 每轮追加，唯一"边玩边写" | ✅ |
| **世界推演** | 宏观时间线 + 活跃人物线程 | 小模型（Qwen3-4B） | 异步，每游戏日一次（第七节） | ✅（活跃名单待自动化） |

---

## 二、状态层 ✅

### 决策

- **`history` 是真状态**（过程），必须持久化。
- **状态在每次 LLM 调用时现拼，且上下文中只出现一次、永远最新**。
  理由：状态必然影响叙述（"有一万两却不知道"会写偏），但快照会过期，不能塞进 `history`。
- **`history` 只保留纯叙事**（user / assistant 正文），状态与工具中间消息都不进 `history`。
- **`turns.jsonl` 每轮追加**：唯一"边玩边做"的更新；一次磁盘 append 成本可忽略，换崩溃安全。
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
- 工具：`DB_query_tool` / `DB_add_and_update_tool` / `DB_query_tool_in_saving` / `check_DB_length`，均按 `collection` 寻址，角色必带 `owner`。

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
  2. 角色档案 LRU 淘汰 → `char_memory`（🚧 待第 ⑦ 步：需活跃档案）
  3. 代码誊写 `游戏存档.md` + 归档
  4. 重置**会话**（history + turns.jsonl）；**玩家状态保留**（故事连续）

> 注：「动态档案 = 存档时快照」已被**世界推演**修订——活跃档案随推演每游戏日更新（第七节）。

### 旧格式映射（`存档流程.md` 已照此重写）

| 旧 type | 新归属 |
|---|---|
| `event`（客观事实） | `gm_memory` |
| `information`（谁得知/认为/打算什么） | `char_memory`，`owner` = 那个人 |
| `relationship` | **拆两半**：客观结盟/敌对→`gm_memory`；A 对 B 的好恶→`char_memory[owner=A]` |

### 关键规则

- **IC / OOC**：`【场外】` 行是玩家对主持人的元对话，**不蒸馏**（见第六节）。
- **id 命名**：`gm_N` / `char_N`，两库各自计数。

---

## 四、内容层 ✅

### 决策

- **`trpg-world/` 是正典唯一来源**。对 LLM 只以两种方式进入：提示注入 / 类型化检索。
  （`file_tools` 的 `WORKSPACE` 只到 `tools/`，本来就够不到 `trpg-world`。）
- **规则层全量注入**：`主持人/*.md`（小、必须每轮在场）。
- **正典层按需检索**：角色静态档案(55)、势力档案、世界设定（大、引用型，全量注入会稀释注意力）。🚧 检索接口未做。
- **势力介绍动态化**，内容放 `trpg-world`。但——

> **动态 ≠ 把 GM 笔记给玩家看。** `trpg-world/江湖势力/*.md` 含剧透（锦香宫实为泥教人间道、释明暗算唐门等）。必须分两级：

```
trpg-world/江湖势力/*.md   ← GM 正典（真相），只进 LLM
        │ 投影
        ▼
玩家可见的势力条目          ← 画廊读这个，来自「玩家已知」
   { name, desc, detail, image }
```

"玩家已知"本身是游戏状态，由 GM 通过接口（如 `update_faction_intro`）动态维护，前端经 `GET /factions` 读取。

### 角色档案

- `角色静态档案/`（55 个 md，带 `node_type: memory` frontmatter）= 正典。
- `角色动态档案/{活跃,不活跃}/` = 记忆的近端投影；随世界推演每游戏日更新（第七节）。目前为空。

### 待办 🔧

- `势力介绍.ts` 从"数据源"退化为"类型定义 + 兜底缓存"，改读 `GET /factions`。（第 ⑥ 步）
- `find_specific_character.py` **路径写错**（`角色静态档案.md` 是目录）；升级为 `get_character`（静态 + 活跃动态）。（第 ⑦ 步）

---

## 五、引擎层 ✅

### 结构（已实现）

```
engine.py
  ├─ GameSession       : history + turns.jsonl + 开局快照 + 前情
  ├─ TurnRunner.run(input, mode) -> list[Event]
  ├─ TurnRunner.run_save(transcript, rules)   # 存档蒸馏专用回合
  └─ 事件流组装        : 叙事指令 + 工具 UI 事件
save_pipeline.py       : POST /save 的收尾管线
tools/registry.py      : 工具 schema + 实现的单一真相源
main.py                : bootstrap + 路由
```

- `main.py` 退回纯路由 + bootstrap；不再持有 history、不再写工具循环。

### 已定 ✅

1. **开局上下文**：`规则 + 状态(现拼)`；角色动态档案**不进开局上下文**，改由工具 `get_character(name)` 按需读（🚧 未做）。
2. **"存档"是引擎的特殊命令**：`POST /save` 独立收尾管线（→ 第六节的"本局生命周期"）。
3. **状态块位置**：messages **末尾**。

### 单一工具注册表（已实现）

- `tools/registry.py`：`_ENTRIES` 一处定义 `(name, schema, fn)`，派生：
  - `TOOLS = {name: (schema, fn)}`
  - `ALL_TOOLS`（`llm.send_messages` 用）
  - `TOOLS_MAP`（`engine.TurnRunner` 用）
- 当前 **32 个工具**；新增工具只需在 `_ENTRIES` 加一行，不必再改 `llm.py` / `main.py`。

### 本局生命周期（已实现）

```
本局进行中 ──┬── 存档 POST /save       → 蒸馏 + 誊写/归档 + reset（状态保留）
             ├── 放弃本轮 POST /abandon → 回滚状态到本局开始 + 丢弃日志 + reset
             └── 中途退出/刷新         → 本局保留；GET /history 续玩
```

- **开局快照**：`GameSession` 在本局开始时把 `游戏数据/*.json` 存到 `sessions/run_start_state.json`；`abandon` 用它回滚。
- `reset`（存档用）保留现状；`abandon`（放弃用）先回滚快照。两者都重拍快照、重读前情、清空 `turns.jsonl`。
- "重开新档"（清空记忆/状态/前情）暂不做。

### 存档管线（已实现）

```
POST /save
 1. 代码：turns.jsonl ──► 逐字叙事 transcript（按游戏内时间分段）
 2. LLM ：读《存档流程.md》蒸馏 ──► gm_memory / char_memory
 3. 代码：transcript ──► 游戏数据/游戏存档.md（下一局读作前情）
 4. 代码：归档 ──► tools/归档存档/<起>~<止> 存档.md
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
- **历史面板 / 续玩**走 `GET /history`（读 `turns.jsonl`）；前端不再维护平行的 `historyLog`。
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
- `mode:"gm"` → 玩家对主持人的场外话（OOC）。后端组装 `玩家的对主持人说的话：<input>`。

`mode` 存进 `turns.jsonl`。存档誊写时：IC → `你说：「…」`；OOC → `【场外】…` 且**禁止蒸馏**。

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

### 背景切换（bg 迁移）🚧

- `bg` 已从 `instruction` 删除；背景改由 UI 事件 `kind:"bg"`（`data:{position,time}`）控制。
- 前端已就绪：`GameController` 收到 `kind:"bg"` 即切背景（`in-game/background.ts` 负责 地点+时辰→图），`GameScene` 只接收 `background` prop。
- **迁移点**：`trpg-world/主持人/总览.md`（输出格式）与 `可用场景.md`（地点清单）仍写给**大模型**，应改由**小模型**承担。（第 ⑧ 步）

### 待定 ❓

- 小游戏事件类型与暂停/恢复语义。
- 前端浮层结构（`MiniGameHost` + 懒加载注册表）。

---

## 七、小模型层（ui_event + 世界推演）

本地小模型：**Qwen3-4B**（LM Studio，`qwen/qwen3-4b-2507`，已加载）。与大模型**并列**的另一条生成链路。

### 7.1 两条管线

| | `ui_event` | 世界推演 |
|---|---|---|
| 时机 | 同步，每轮 | 异步，随游戏日 |
| 延迟敏感 | 高（背景/音乐随场景） | 无（off-screen） |
| 输出 | 极小（kind + 字段） | **两个枚举值** |
| 触发 | 当前叙事 / 场景 | 推进一个游戏日 |
| 状态 | 🚧 未做（第 ⑧ 步） | ✅ 已实现 |

**模型分工**：大模型产 `chat`/`narration`（玩家眼前）；小模型产 `ui_event` + off-screen 推演。

### 7.2 世界推演的核心决策（已实现）

> **小模型只做离散采样，具体叙事交给大模型。**

```
每游戏日，对每个活跃人物：
    小模型 ──► { 地点, 事件类型 }          ← 只有两个值，幻觉面趋近于零
    代码   ──► 顺利度（加权掷骰，顺+平 ≈ 90%）
        └──► 写入 世界状态.人物线程

玩家遇到该人物时：
    大模型 ──► get_character(name) 读 静态档案 + 线程
            ──► 自行演绎出既具体、又合正典的叙事
```

**为什么只出两个值**：4B 生成"具体事实"必然与正典冲突，且会被固化成假事实；
抽象成离散状态后它**无从编错**，由读过全部正典的大模型负责演成情节。
（实测：不逼它极简时，它会把字段写成整段小说、单次 19s+；严格提示后降到 0.5-2s。）

- **事件类型**（8 选 1）：营生 / 修行 / 社交 / 赶路 / 生活 / 公务 / 寻医 / 变故
- **顺利度**（代码掷骰，5 档）：大顺 5 / 顺 45 / 平 45 / 不顺 4 / 大挫 1
- **地点**：自由文本（信任小模型不会让人日行千里）

### 7.3 触发与异步（已实现）

```
每次 /action 结束 ──► world_worker.on_turn_end()
    比对「已入队游标」与当前游戏日期
    跨 N 天 ──► 入队 N 个「日任务」（超过 MAX_TICKS=10 则跳过早先的）
                        │  daemon 线程（不阻塞玩家）
                        ▼
   单日：触发宏观 → 对每个活跃人物采样（与玩家同地点者豁免）→ 写回 → 游标推进
```

- **入队游标与推演游标分离**：避免"没跑完就被重复入队"；进程重启后自动补缺口。
- **事务性**：写回成功才推进游标；`放弃本轮`/存档时 `clear()` 清队（底层状态已变）。
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
      人物线程: {名: {地点, 最新:{日期,类型,顺利度}, 流水:[...上限30]}} }
trpg-world/角色动态档案/{活跃,不活跃}/*.md   ← 近记忆文本（大模型读）
trpg-world/世界推演/宏观时间线.json + 推演规则.md
chroma                        ← 存档时蒸馏（大模型，重）
```

> **修订**：此前「动态档案 = 存档时快照」改为——活跃档案随推演更新。
> 「存档时才写」约束的是**蒸馏**（重 LLM），不是档案文件（轻磁盘写）。

### 7.6 大模型如何获知世界

1. **`世界状态.json` 及时可见**：在 `游戏数据/` 下，被「状态现拼」自动纳入每次 LLM 调用 ⇒ 永远最新。
2. **NPC 登场即读档**：调工具 `get_character(name)`（待做），返回 `角色静态档案/<名>.md` + `角色动态档案/活跃/<名>.md`，必要时再查 `char_memory[owner]`。

### 7.7 硬依赖

- **时间必须权威**：任何「过夜/赶路/等待」的叙述，大模型必须调用 `update_time`；否则日期不变、推演不触发。需写入 `总览.md`。🚧

### 待定 ❓

- **活跃人物名单从哪来**：目前"扫 `活跃/`"，但**谁往里面放人尚未自动化**（计划存档流程写入）。
- 活跃 → 不活跃的淘汰规则。
- `get_character(name)` 工具（静态 + 活跃动态）。
- `ui_event` 的 kind 清单与协议（第 ⑧ 步）。

---

## 八、已知问题 / 不一致清单

| # | 问题 | 位置 | 状态 |
|---|---|---|---|
| 1 | 系统提示里的状态是开机快照，永不刷新 | `main.py` | ✅ 由"状态现拼"解决 |
| 2 | `find_specific_character` 路径写错（永远返回“没找到”） | `tools/find_specific_character.py` | ✅ 已修（绝对路径+目录，返回 dict）；后续升级为 `get_character`（第 ⑦ 步） |
| 3 | chroma 初始化路径与读取路径不一致 | `init_GM_DB.py` vs `main.py` | ✅ 已修正，统一到 `trpg-db/chroma_db` |
| 4 | embedding 模型三处不一致 | `main.py`/`init_GM_DB.py`/`DB.py` | ✅ 统一用 `lms.embedding_model` |
| 5 | 存档流程用 file 工具写 `游戏数据/`，被 guard 拦 | `存档流程.md` | ✅ 改为代码誊写 |
| 6 | 存档流程 off-by-one（蒸馏上一局） | `存档流程.md` | ✅ 已修正：蒸馏本局 |
| 7 | 前端属性/金钱是写死的假数据 | `GameController.tsx` | ✅ 已接 `/state` |
| 8 | 工具双份登记 | `llm.py` + `main.py` | ✅ 已合并为 `tools/registry.py` |
| 9 | 内容双写（势力介绍） | `势力介绍.ts` vs `trpg-world` | 🚧 待第 ⑥ 步 |
| 10 | `角色动态档案/` 为空且无机制 | `trpg-world/角色动态档案/` | 🚧 待第 ⑦ 步 |
| 11 | `属性.json` / `混乱度.json` 无写接口 | `游戏数据/` | 🚧 待补 `update_ability` / `evaluate_chaos` |
| 12 | 放弃确认用原生 `window.confirm`，与 UI 不搭 | `GameController.tsx` | 🚧 待换自定义浮层 |
| 13 | 工具返回类型不统一（str / dict / int / list） | `tools/*.py` | 🔧 目前都能被 `json.dumps`，新工具需注意 |
| 14 | 活跃人物名单无人写入（`角色动态档案/活跃/`） | `trpg-world/角色动态档案/` | 🚧 目前手放；计划存档流程写入 |
| 15 | **外部程序打开 `chroma_db` 会让 chromadb 静默卡死** | `trpg-db/chroma_db` | ⚠️ 已知坑：Rust 内核启动要拿写锁，被占则无输出死等（如 DB Browser for SQLite）。运行前先关掉 |
| 16 | **`check_DB_length` 式编 id：删过条目后会撞 id，而 chroma 对重复 id 静默丢弃 → 记忆悄失** | `tools/DB.py` | ✅ 已修：id 由代码 `_next_id`（max+1）分配，LLM 不再编 id（32 工具） |

---

## 九、迁移顺序

```
地基（互相咬合）：
  ① engine.py + GameSession + turns.jsonl 落盘        ✅
  ② 统一事件流（含 /state、/history）                 ✅
  ③ 单一工具注册表                                    ✅

记忆层：
  ④ 两 collection + owner；修 init 路径与 embedding   ✅
  ⑤ 存档流程重写（代码誊写 + LLM 蒸馏 + 归档）          ✅（LRU 待 ⑦）
  本局生命周期（存档 / 放弃 / 续玩）                    ✅

内容层：
  ⑥ /factions 投影 + 玩家可见势力接口                  🚧

小模型层：
  ⑦ 世界状态.json + 日推演异步 worker + 宏观时间线      ✅
  ⑧ ui_event 管线（把 bg 从大模型提示词迁到小模型）      🚧

能力扩展（此时都只是"加事件类型"）：
  ⑨ 小游戏 / 音乐 / 战斗                               🚧
```

### 实现记录（简）

- **① 引擎拆分 + 过程日志**：`engine.py`（`GameSession` / `TurnRunner`）；`state_manager` 加 `snapshot()`；日志 `sessions/current.jsonl`。
- **② 统一事件流**：`tools/ui_events.py`；`TurnRunner` 收集并剥离 `_ui_events`；`GET /state`；前端 `ui_event` 类型 + 拆分 UI 事件。
- **bg 迁移**：删 `bg` 类型；新增 `in-game/background.ts`；`GameScene` 改为接收 `background` prop；`GameController` 处理 `kind:"bg"`。
- **③ 单一工具注册表**：`tools/registry.py`（脚本从旧代码生成，零错配）；`llm.py` 缩到客户端；`main.py` 去工具导入。
- **④ 记忆层双库**：`gm_memory` / `char_memory`；`tools/mem_store.py`（懒加载）；`DB.py` 按 collection+owner；修 init 路径与 embedding。初始化脚本改为**只建结构、不写入任何内容**（`--reset` 可重建）。**id 由代码分配**（`_next_id` = max+1），LLM 不再编 id；`check_DB_length` 退出工具集。
  - ⚠️ chroma 的 `delete()` 是**逻辑删除 + 打墓碑**：`count()` 归 0，但写前日志 `embeddings_queue` 与 HNSW 向量段仍留痕迹。**彻底清空只能 `init_GM_DB.py --reset`**。
- **⑤ 存档流程**：`save_pipeline.py`；`TurnRunner.run_save`；`存档流程.md` 重写；`POST /save`；IC/OOC 输入模式与 `【场外】` 不蒸馏。
- **历史面板 + 续玩**：`GET /history`（`{active, lines, tail}`）；删 `historyLog`；进入游戏自动续上最后一幕。
- **放弃本轮**：开局快照 `sessions/run_start_state.json`；`POST /abandon` 回滚状态。
- **UI 重构**：顶层按钮收敛为 主持人/行动/历史记录/数据；存档/放弃/地图/势力/返回入「菜单」；`save_game` 工具退役（32 工具）。
- **工具审计**（33 个）：schema↔函数签名静态对齐 **0 问题**；运行时逐个调用（含负例）全部正常。
  修复 `DB_add_and_update_tool`：不带 `time` 时 metadata 为空被 chroma 拒绝（已在存档蒸馏路径上）——改为 `time` 始终写入。
  `find_specific_character` 路径 bug 已修（绝对路径 + 目录，返回 dict）；后续升级 `get_character`。
- **⑦ 世界推演**（2026-09-13）
  - `tools/small_model.py`：Qwen3-4B 封装，`respond(response_format=<JSON Schema>)` + `res.parsed`；严格提示后 0.5-2s/次。
  - `tools/world_state.py`：世界状态读写（游标 / 宏观 / 定时线 / 人物线程）、日期差、活跃名单（扫 `角色动态档案/活跃/`）。
  - `tools/world_sim.py`：单日推演——小模型只出 `{地点,事件类型}`，顺利度**代码加权掷骰**（顺+平≈90%）；宏观按日期触发；在场豁免（与玩家同地点者跳过）。
  - `tools/world_worker.py`：异步队列 + daemon 线程；入队/推演游标分离；MAX_TICKS=10 大跨度跳过；`clear()`；`TRPG_WORLD_SIM=0` 总开关。
  - `engine.py`：每轮结束调 `on_turn_end()`；`reset`/`abandon` 清队；开局快照含 `世界状态`（首次不存在时补空白）。
  - 内容：`世界推演/宏观时间线.json`（19 条，1220-02~1224-09，参照南宋嘉定年间）+ `推演规则.md`。
  - 已测：宏观按日期触发、在场豁免、掷骰分布（顺+平=90.2%）、入队/去重/清队/大跨度跳过、快照含世界状态。

---

## 十、待定问题汇总

### 阻塞项

- 无（embedding 已定：统一 `lms.embedding_model`）。

### 待定

- [ ] **⑥** 玩家可见势力由谁维护（GM 工具动态写 vs md 标记抽取）
- [ ] **⑦** 活跃人物名单自动化（谁往 `角色动态档案/活跃/` 放人）
- [ ] **⑦** `世界状态.json` 体积与注入策略（全量 vs 摘要 + 工具）
- [ ] **⑦** 活跃 → 不活跃 淘汰规则
- [ ] **⑦** `get_character(name)` 工具（静态 + 活跃动态）
- [ ] **⑧** `总览.md` / `可用场景.md` 从大模型提示词迁移到小模型上下文
- [ ] **⑧** `ui_event` 的 kind 清单与协议
- [ ] **⑨** 小游戏事件类型与暂停/恢复语义
- [ ] **⑨** 音乐/战斗如何复用事件流
- [ ] **二** `update_ability` / `train_skill` / `evaluate_chaos`
- [ ] **UI** 放弃确认换成自定义浮层（替换 `window.confirm`）

### 你的补充区

（在此处继续记录新的决策、推翻的理由、或新发现的问题）

- 
