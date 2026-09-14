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
