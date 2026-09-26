# -*- coding: utf-8 -*-
"""
llm.py
======
大模型客户端（DeepSeek）与消息发送。

工具 schema 的单一真相源在 tools/registry.py：
    ALL_TOOLS —— 本模块 send_messages 使用
    TOOLS_MAP —— engine.TurnRunner 使用
"""

import copy
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from tools.大模型.registry import ALL_TOOLS
from tools.核心 import context_dump

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

# ------------------------------------------------------------
# 大模型客户端配置（热改免重启）：`配置/大模型.json`
#   provider  仅作标记；实际只看 base_url / api_key / model
#   api_key   直接写密钥；或留空用 api_key_env 指定的环境变量（默认 LLM_API_KEY）
#   默认 = DeepSeek（与旧行为一致）；改成一个 OpenAI 兼容端点即可换模型（如 gpt-6-luna）
# ------------------------------------------------------------
SERVER_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SERVER_DIR / "配置" / "大模型.json"

_DEFAULT_CFG = {
    "provider": "deepseek",
    "base_url": "https://api.deepseek.com",
    "api_key": "",
    "api_key_env": "LLM_API_KEY",
    "model": "deepseek-v4-flash",
    "timeout": float(os.environ.get("LLM_TIMEOUT", "180")),
    "max_retries": int(os.environ.get("LLM_MAX_RETRIES", "1")),
    # 可选：关闭模型「思考」（DeepSeek 认 "none" → 不再产 reasoning，GM 回复明显变快）。
    # 留空 = 不传该参数。
    "reasoning_effort": "",
}

_cfg_cache: dict = {}
_clients: dict = {}


def config() -> dict:
    """读 `配置/大模型.json`（按 mtime 缓存；缺失/损坏用默认 DeepSeek）。热改免重启。"""
    try:
        m = CONFIG_FILE.stat().st_mtime
    except OSError:
        return dict(_DEFAULT_CFG)
    if _cfg_cache.get("m") == m:
        return _cfg_cache["v"]
    cfg = dict(_DEFAULT_CFG)
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            cfg.update({k: v for k, v in raw.items() if k in _DEFAULT_CFG})
    except (OSError, json.JSONDecodeError):
        pass
    _cfg_cache["m"], _cfg_cache["v"] = m, cfg
    return cfg


def _api_key(cfg: dict) -> str:
    if cfg.get("api_key"):
        return str(cfg["api_key"])
    return os.getenv(str(cfg.get("api_key_env") or "LLM_API_KEY"), "")


def _client(cfg: dict) -> OpenAI:
    key = (cfg.get("base_url"), _api_key(cfg), float(cfg.get("timeout") or 180),
           int(cfg.get("max_retries") or 0))
    cli = _clients.get(key)
    if cli is None:
        cli = OpenAI(
            api_key=_api_key(cfg) or "none",
            base_url=cfg.get("base_url"),
            timeout=float(cfg.get("timeout") or 180),
            max_retries=int(cfg.get("max_retries") or 0),
        )
        _clients[key] = cli
    return cli


def _extra(cfg: dict) -> dict:
    out = {}
    if cfg.get("reasoning_effort"):
        out["reasoning_effort"] = cfg["reasoning_effort"]
    return out


def send_messages(history, tools=None):
    cfg = config()
    payload_tools = _plain_tools(tools) if tools else _ALL_TOOLS_PLAIN
    # 把**真实发出去**的 messages / tools 原样留一份（TRPG_DUMP_CONTEXT=1 时；见 context_dump.py）
    context_dump.dump(history, payload_tools, str(cfg.get("model") or ""))
    response = _client(cfg).chat.completions.create(
        model=cfg.get("model"),
        messages=history,
        tools=payload_tools,
        **_extra(cfg),
    )
    return response.choices[0].message


def complete(messages, model=None):
    """无工具的纯文本补全（用于前情浓缩 / 任务过期结局等，不涉及 function calling）。"""
    cfg = config()
    response = _client(cfg).chat.completions.create(
        model=model or cfg.get("model"), messages=messages, **_extra(cfg))
    return response.choices[0].message.content or ""


def complete_json(messages, model=None):
    """无工具的 JSON 补全（保证返回合法 JSON 对象）。

    用于战斗里大模型判定「思路」/ 任务里程碑裁定：只要结构化的评价，不要叙事。
    """
    cfg = config()
    response = _client(cfg).chat.completions.create(
        model=model or cfg.get("model"),
        messages=messages,
        response_format={"type": "json_object"},
        **_extra(cfg),
    )
    return response.choices[0].message.content or "{}"
