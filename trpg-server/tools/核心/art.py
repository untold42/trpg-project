# -*- coding: utf-8 -*-
"""
art.py
======
画作子系统（GM 可调用工具 + 异步生成 + 后端主动呈现）。

范式：
    玩家请人作画 → GM 调 `commission_painting`（**立即返回「作画中」**）
      → 后台线程用图像模型生成（~25s）→ 存 `trpg-server/画作/<id>.png`
      → 完成后**后端主动发起一个 GM 回合**（`runner.run_push`）呈现
      → 事件流进 `tools.核心.push` 队列 → 前端轮询 `GET /pending` 取走并展示

设计原则（承接「硬事实由代码裁决」）：
    - 图像模型**不可控**（画出来和描述有出入）→ 所以「这幅画真正想说什么」由
      `寓意` 字段**在代码侧定死**；GM 呈现时只描动作氛围、**不描述画的内容**。
    - `寓意` 仅 GM 与系统可见；玩家视图（`card`）不含，留给玩家自己读、自己问。
    - 作画中清单注入 GM 上下文 → 玩家中途问起，GM 答「还在画」。

配置（热改免重启）：`配置/画作.json`。
"""

from __future__ import annotations

import base64
import functools
import json
import threading
import time
import uuid
from pathlib import Path

from tools.核心.state_manager import state
from tools.核心.ui_events import ui_event, UI_EVENTS_KEY

STATE_KEY = "画作"
SERVER_DIR = Path(__file__).resolve().parent.parent.parent
DIR = SERVER_DIR / "画作"
CONFIG_FILE = SERVER_DIR / "配置" / "画作.json"

STATUS_DOING = "作画中"
STATUS_DONE = "已完成"
STATUS_FAIL = "失败"

_DEFAULT_CFG = {
    "启用": True,
    "base_url": "http://127.0.0.1:8317/v1",
    "api_key": "",
    "model": "gpt-image-2.5",
    "size": "1024x1536",
    "timeout": 300,
    "风格后缀": "中国水墨写意画，宣纸质感，墨色清雅，大片留白，无文字、无印章、无边框。",
    "同时在画上限": 3,
}

_cfg_cache: dict = {}
_lock = threading.RLock()

#: 由 main 注入：runner(text) -> 事件流（TurnRunner.run_push）
_push_runner = None
#: 由 main 注入：sink(events)
_push_sink = None


def _locked(fn):
    @functools.wraps(fn)
    def wrapper(*a, **k):
        with _lock:
            return fn(*a, **k)
    return wrapper


def set_push_runner(fn) -> None:
    global _push_runner
    _push_runner = fn


def set_push_sink(fn) -> None:
    global _push_sink
    _push_sink = fn


# ------------------------------------------------------------
# 配置 / 读写
# ------------------------------------------------------------
def config() -> dict:
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


def _load() -> dict:
    d = state.load(STATE_KEY, None)
    if not isinstance(d, dict) or not isinstance(d.get("画作"), list):
        d = {"画作": []}
    return d


def _all(d: dict | None = None) -> list[dict]:
    return (d or _load()).get("画作") or []


def get(paint_id: str) -> dict | None:
    for r in _all():
        if r.get("id") == paint_id:
            return r
    return None


def _patch(paint_id: str, **fields) -> dict | None:
    with _lock:
        d = _load()
        for r in _all(d):
            if r.get("id") == paint_id:
                r.update(fields)
                state.save(STATE_KEY, d)
                return r
    return None


def _new_id() -> str:
    return "p_" + uuid.uuid4().hex[:8]


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


# ------------------------------------------------------------
# 工具：委托作画（异步）
# ------------------------------------------------------------
@_locked
def commission(作者: str = "", 题: str = "", 画面: str = "",
               寓意: str = "", 风格: str = "") -> dict:
    """GM 工具入口：委托某人作画。**立即返回**（作画中），完成后另行呈现。"""
    cfg = config()
    if not cfg.get("启用"):
        return {"success": False, "error": "画作功能未启用（配置/画作.json 的 启用=false）"}
    作者 = str(作者 or "").strip() or "无名画师"
    题 = str(题 or "").strip()
    画面 = str(画面 or "").strip()
    if not (题 or 画面):
        return {"success": False, "error": "至少给出「题」或「画面」，说明要画什么"}
    cap = int(cfg.get("同时在画上限") or 3)
    doing = [r for r in _all() if r.get("状态") == STATUS_DOING]
    if len(doing) >= cap:
        return {"success": False,
                "error": f"同时最多 {cap} 幅在画，请稍候再委托"}

    rec = {
        "id": _new_id(),
        "作者": 作者,
        "题": 题 or "无题",
        "画面": 画面,
        "寓意": str(寓意 or "").strip(),
        "风格": str(风格 or "").strip(),
        "状态": STATUS_DOING,
        "图片": None,
        "创建于": _now(),
        "完成于": None,
        "错误": None,
    }
    d = _load()
    d["画作"].append(rec)
    state.save(STATE_KEY, d)
    threading.Thread(target=_worker, args=(rec["id"],), daemon=True,
                     name="art-gen").start()
    return {
        "success": True,
        "状态": STATUS_DOING,
        "id": rec["id"],
        "作者": 作者,
        "题": rec["题"],
        "提示": (f"{作者}铺纸研墨，开始专心作画。画需些时候才好——"
                 f"这段时间里，若梁峰问起，就答「她还在专心画」。"),
        UI_EVENTS_KEY: [ui_event("art", 状态=STATUS_DOING, id=rec["id"],
                                 作者=作者, 题=rec["题"])],
    }


# ------------------------------------------------------------
# 后台：生成 + 呈现
# ------------------------------------------------------------
def _prompt_of(rec: dict) -> str:
    cfg = config()
    body = "。".join(x for x in (rec.get("画面") or "", rec.get("题") or "") if x)
    style = rec.get("风格") or ""
    tail = str(cfg.get("风格后缀") or "").strip()
    return "。".join(x for x in (body, style, tail) if x).strip("。") + "。"


def _generate(prompt: str) -> bytes:
    """调用 OpenAI 兼容的图像端点，返回 PNG 字节。"""
    import urllib.request
    cfg = config()
    url = str(cfg.get("base_url") or "").rstrip("/") + "/images/generations"
    body = json.dumps({
        "model": cfg.get("model"),
        "prompt": prompt,
        "size": cfg.get("size") or "1024x1536",
        "n": 1,
    }).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Authorization": "Bearer " + str(cfg.get("api_key") or ""),
                 "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=float(cfg.get("timeout") or 300)) as r:
        d = json.load(r)
    it = (d.get("data") or [{}])[0]
    if it.get("b64_json"):
        return base64.b64decode(it["b64_json"])
    if it.get("url"):                       # 万一返回的是 URL，取回字节
        with urllib.request.urlopen(it["url"], timeout=120) as r2:
            return r2.read()
    raise RuntimeError("图像端点未返回 b64_json/url")


def _worker(paint_id: str) -> None:
    rec = get(paint_id)
    if not rec:
        return
    try:
        raw = _generate(_prompt_of(rec))
        DIR.mkdir(parents=True, exist_ok=True)
        name = f"{paint_id}.png"
        (DIR / name).write_bytes(raw)
        rec = _patch(paint_id, 状态=STATUS_DONE, 图片=name, 完成于=_now()) or rec
        print(f"[art] 画成：{rec.get('作者')}《{rec.get('题')}》→ {name} ({len(raw)}B)")
        _push_turn(rec)
    except Exception as e:
        _patch(paint_id, 状态=STATUS_FAIL, 错误=f"{type(e).__name__}: {e}")
        print(f"[art] 作画失败（{paint_id}）：{type(e).__name__}: {e}")


def _push_text(rec: dict) -> str:
    return (
        f"【后台事件】{rec.get('作者')}把题为《{rec.get('题')}》的画作画成、晾干、题了款，"
        f"双手捧着呈到梁峰面前。请只用两三句描写这一刻：画者的动作、神态、纸墨的气息与周遭气氛。"
        f"画已经呈到梁峰眼前（系统会同时把画展示给他）——**不要替他解读、不要点破言外之意**。"
    )


def _push_turn(rec: dict) -> None:
    """画成 → 后端主动发起一个 GM 回合呈现（server→GM push）。"""
    ev = ui_event("art", 状态=STATUS_DONE, id=rec.get("id"),
                  作者=rec.get("作者"), 题=rec.get("题"),
                  图片=f"/art/{rec.get('id')}.png")
    narrative: list = []
    if _push_runner is not None:
        try:
            narrative = list(_push_runner(_push_text(rec)) or [])
        except Exception as e:
            print(f"[art] 呈现回合失败：{type(e).__name__}: {e}")
    sink = _push_sink
    if sink is not None:
        sink([ev] + narrative)
    else:
        from tools.核心 import push as _push
        _push.push([ev] + narrative)


# ------------------------------------------------------------
# 视图
# ------------------------------------------------------------
def pending_view() -> list[dict]:
    """作画中清单（注入 GM，让它知道有人在画；也给前端显示进度）。"""
    return [{"作者": r.get("作者"), "题": r.get("题"), "开始于": r.get("创建于")}
            for r in _all() if r.get("状态") == STATUS_DOING]


def context_view(limit: int = 30) -> list[dict]:
    """**画作台账（仅 GM 可见，常驻上下文）**：作者/题/画面/寓意/状态/时间。

    - 玩家看不到（玩家视图是 `card`，不含 `画面`/`寓意`）；
    - `寓意` **可空**——画画未必有言外之意，空就不给这个字段，别逼 GM 硬编含义；
    - 含作画中与已完成（让 GM 记得住、前后一致地提）。
    """
    out = []
    for r in _all()[-limit:]:
        if r.get("状态") == STATUS_FAIL:
            continue
        item = {
            "作者": r.get("作者"),
            "题": r.get("题"),
            "画面": r.get("画面"),
            "状态": r.get("状态"),
            "时间": r.get("创建于"),
        }
        if r.get("寓意"):
            item["寓意"] = r["寓意"]
        out.append(item)
    return out


def card(rec: dict) -> dict:
    """玩家投影：不含 `寓意`（留待自己解读）。"""
    return {
        "id": rec.get("id"),
        "作者": rec.get("作者"),
        "题": rec.get("题"),
        "状态": rec.get("状态"),
        "图片": f"/art/{rec.get('id')}.png" if rec.get("图片") else None,
        "创建于": rec.get("创建于"),
        "完成于": rec.get("完成于"),
    }


def all_view() -> list[dict]:
    return [card(r) for r in _all() if r.get("状态") == STATUS_DONE]
