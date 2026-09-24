# -*- coding: utf-8 -*-
"""
director.py
===========
「导演」角色：**每局跑一次**，产出一份《导演简报》，常驻大模型上下文。

职责（不是 GM、不写正文）：
    替 GM 做减法——把握主线、推进节奏、收束堆积的线索、盯玩家体验。
    GM（DeepSeek）擅长细枝末节，容易困于细节不敢收线；导演站在全局给出大方向。

为什么用 GLM（智谱）：
    它比本地 4B 强、比 DeepSeek 免费，但很慢（一次 40–200s）——所以**只异步跑、每局一次**，
    不进任何人的等待路径。走 OpenAI 兼容端点，**不引入新依赖**。

设计：
    - 触发：`engine.GameSession` 开局（__init__/reset/abandon）异步生成一次；一局顶多 7 个游戏日，常驻即可。
            续玩时若发现上次崩溃残留的「生成中」→ `recover_stuck()` 收尾 / 重跑。
    - 输入：**《故事大纲》**（system，`trpg-world/故事大纲.md`，热读）
            + 上一局逐字存档（`游戏数据/游戏存档.md`）——**不给现成的「悬着」清单**，让它自己找。
            首局无前情时，退而用当前状态/开局设定当材料（否则永远不跑）。
    - 存储：`游戏数据/导演简报.json` ⇒ 自动进入「状态现拼」，每轮注入 DeepSeek。
    - 降级：失败/超时/429 → 保留上一版；从未成功 → 内容为空（不注入噪音）。永不阻塞。
    - 开关：`TRPG_DIRECTOR=0` 关闭。

⚠️ **信息分层**：大纲含重剧透（身份/结局/瑞杏的棋局），**GM 永远看不到**。
    简报是**唯一**把大纲方向送进 GM 的通道 → 简报必须「翻译」成 GM 能执行的线索，
    **不得原样剧透底牌**（见 `SYSTEM` 铁律 8 与 `OUTLINE_HEADER`）。

环境变量：`GLM_API_KEY`（必需）、`GLM_MODEL`（默认 glm-4.5-flash）、`GLM_TIMEOUT`、`GLM_MAX_TOKENS`。
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

from dotenv import load_dotenv

from tools.核心.state_manager import state

ROOT = Path(__file__).resolve().parent.parent.parent.parent
load_dotenv(ROOT / ".env")

#: 故事大纲（导演专用·含剧透·不喂 GM）；热读，改文件免重启。
OUTLINE_PATH = ROOT / "trpg-world" / "故事大纲.md"

ENABLED = os.environ.get("TRPG_DIRECTOR", "1") != "0"
MODEL = os.environ.get("GLM_MODEL", "glm-4.5-flash")
BASE_URL = os.environ.get("GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
TIMEOUT = float(os.environ.get("GLM_TIMEOUT", "900"))
MAX_TOKENS = int(os.environ.get("GLM_MAX_TOKENS", "16000"))
RETRIES = int(os.environ.get("GLM_RETRIES", "3"))

STATE_KEY = "导演简报"
NOTE = "幕后简报：仅供把握节奏与取舍，不得复述、不得出现在叙事里"

#: 导演专属底牌词——**不得进简报**（简报会进 GM 上下文）。
#: 千灯楼 / 极乐教 / 尸心丹 已在 `主持人/世界.md`，GM 本来就知道，故不在列。
SPOILER_TERMS = [
    "五神共选", "共选之子", "多周目", "轮回", "弑神",
    "神的底牌", "棋盘外", "幸福牢笼", "大一统",
]

#: 代码兼底用的中性改写（重试后仍命中时，就地消弧，保结构、不泄底）
SPOILER_REWRITE = {
    "五神共选": "来历成谜",
    "共选之子": "来历成谜",
    "多周目": "异数",
    "轮回": "异数",
    "弑神": "欲灭尽觉醒者",
    "神的底牌": "最后的变数",
    "棋盘外": "局外",
    "幸福牢笼": "安稳的秩序",
    "大一统": "一统天下",
}


def scan_spoilers(text: str) -> list[str]:
    """返回命中的剧透黑名单词（代码兼底，不靠模型自查）。"""
    return sorted({w for w in SPOILER_TERMS if w in (text or "")})


def sanitize(text: str) -> str:
    """把黑名单词就地改写成中性词（仅当重试后仍命中才用）。"""
    for bad, good in SPOILER_REWRITE.items():
        text = text.replace(bad, good)
    return text

# ---- 提示词 v5（实测版）：v4 + 接《大纲》 + 防剧透(黑名单/禁点名) + 强制取舍 + 防漏自查 ----
SYSTEM = """\
你是武侠叙事游戏（南宋·架空江湖）的「导演」，负责**叙事结构**，不是 GM、不写正文。

你的核心职责是**替 GM 做减法**：
- GM 容易困于细节、不敢收线，导致主线停滞、疑点越堆越多；
- 你必须**果断取舍**：留下最该推进的少量线，其余的明确「冷藏」或「砍掉」。

铁律：
1. **只给方向与建议**，不下命令，不替玩家决定，不写正文。
2. **宁可砍错，也不要什么都"推进"**——清单越长越失败。
3. 站在**玩家体验**角度：此刻玩家有没有目标感？会不会无聊或困惑？关系是否失衡？
4. 每条建议要**具体到动作**（谁、在哪、做什么），不要"应该有所交代"这类空话。
5. 全文 **≤ 500 字**，短条目，不复述剧情、不展开分析。
6. **防漏铁律**：凡「玩家花过时间 / 许过承诺 / 起过疑心」的东西，必须出现在
   「主线 / 支线 / 冷藏或砍」三者之一——**不许凭空消失**。做减法不等于漏事。
7. **查主角行动**：主角过去做过的事（去过哪、答应过谁、办过什么差事、惹过谁），
   有没有**结果未交代**的？有就必须列入。**不要假设任何现成清单就是全部**——自己从正文里找。
8. **服务主线、但绝不剧透**：你手上有《故事大纲》（下一条 system 消息，**只有你能看**）。
   简报要让当前局面朝**大纲的主线方向**走；若存档与大纲冲突，以大纲**【已定】**为准。
   但——**简报会被逐字注入 GM 上下文，GM 没有大纲**，所以你写进去的每个字都会变成 GM 的「已知」。
   ⚠️ **【剧透黑名单】任何一条都不许出现在简报里**：
   `五神共选 / 共选之子 / 多周目 / 轮回 / 弑神（者） / 神的底牌 / 棋盘外的人 / 幸福牢笼 / 大一统的幕后推手`
   → 要把它**翻译成当下的事件、人物与钩子**。需要指代梁峰时，只写**可观察层**：
   「一个五行俱全却全为 0、来历不明的怪人」；需要指代那盘棋时，只写「瑞杏似乎在下一盘大局」这种**表层暗示**。
9. **【待定】/【提议】不是正典**：大纲里未拍板的内容，**不得当作事实**推进或引用。
10. **简报里的「主线」是「本局这一段的戏」，不是全书主题。**
   不要拿「梁峰是谁 / 天下终局」当主线——那不是 GM 此刻能演的东西。
11. **禁止项也不得点名底牌**：错误示范——「不得揭示梁峰是五神共选之子」（这句话本身就是泄底）；
   正确写法——「不得直说他那身五行之力的来历」。黑名单里的词，**连否定句、禁止句、举例句都不许出现**。
"""

OUTLINE_HEADER = """\
===== 故事大纲（正典·含重剧透·**只有你能看，GM 永远看不到**）=====
以下是本作的故事骨架：主线、瑞杏的棋局、梁峰的身份、揭示节奏、多结局。
用法：
- 据它**定方向**；把大纲翻译成 GM 能执行的**当下线索与方向**，让主线通过事件、人物、钩子自然浮现。
- 只有标注**【已定】**的才算正典；**【待定】/【提议】**不得当正典使用。

⚠️ **输出前必做自查（违反即事故）**：以下是**剧透黑名单**，你的简报里出现任何一个都算失败，必须改写：
    五神共选、共选之子、多周目、轮回、弑神、弑神者、神的底牌、棋盘外的人、幸福牢笼、大一统的幕后推手。
- 指代梁峰 → 只写可观察层：「五行俱全却全为 0、来历不明的怪人」。
- 指代瑞杏的谋划 → 只写表层暗示：「她似乎在下一盘很大的棋」。
- 指代恶势力 → 用**当下可见的行为**（散邪术、抓觉醒者），不要用「弑神者」这个定性词。

"""

USER_TMPL = """\
请阅读下面的游戏存档，输出《导演简报》，严格按以下八节（**总字数 ≤ 500**）：

## 一、当前局面
（≤3 行：阶段 + 玩家此刻的目标感/心理状态；若这段存档本就是日常戏、没推进任何主线，直接点明）

## 二、主线（只留 1 条）
（**本局这一段的戏**，不是全书主题；一句话：卡在哪 / 下一拍该发生什么）

## 三、支线（最多 2 条，按优先级）
（每条一行：是什么 / 埋了多久 / 为什么值得留）

## 四、冷藏或砍掉（必须穷尽）
（格式：`线索 —— 冷藏/砍 —— 一句理由`）

## 五、本阶段禁止
（≤3 条；防止信息过载与剧情停滞）

## 六、下一步建议（最多 2 条，按优先级）
（每条：具体动作 + 为什么 + 预期效果）

## 七、自查：所有未回收的线（必须穷尽）
（自己从正文里找，**不要依赖任何现成清单**）：
（a）玩家花过时间 / 许过承诺 / 起过疑心的东西；
（b）**主角此前行动中结果未交代的**（去过哪、办过什么差事、答应过谁）。
逐条列出并注明它落在「主线/支线/冷藏砍」的哪一处；若确实没有，写「无」。

## 八、输出前自查
（从上面的铁律 8 / 大纲标题里的【剧透黑名单】逐字检查；有则改写后再输出。无则写「无剧透」）

---
存档如下：

{text}
"""

_lock = threading.Lock()
_running = False
_pending: str | None = None   # 运行中又被请求的最新材料：跑完接着跑它，保证「最后一次赢」
_error = ""
_outline_cache: tuple[float, str] | None = None


def outline_text() -> str:
    """热读《故事大纲.md》（改文件免重启）。缺失/失败返回空串。"""
    global _outline_cache
    try:
        mtime = OUTLINE_PATH.stat().st_mtime
    except OSError:
        return ""
    if _outline_cache and _outline_cache[0] == mtime:
        return _outline_cache[1]
    try:
        text = OUTLINE_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    _outline_cache = (mtime, text)
    return text


def _first_material() -> str:
    """首局（无前情）的兜底材料：当前状态 + 开局设定，供导演找开场钩子。

    没有它，首局 `previous_story` 为空 → 导演永远不跑（这正是「第一场戏缺钩子」的成因之一）。
    """
    payload = {
        "基本信息": state.load("基本信息", {}),
        "状态": state.load("状态", {}),
        "属性": state.load("属性", {}),
        "难度": (state.load("难度设置", {}) or {}).get("难度", ""),
    }
    try:
        body = json.dumps(payload, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        body = str(payload)
    return (
        "【首局·尚无上一局存档】\n"
        "这是新档的第一局，还没有任何剧情发生。下面是玩家开局时的状态与设定；\n"
        "请据此 + 《故事大纲》，给出**开局阶段**的导演简报。\n"
        "尤其要指出：**第一场戏的钩子该往哪个方向设**——如何把玩家自然拉进主线、又不剧透。\n\n"
        + body
    )


def _client():
    from openai import OpenAI

    key = os.environ.get("GLM_API_KEY")
    if not key:
        raise RuntimeError("缺少 GLM_API_KEY")
    return OpenAI(api_key=key, base_url=BASE_URL, timeout=TIMEOUT, max_retries=0)


def brief() -> dict:
    d = state.load(STATE_KEY, {})
    return d if isinstance(d, dict) else {}


def _save(status: str, content: str = "", error: str = ""):
    """落盘简报。**只有给了新内容才覆盖**：生成中 / 失败都保留上一版。

    旧实现 `content or (prev.get("内容") if status == "失败" else "")` 在「生成中」时
    会把内容清空，之后失败再「保留上一版」拿到的已是空串——失败必然丢简报。
    """
    prev = brief()
    state.save(STATE_KEY, {
        "状态": status,
        "模型": MODEL,
        "生成于": time.strftime("%Y-%m-%d %H:%M:%S"),
        "说明": NOTE,
        "大纲字数": len(outline_text()),
        "内容": content or prev.get("内容", ""),
        **({"错误": error} if error else {}),
    })


def _messages(material: str) -> list[dict]:
    """system = 角色铁律 + 《故事大纲》；user = 本局材料（存档 / 首局状态）。"""
    msgs = [{"role": "system", "content": SYSTEM}]
    outline = outline_text()
    if outline:
        msgs.append({"role": "system", "content": OUTLINE_HEADER + outline})
    msgs.append({"role": "user", "content": USER_TMPL.format(text=material)})
    return msgs


def generate(material: str, extra_hint: str = "") -> str | None:
    """调 GLM 生成简报（带 429 退避重试）。失败返回 None。

    `extra_hint` 追加到 user 末尾（用于命中剧透后的「改写」重试）。
    """
    client = _client()
    messages = _messages(material)
    if extra_hint:
        messages[-1] = {
            "role": "user",
            "content": messages[-1]["content"] + "\n\n" + extra_hint,
        }
    for attempt in range(1, RETRIES + 1):
        try:
            r = client.chat.completions.create(
                model=MODEL, messages=messages,
                max_tokens=MAX_TOKENS, temperature=0.7,
            )
            return (r.choices[0].message.content or "").strip() or None
        except Exception as e:
            if attempt == RETRIES:
                raise
            time.sleep(15 * attempt)
    return None


def _work(material: str):
    global _running, _error, _pending
    try:
        _save("生成中")
        txt = generate(material)
        # 代码兼底：命中剧透黑名单 → 先重试一次；仍命中则就地改写（绝不把底牌送进 GM 上下文）
        hits = scan_spoilers(txt or "")
        if hits:
            hint = (
                "⚠️ 上一版泄露了剧透底牌，必须重写：你的输出里出现了禁止出现的词："
                + "、".join(hits)
                + "。把涉及的身份/终局内容改成**当下可见的行为与暗示**，"
                "连「禁止项」也不得点名这些词。其余内容按原要求重新完整输出。"
            )
            retry = generate(material, extra_hint=hint)
            if retry and not scan_spoilers(retry):
                txt = retry
            elif txt:
                txt = sanitize(txt)  # 两次都漏 → 机械消弧
        if txt:
            _save("ok", txt)
            _error = ""
        else:
            _save("失败", error="空输出")
    except Exception as e:
        _error = f"{type(e).__name__}: {e}"
        _save("失败", error=_error[:200])
    finally:
        with _lock:
            nxt, _pending = _pending, None
            _running = bool(nxt)      # 有待跑材料就继续占着，避免中间状态被别的请求抢跑
        if nxt:
            print("[director] 检测到新的开局材料，接着生成")
            _start(nxt)


def is_running() -> bool:
    """当前是否有一次生成在跑（进程内，非按局）。"""
    return _running


def recover_stuck(material: str = "") -> bool:
    """启动 / 续玩时兜底：上次生成被中断（状态=「生成中」但已无活线程）。

    - 内容还在（`_save` 已保留上一版）→ 只把状态收尾为 ok；
    - 内容也丢了 → 用同一材料重新异步生成一次。
    返回是否做了恢复动作。
    """
    if not ENABLED or _running:
        return False
    b = brief()
    if str(b.get("状态", "")) != "生成中":
        return False
    if str(b.get("内容", "")).strip():
        _save("ok")                      # 内容尚在：只补状态
        return True
    print("[director] 检测到上次生成被中断，重新生成简报")
    refresh_async(material)               # 内容已失：重跑
    return True


def _start(material: str) -> None:
    threading.Thread(target=_work, args=(material,), daemon=True, name="director").start()


def refresh_async(material: str):
    """开局异步生成一次（每局一次）。失败保留上一版。

    若已有一次生成在跑（例如开局后马上存档 / 放弃），**不丢弃本次请求**，而是记为最新待跑；
    当前线程结束后立刻用最新材料再生成一次——保证「最后一次请求赢」，不会停在旧局的简报上。
    """
    global _running, _pending
    if not ENABLED:
        return
    # 首局无前情 → 用当前状态兜底（否则导演永远不跑，开场也就永远没有钩子）
    material = (material or "").strip() or _first_material()
    if not material.strip():
        return
    with _lock:
        _pending = material          # 不管在不在跑，先记下“最新要什么”
        if _running:
            return                   # 有人在跑：它结束后会接着跑这份
        _running = True
        _pending = None
    _start(material)
