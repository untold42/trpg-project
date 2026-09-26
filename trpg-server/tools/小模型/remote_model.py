# -*- coding: utf-8 -*-
"""
remote_model.py
===============
**远端 OpenAI 兼容模型**客户端（目前只服务 `quest_sim` 里程碑判定）。

背景：
    本地 Qwen3-4B 做「里程碑是否完成」这种**语义判断**能力不足（只会关键词对齐，
    例：叙事说「追问但对方含糊没说出」，它也判完成）。
    经实测，本机 Codex 网关（`http://127.0.0.1:8317/v1`）的 `gpt-6-luna` 判断正确，
    且支持 strict `response_format` JSON Schema。故把 quest 判定路由过去，
    其余对延迟敏感的本地小模型任务仍走 LM Studio 4B。

配置（热改免重启）：`配置/小模型.json` 的 `quest` 段：
    provider        "remote" 走本模块；"local"/缺失 走 `small_model`(4B)
    base_url/api_key/model/timeout/max_tokens
    "失败回退本地"   远端失败时是否退回 4B（默认 false：失败直接放弃，避免误判）

为什么不用 openai SDK 的严格 schema 直接发：OpenAI strict 模式要求每个 object
    带 `additionalProperties:false` 且所有字段都在 `required`，本模块自动补齐
    （调用方只写普通 JSON Schema）。

调用方：
    from tools.小模型 import remote_model
    if remote_model.enabled("quest"):
        r = remote_model.ask_json("quest", SYSTEM, user, schema)
    else:
        r = small_model.ask_json(SYSTEM, user, schema)   # 4B
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from openai import OpenAI

SERVER_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_FILE = SERVER_DIR / "配置" / "小模型.json"

_DEFAULT_SECTION = {
    "provider": "local",
    "base_url": "http://127.0.0.1:8317/v1",
    "api_key": "",
    "model": "gpt-6-luna",
    "timeout": 60,
    "max_tokens": 400,
    "失败回退本地": False,
    # 可选：关闭模型的「思考模式」。
    #   reasoning_effort: "none" —— OpenAI 风格（LM Studio 对 Qwen3.5 认这个）；
    #   chat_template_kwargs: {"enable_thinking": false} —— Qwen 模板原生开关；
    # 两者都填也无妨，哪个生效用哪个。
    "reasoning_effort": "",
    "chat_template_kwargs": None,
    # JSON 解析失败时重试次数（结构化输出偶发坏格式时有用）
    "重试": 1,
}

_cache: dict = {}
_clients: dict = {}


# ------------------------------------------------------------
# 配置
# ------------------------------------------------------------
def _load_all() -> dict:
    try:
        m = CONFIG_FILE.stat().st_mtime
    except OSError:
        return {}
    if _cache.get("m") == m:
        return _cache["v"]
    raw = {}
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raw = {}
    except (OSError, json.JSONDecodeError):
        raw = {}
    _cache["m"], _cache["v"] = m, raw
    return raw


def config(section: str = "quest") -> dict:
    """取某段的配置（缺省字段用默认补齐）。"""
    cfg = dict(_DEFAULT_SECTION)
    seg = _load_all().get(section)
    if isinstance(seg, dict):
        cfg.update(seg)
    return cfg


def enabled(section: str = "quest") -> bool:
    """是否走远端（provider=="remote" 且配了 model）。"""
    cfg = config(section)
    return cfg.get("provider") == "remote" and bool(cfg.get("model"))


def _client(cfg: dict) -> OpenAI:
    # key 带 timeout：改超时也会重建客户端（否则旧客户端会一直用旧超时）
    key = (cfg.get("base_url"), cfg.get("api_key"), float(cfg.get("timeout") or 60))
    cli = _clients.get(key)
    if cli is None:
        cli = OpenAI(
            api_key=cfg.get("api_key") or "none",
            base_url=cfg.get("base_url"),
            timeout=float(cfg.get("timeout") or 60),
            max_retries=0,
        )
        _clients[key] = cli
    return cli


# ------------------------------------------------------------
# OpenAI strict schema：object 必须 additionalProperties=false 且字段全在 required
# ------------------------------------------------------------
def _strict(node):
    if isinstance(node, dict):
        if node.get("type") == "object" and isinstance(node.get("properties"), dict):
            node.setdefault("additionalProperties", False)
            node["required"] = list(node["properties"].keys())
        for v in node.values():
            _strict(v)
    elif isinstance(node, list):
        for v in node:
            _strict(v)
    return node


def _clean_system(system: str) -> str:
    """远端模型不认 Qwen 的 `/no_think`，去掉以免干扰。"""
    return str(system or "").replace("/no_think", "").strip()


def _parse(content) -> dict | None:
    if not content:
        return None
    txt = str(content).strip()
    if txt.startswith("```"):
        txt = txt.strip("`")
        if "\n" in txt:
            txt = txt.split("\n", 1)[1]
        txt = txt.rsplit("```", 1)[0] if "```" in txt else txt
    try:
        r = json.loads(txt)
    except json.JSONDecodeError:
        return None
    return r if isinstance(r, dict) else None


# ------------------------------------------------------------
# 调用
# ------------------------------------------------------------
def ask_json(section: str, system: str, user: str, schema: dict,
             max_tokens: int | None = None, timeout: float | None = None) -> dict | None:
    """一次结构化调用。成功返回 dict；未启用/失败/非法 JSON 返回 None（调用方降级）。

    `timeout` 仅在显式传入时覆盖 `配置/小模型.json` 的该段值。
    """
    cfg = config(section)
    if not enabled(section):
        return None
    if timeout is not None:
        cfg = {**cfg, "timeout": float(timeout)}
    attempts = 1 + max(0, int(cfg.get("重试") or 0))
    extra: dict = {}
    if cfg.get("reasoning_effort"):
        extra["reasoning_effort"] = cfg["reasoning_effort"]
    if isinstance(cfg.get("chat_template_kwargs"), dict):
        extra["extra_body"] = {"chat_template_kwargs": cfg["chat_template_kwargs"]}
    last_err = ""
    for _ in range(attempts):
        try:
            resp = _client(cfg).chat.completions.create(
                model=cfg["model"],
                messages=[{"role": "system", "content": _clean_system(system)},
                          {"role": "user", "content": user}],
                max_tokens=int(max_tokens or cfg.get("max_tokens") or 400),
                response_format={"type": "json_schema",
                                 "json_schema": {"name": "result",
                                                 "schema": _strict(copy.deepcopy(schema)),
                                                 "strict": True}},
                **extra,
            )
            r = _parse(resp.choices[0].message.content)
            if r is not None:
                return r
            last_err = "JSON 解析失败"
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
    print(f"[remote_model:{section}] 调用失败（{last_err}）")
    return None
