# -*- coding: utf-8 -*-
"""
llm.py
======
大模型客户端（DeepSeek）与消息发送。

工具 schema 的单一真相源在 tools/registry.py：
    ALL_TOOLS —— 本模块 send_messages 使用
    TOOLS_MAP —— engine.TurnRunner 使用
"""

import os
import copy

from dotenv import load_dotenv
from openai import OpenAI

from tools.大模型.registry import ALL_TOOLS
import context_dump

load_dotenv()


# ------------------------------------------------------------
# 工具 schema 描述去 markdown（模型不需要加粗/反引号，纯占 token）
# ------------------------------------------------------------
def _plain(s: str) -> str:
    """去掉纯装饰性的 markdown 字符（**加粗** / `反引号` / *斜体*）。"""
    return s.replace("**", "").replace("*", "").replace("`", "")


def _plain_tools(tools):
    """深拷贝并清洗工具 schema 描述里的 markdown（**不改动 registry 里的源**）。

    只清洗 `description` 字段；属性名 / enum 值不动。
    """
    out = []
    for t in tools or []:
        t = copy.deepcopy(t)
        fn = t.get("function") or {}

        def walk(o):
            if isinstance(o, dict):
                for k, v in list(o.items()):
                    if k == "description" and isinstance(v, str):
                        o[k] = _plain(v)
                    else:
                        walk(v)
            elif isinstance(o, list):
                for x in o:
                    walk(x)

        if isinstance(fn.get("description"), str):
            fn["description"] = _plain(fn["description"])
        walk(fn.get("parameters") or {})
        out.append(t)
    return out


_ALL_TOOLS_PLAIN = _plain_tools(ALL_TOOLS)

# 超时/重试（秒）：不设的话，API 卡住会阻塞很久（默认 600s × 重试）。
# 可用环境变量 LLM_TIMEOUT 调（存档蒸馏大请求可设大些，如 300）。
_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "180"))
_MAX_RETRIES = int(os.environ.get("LLM_MAX_RETRIES", "1"))

client = OpenAI(
    api_key=os.getenv("LLM_API_KEY"),
    base_url="https://api.deepseek.com",
    timeout=_TIMEOUT,
    max_retries=_MAX_RETRIES,
)


def send_messages(history, tools=None):
    payload_tools = _plain_tools(tools) if tools else _ALL_TOOLS_PLAIN
    # 把**真实发出去**的 messages / tools 原样留一份（TRPG_DUMP_CONTEXT=1 时；见 context_dump.py）
    context_dump.dump(history, payload_tools, "deepseek-v4-flash")
    response = client.chat.completions.create(
        model="deepseek-v4-flash",
        messages=history,
        tools=payload_tools,
    )
    return response.choices[0].message


def complete(messages, model="deepseek-v4-flash"):
    """无工具的纯文本补全（用于前情浓缩等，不涉及 function calling）。"""
    response = client.chat.completions.create(model=model, messages=messages)
    return response.choices[0].message.content or ""


def complete_json(messages, model="deepseek-v4-flash"):
    """无工具的 JSON 补全（保证返回合法 JSON 对象）。

    用于战斗里大模型判定「思路」：只要结构化的评价，不要叙事。
    """
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        response_format={"type": "json_object"},
    )
    return response.choices[0].message.content or "{}"
