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

from dotenv import load_dotenv
from openai import OpenAI

from tools.registry import ALL_TOOLS

load_dotenv()

client = OpenAI(
    api_key=os.getenv("LLM_API_KEY"), base_url="https://api.deepseek.com"
)


def send_messages(history, tools=None):
    response = client.chat.completions.create(
        model="deepseek-v4-flash", messages=history, tools=tools or ALL_TOOLS
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
