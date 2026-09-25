# 背景图 AI 重构素材包

把 `trpg-map/draw_tiles/song_kinds.py` 里每个 kind 展开成一个文件夹包：**参考图 + 提示词**。
脚本不调用任何生图 API，你拿着文件夹里的东西直接喂给任意生图 AI 即可。

## 用法

```bash
# 全部 116 个 kind
python trpg-client/scripts/background-pipeline/build_packs.py

# 只做一个 kind，先试水
python trpg-client/scripts/background-pipeline/build_packs.py --kind 青楼

# 参考图不想用硬链接（默认 hardlink，几乎不占空间）
python trpg-client/scripts/background-pipeline/build_packs.py --link copy

# 重刷已有包里的参考图
python trpg-client/scripts/background-pipeline/build_packs.py --force
```

产出在 `trpg-client/scripts/background-pipeline/packs/`。

## 文件夹结构

```text
packs/
├── 生成顺序.md              Agent 的作业清单（顺序 + 勾选进度）
├── 青楼/
│   ├── 说明.md              元信息、操作步骤、提示词全文
│   ├── 白天/
│   │   ├── 提示词.txt        直接复制粘贴
│   │   ├── 01_画舫.png       参考图，文件名数字即提交顺序
│   │   ├── 02_豪华的房间.png
│   │   ├── 03_客栈二楼大厅.png
│   │   └── 04_锦香宫.png
│   └── 黑夜/
│       ├── 提示词.txt
│       ├── 01_画舫.png
│       └── ...
└── 教坊/ …
```

## 操作流程

1. 打开 `<kind>/白天/`，参考图和 `提示词.txt` 一起提交给生图 AI。
2. 接着做 `<kind>/黑夜/`：把**刚生成的白天图**当第一参考，再加 `黑夜/` 里的参考图和提示词。
3. 两张图直接输出即可。整个流程不保存文件、不改名、不搬运。

## 无人空景（硬规则）

背景一律是**无人的空景**，人物由游戏叠加立绘。为了不让 AI 画人，三处同时设防：

1. `最高优先级`：单独成段放在提示词最前面，并列出必须排除的人物类型。
2. `禁止项`：独立禁止段落，结尾再次强调。
3. `画面核心`：清单里的描述**不含人群、摊贩、士卒、听众等人词**，只写建筑、陈设、器具、货物。

另外 `参考图通用说明` 会告诉 AI：参考图里若有人物，请直接忽略，不要抄进来。

若某个模型仍然画人，可在该 kind 的 `提示词.txt` 末尾手动追加：

```text
只输出空景，禁止任何人物与生物。
```

## 让 Agent 自己跑：`packs/生成顺序.md`

`packs/生成顺序.md` 是给执行生成的 AI / Agent 的作业清单：

- 232 项 → 已完成 2 个 kind（青楼、笔坊）后现为 228 项；完成一个 kind 就把它加进 `config.json` 的 `已完成`，它会从清单里消失。
- 文件开头写明了执行规则：**生成一项就勾掉一项，然后不停顿地继续下一项，不问、不停、不中途汇报**。
- 每项只要求「直接输出图片」：不保存、不改名、不搬运。
- 单项失败最多重试 2 次，仍失败就标 `- [!]` 并继续；全部跑完才汇总一次。
- 重跑 `build_packs.py` 时，已有的 `[x]` / `[!]` 会被保留，进度不丢。

把这句话给 Agent 即可：

```text
读 trpg-client/scripts/background-pipeline/packs/生成顺序.md，按里面的执行规则一直做下去，不要停。
```

## 白天与黑夜的关系

- **白天**：4 张同类旧背景当参考，确定画风、空间密度和镜头。
- **黑夜**：以**刚生成的白天图**为第一参考，再叠 4 张旧黑夜图，**锁死机位、透视、建筑结构和主要陈设**，只换光照与活动状态。

## 提示词的组成

由 `config.json` 拼装：

| 段落 | 来源 |
|---|---|
| 场景原型 / 画面核心 | `trpg-world/场景表.json` 的 `场景原型`（kind→原型/画面核心）+ `song_kinds.py` |
| 历史功能 / 位置倾向 | `song_kinds.py` 的 `note` 与 `zone` |
| 画面要求 | `config.json.固定要求` |
| 美术风格 | `config.json.美术风格` |
| 光照与材质 | `config.json.光照与材质` + `period_rules[时段]` |
| 参考图用法 | 包内实际文件名 + `reference_roles` + `参考图通用说明` |

想调风格、加禁止项、改分辨率，只改 `config.json`，重跑即可。

## 参考图怎么定的

- `group_profiles`：按 `group`（风月 / 百工 / 官署…）给的默认参考池。
- `kind_reference_overrides`：单个 kind 的覆盖，优先级最高。
- 参考场景名必须与 `config.reference_root`（现为 `D:\trpg仓库\背景_参考图`，原 `trpg-client/src/assets/背景/`）下的目录同名；同时间图缺失时按 白天 → 黑夜 → 黄昏 回退。

## 扩展 kind（`extra_kinds`）

`song_kinds.py` 之外的结构/内室/城外场景写在 `config.json.extra_kinds`（kind → 分组/zone/note/原型/画面核心，可选 `窄景`/`priority`）：

- `窄景: true` → 提示词多一段「局部窄景」（近景/一角/元素从简），供 38 个内室用；
- `priority: 0/1/2` → 清单分批（否则按原型查 `场景表.json.分批`）；
- 参考图走 `kind_reference_overrides`。

产出图放 **`trpg-client/src/assets/背景_重构/<城内|城外|室内>/<场景>/{白天,黑夜}.png`**（分类目录 = 唯一闸门，见 `README/09 §13.1`）。

## 文件说明

- `config.json`：全部可调项（`source_kinds` / `scene_table` / `reference_root` / `extra_kinds` / 预设 段）。
- `build_packs.py`：生成器（读 `场景表.json` 的 `场景原型` / `分批`）。
- `packs/`：产出（已 gitignore，可随时重跑；2026-09-25 清理时删过，重跑 `build_packs.py` 即恢复）。
  根目录只有一份 `生成顺序.md`，其余全是 `<kind>/{白天,黑夜}/` 素材包。
