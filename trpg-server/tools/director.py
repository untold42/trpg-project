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
    - 输入：上一局逐字存档（`游戏数据/游戏存档.md`）——**不给现成的「悬着」清单**，让它自己找。
    - 存储：`游戏数据/导演简报.json` ⇒ 自动进入「状态现拼」，每轮注入 DeepSeek。
    - 降级：失败/超时/429 → 保留上一版；从未成功 → 内容为空（不注入噪音）。永不阻塞。
    - 开关：`TRPG_DIRECTOR=0` 关闭。

环境变量：`GLM_API_KEY`（必需）、`GLM_MODEL`（默认 glm-4.5-flash）、`GLM_TIMEOUT`、`GLM_MAX_TOKENS`。
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from dotenv import load_dotenv

from tools.state_manager import state

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

ENABLED = os.environ.get("TRPG_DIRECTOR", "1") != "0"
MODEL = os.environ.get("GLM_MODEL", "glm-4.5-flash")
BASE_URL = os.environ.get("GLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
TIMEOUT = float(os.environ.get("GLM_TIMEOUT", "900"))
MAX_TOKENS = int(os.environ.get("GLM_MAX_TOKENS", "16000"))
RETRIES = int(os.environ.get("GLM_RETRIES", "3"))

STATE_KEY = "导演简报"
NOTE = "幕后简报：仅供把握节奏与取舍，不得复述、不得出现在叙事里"

# ---- 提示词 v4（实测版）：强制取舍 + 防漏自查 + 查主角行动 ----
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
"""

USER_TMPL = """\
请阅读下面的游戏存档，输出《导演简报》，严格按以下七节（**总字数 ≤ 500**）：

## 一、当前局面
（≤3 行：阶段 + 玩家此刻的目标感/心理状态；若这段存档本就是日常戏、没推进任何主线，直接点明）

## 二、主线（只留 1 条）
（一句话；卡在哪；下一拍该发生什么）

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

---
存档如下：

{text}
"""

_lock = threading.Lock()
_running = False
_error = ""


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
    prev = brief()
    state.save(STATE_KEY, {
        "状态": status,
        "模型": MODEL,
        "生成于": time.strftime("%Y-%m-%d %H:%M:%S"),
        "说明": NOTE,
        "内容": content or (prev.get("内容", "") if status == "失败" else ""),
        **({"错误": error} if error else {}),
    })


def generate(material: str) -> str | None:
    """调 GLM 生成简报（带 429 退避重试）。失败返回 None。"""
    client = _client()
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": USER_TMPL.format(text=material)},
    ]
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
    global _running, _error
    try:
        _save("生成中")
        txt = generate(material)
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
            _running = False


def refresh_async(material: str):
    """开局异步生成一次（每局一次）。已在生成中则跳过；失败保留上一版。"""
    global _running
    if not ENABLED:
        return
    material = (material or "").strip()
    if not material:
        return
    with _lock:
        if _running:
            return
        _running = True
    threading.Thread(target=_work, args=(material,), daemon=True, name="director").start()
