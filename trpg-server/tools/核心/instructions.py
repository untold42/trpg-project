# -*- coding: utf-8 -*-
"""
instructions.py
===============
指令数组的**唯一解析入口**。

模型每轮最终要交回一个「指令数组」：

    [{"type": "narration", "content": "…"},
     {"type": "chat", "speaker": "苏惜惜", "content": "…"}]

它经常写不规范。本模块把那些不规范**一次收干净**，产出保证可用的数组：
每条一定有 `type`（chat / narration），chat 一定有 `speaker`，`content` 一定非空。

## 为什么这么写（两条路，不是多级瀑布）

    剥掉围栏后，文本以 `[` 或 `{` 开头  →  按 JSON 解；解不出返回 None（交上层重发修正）
    否则                              →  整段当一条 narration（散文兜底）

两条明确的规则，加上「首尾围栏里包着 JSON」这一种精确形态。仅此而已。

## 踩过的两个坑（别再走回去）

1. **不从散文里抠花括号。**
   模型解释自己格式错误时，会在散文里**引用**一段 JSON 当例子。旧实现「截取最外层
   `{…}`」把那段引用抠出来当指令，于是「它在解释的那个 bug」被重新输出了一遍
   （实测：一段 217 字的道歉，被抠出 47 字，最终输出一条 `苏惜惜：苏惜惜`）。
2. **判「像不像 JSON」只看开头。**
   旧实现用 `'"type"' in 文本`，结果任何**提到** `"type"` 的散文都失去「当旁白兜底」的
   资格——上一条那种道歉正好提到 `"type"`，于是它既不能被当旁白，又只能被抠出那段引用。

## 外部只需要

    parse(raw)        → 永不返回 None；最差是 []，调用方自己决定要不要给占位文案
    try_parse(raw)    → 只走 JSON 路径；解不出返回 None（用于「要不要重发一次」的判断）
    to_text(items)    → 把指令数组写回文本（喂给模型下一轮用）
    items_of(turn)    → 从一回合记录里取指令：优先落盘的 instructions，老存档回落 parse(raw)
"""

from __future__ import annotations

import json
import re

#: 模型写的 `type` 变体（它偶尔自创键名）→ 归一到 chat / narration
_TYPE_ALIASES = {
    "chat": "chat", "dialogue": "chat", "say": "chat", "speech": "chat", "台词": "chat",
    "narration": "narration", "narrate": "narration", "narrative": "narration", "旁白": "narration",
}

#: ```json … ``` 围栏（取第一个围栏块的内容）
_FENCE_RE = re.compile(r"```[a-zA-Z]*[ \t]*\r?\n?(.*?)```", re.S)


def _strip_outer_fence(s: str) -> str:
    """整段被围栏包住时剥掉围栏。"""
    s = (s or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else ""
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    return s.strip()


def _fenced_block(s: str) -> str:
    """取文本里**第一个**围栏块的内容；没有围栏返回 ""。

    只认围栏，不认裸花括号——这是「允许前言 + 代码块」与「不从散文里抠 JSON」的分界。
    """
    m = _FENCE_RE.search(s or "")
    return m.group(1).strip() if m else ""


def _escape_inner_quotes(s: str) -> str:
    """把 JSON 字符串值里**未转义的内层双引号**转义。

    模型写对白时常直接写 `"..."`（英文引号），把 JSON 字符串提前截断。
    规则：字符串里的 `"`，只有当它后面（跳空白）是 `, : } ]` 或行尾时，才算字符串结束；
    否则视为内层引号 → 转义为 `\\"`。已转义的 `\\"` 原样保留。
    """
    out, in_str, i, n = [], False, 0, len(s)
    while i < n:
        ch = s[i]
        if not in_str:
            out.append(ch)
            if ch == '"':
                in_str = True
            i += 1
            continue
        if ch == "\\":                     # 已转义：原样带走
            out.append(ch)
            if i + 1 < n:
                out.append(s[i + 1]); i += 2
            else:
                i += 1
            continue
        if ch == '"':
            j = i + 1
            while j < n and s[j] in " \t\r\n":
                j += 1
            if j >= n or s[j] in ",:}]":   # 后面是分隔符/结尾 → 字符串结束
                out.append(ch); in_str = False
            else:                            # 内层引号 → 转义
                out.append('\\"')
            i += 1
            continue
        out.append(ch); i += 1
    return "".join(out)


def _coerce(data):
    """把解析出的 JSON 变成指令数组：数组原样；单个指令对象包成数组。"""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]          # 单对象（type 合法性交给 normalize 判）
    return None


def _json_items(s: str):
    """`s` 当 JSON 解 → 指令数组；解不出返回 None。转义内层引号后再试一次。"""
    if not s:
        return None
    for cand in (s, _escape_inner_quotes(s)):
        try:
            data = json.loads(cand)
        except (json.JSONDecodeError, TypeError):
            continue
        items = _coerce(data)
        if items is not None:
            return items
    return None


def _starts_like_json(t: str) -> bool:
    """文本是不是**从一开始**就在写 JSON（判「能不能当散文兜底」只看这个）。"""
    return t.startswith("[") or t.startswith("{")


def normalize(items) -> list[dict]:
    """校验并补齐每条指令（返回新列表，不改原对象）。

    - `type`：认得出的变体归一；认不出或缺 → **有 `speaker` 当台词，否则当旁白**
    - `chat` 没有 `speaker` → 降级成旁白（前端只有 chat 才画立绘，空 speaker 会取不到人）
    - `content` 为空 → 丢掉
    - `chat` 的 `content` 恰好等于 `speaker` → 丢掉
      （模型偶发拿台词项当「角色名牌」，连犯过三轮；真正的台词不会只有一个名字）
    """
    out = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        item = dict(item)

        raw_type = str(item.get("type") or "").strip().lower()
        kind = _TYPE_ALIASES.get(raw_type) if raw_type else None
        speaker = str(item.get("speaker") or "").strip()
        if kind is None:
            kind = "chat" if speaker else "narration"
        if kind == "chat" and not speaker:
            kind = "narration"
        item["type"] = kind

        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        if kind == "chat" and content.strip() == speaker:
            continue          # 不打印：历史面板每次重解析全部回合，会刷屏
        out.append(item)
    return out


def try_parse(raw: str):
    """只走 JSON 路径。解不出（或全被判废）返回 None —— 供上层决定「要不要重发一次」。"""
    text = _strip_outer_fence(raw)
    items = None
    if _starts_like_json(text):
        items = _json_items(text)
    if items is None:
        block = _fenced_block(raw or "")
        if block:
            items = _json_items(block)
    if items is None:
        return None
    norm = normalize(items)
    if items and not norm:                 # 解出来了但每条都被判废 → 当失败
        return None
    return norm


def salvage_narration(raw: str) -> list[dict]:
    """散文兜底：整段当一条 `narration`。

    只在文本**不是**从 `[` / `{` 开始（即不像在写 JSON）时用。
    模型在一次工具调用之后偶尔会直接写旁白（实测：`advance_time` 之后）。
    """
    txt = _strip_outer_fence(raw or "").strip()
    if not txt or _starts_like_json(txt):
        return []
    return [{"type": "narration", "content": txt}]


def parse(raw) -> list[dict]:
    """**唯一入口**：永不返回 None。JSON → 散文 → []（调用方自行决定占位文案）。"""
    items = try_parse(raw)
    if items is not None:
        return items
    return salvage_narration(raw)


def to_text(items) -> str:
    """把指令数组写回文本（喂给模型下一轮）。

    `expression` 是后端小模型事后补的（不是模型自己写的），回喂前去掉，
    免得它以为那是自己该输出的字段。列表为空则原样返回（无法序列化时也原样返回）。
    """
    clean = [{k: v for k, v in it.items() if k != "expression"}
             for it in (items or []) if isinstance(it, dict)]
    if not clean:
        return ""
    try:
        return json.dumps(clean, ensure_ascii=False)
    except (TypeError, ValueError):
        return ""


def items_of(turn: dict) -> list[dict]:
    """从一回合记录里取指令：**优先落盘的 `instructions`**，老存档才回落到 `parse(raw)`。

    落盘的 `instructions` 才是「当时真正渲染出去的东西」（已规范化、已过天气机械改写、
    已补表情）。有了它，下游不必各自重解析，解析器改版也不会改旧存档的语义。
    """
    if not isinstance(turn, dict):
        return []
    stored = turn.get("instructions")
    if isinstance(stored, list) and stored:
        return [it for it in stored if isinstance(it, dict)]
    return parse(turn.get("assistant_raw"))
