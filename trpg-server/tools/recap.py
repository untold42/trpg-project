# -*- coding: utf-8 -*-
"""
recap.py
========
进入游戏前的「前情回顾」加载。

流程（点击「继续旅途」触发，见 GET /recap）：
    1. 读 `游戏数据/游戏存档.md`（上一轮的前情提要）；为空 → 无回顾，直接进游戏。
    2. 大模型把前情**浓缩成 ≤ MAX_SEGMENTS 段 narration**，最后一段**无缝衔接**当前场景。
    3. 小模型为**最后一幕**选 bg + 音乐（这 10 段共用这份 bg）。
    4. 返回 {has_recap, segments, bg, music}。

音乐策略（用户定）：**回顾期间不换曲**——主菜单主题曲一直放，直到真正进入游戏才切到所选音乐。
因此这里只负责“选出”音乐，何时播放由前端决定。
"""

import json
import re
from pathlib import Path

import llm
from tools import ui_sim
from tools.state_manager import state

_GAME_DATA = Path(__file__).resolve().parent.parent / "游戏数据"
SAVE_TRANSCRIPT = _GAME_DATA / "游戏存档.md"

#: 前情回顾最多几段
MAX_SEGMENTS = 10

_PROMPT = """你是 TRPG 的主持人。玩家即将继续游戏，请把《上一轮存档》浓缩成一段**前情回顾**，
供玩家在进入游戏前快速回顾。要求：

- 输出 **一个 JSON 数组**，每个元素是一段**旁白文本**（字符串），**不超过 10 段**。
- 每段 1–3 句，第二人称「你」称呼主角（梁峰），只叙事、不要 NPC 对话、不要标题、不要编号。
- 按时间顺序浓缩关键人事；**最后一段必须无缝衔接当前场景**——用玩家此刻的所在地/时间收尾，
  让玩家读完就能自然接上下一句行动。
- 只输出 JSON 数组本身，不要任何解释、不要 markdown 代码块。"""


def _current_context() -> str:
    b = state.load("基本信息", {}) or {}
    t = b.get("时间", {}) or {}
    p = b.get("位置", {}) or {}
    return (f"当前游戏时间：{t.get('日期', '')} {t.get('时辰', '')}{('，' + str(t.get('刻')) + '刻') if t.get('刻') else ''}；"
            f"玩家当前所在地：{p.get('地点', '')}。")


def _parse_segments(raw: str) -> list[str]:
    """从模型输出里抠出 JSON 数组；容错 markdown 代码块/多余文字。"""
    if not raw:
        return []
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\[[\s\S]*\]", text)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        s = item if isinstance(item, str) else (item.get("content") if isinstance(item, dict) else "")
        s = str(s or "").strip()
        if s:
            out.append(s)
    return out


def build_recap() -> dict:
    """生成前情回顾。无存档 → {has_recap: False}。"""
    try:
        transcript = SAVE_TRANSCRIPT.read_text(encoding="utf-8").strip()
    except OSError:
        transcript = ""
    if not transcript:
        return {"has_recap": False}

    messages = [
        {"role": "system", "content": _PROMPT},
        {"role": "user", "content": _current_context() + "\n\n《上一轮存档》\n\n" + transcript},
    ]
    try:
        segs = _parse_segments(llm.complete(messages))
    except Exception as e:  # LLM 不可用 → 不阻断进游戏
        return {"has_recap": False, "error": str(e)}
    if not segs:
        return {"has_recap": False}
    segs = segs[:MAX_SEGMENTS]
    segments = [{"type": "narration", "content": s} for s in segs]

    # 小模型：最后一幕的 bg / 音乐（回顾期间不换曲，进游戏时才用音乐）
    bg = None
    music = None
    try:
        loc = (state.load("基本信息", {}) or {}).get("位置", {}).get("地点")
        for ev in ui_sim.generate(segs[-1], location=loc):
            if ev.get("kind") == "bg":
                bg = ev.get("data") or None
            elif ev.get("kind") == "music":
                music = (ev.get("data") or {}).get("track") or None
    except Exception:
        pass

    return {"has_recap": True, "segments": segments, "bg": bg, "music": music}
