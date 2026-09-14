# -*- coding: utf-8 -*-
"""
ui_sim.py
=========
小模型 UI 事件管线（背景 `bg` / 音乐 `music`）。

设计（ARCHITECTURE.md 第六、七节）：
    - 大模型只产 `chat` / `narration`；
    - 背景与音乐由**本地小模型**根据「这一幕的叙事 + 当前地点 + 当前背景/音乐」判断；
    - 产出统一 UI 事件（`tools/ui_events.ui_event`），由引擎旁路送到前端。

小模型只做**从固定枚举里选一个**（离散、无幻觉面）：
    场景 ∈ 前端 `assets/背景/` 下的场景目录 + 「无」
    音乐 ∈ `音乐清单.md`（叙事）里的曲目 + 「无」；战斗曲在 `战斗音乐清单.md`，叙事候选**看不到**
「无」= 保持当前不变。

降级：小模型不可用 / 输出非法 → 返回空列表，前端保持原样。
总开关：`TRPG_UI_SIM=0` 关闭。
"""

import os
import re
from pathlib import Path

from tools import small_model
from tools.state_manager import state
from tools.ui_events import bg_event, music_event

_ROOT = Path(__file__).resolve().parent.parent.parent
_SCENE_DIR = _ROOT / "trpg-client" / "src" / "assets" / "背景"
_MUSIC_DIR = _ROOT / "trpg-client" / "src" / "assets" / "音乐"
_MUSIC_MANIFEST = _ROOT / "trpg-world" / "音乐清单.md"
_BATTLE_MANIFEST = _ROOT / "trpg-world" / "战斗音乐清单.md"
_SCENE_MANIFEST = _ROOT / "trpg-world" / "场景清单.md"
_SCENE_MAP_MANIFEST = _ROOT / "trpg-world" / "场景映射.md"

ENABLED = os.environ.get("TRPG_UI_SIM", "1") != "0"

NONE = "无"

#: 没有更贴合曲目时的默认底色曲（需在叙事清单里且 mp3 存在）
DEFAULT_TRACK = "山中好岁月"

# 前端资源目录读不到时的兜底场景
_FALLBACK_SCENES = [
    "城市大街", "街区", "大街", "客栈一楼大厅", "客房", "茶肆", "脚店",
    "荒郊野岭", "山路", "庭院", "卧室", "森林", "江河", "码头",
]

SYSTEM = (
    "你是武侠世界（南宋）的「场景 / 音乐」标注器，只输出 JSON。"
    "读一段叙事，判断**玩家此刻身处的环境**最适合的背景场景与背景音乐。"
    "**以玩家此刻的站位为准**：叙事说「门前 / 街上 / 门外 / 墙外 / 楼下」→ 用**室外**场景；"
    "「推门进了 / 屋里 / 雅间 / 房内 / 楼上」→ 用**室内**场景；分不清就用能涵盖两者的（如 街区 / 城市大街 / 坊）。"
    "音乐要按叙事的**情境 / 情绪**选（用户会给出候选与说明）。"
    "场景与音乐都**只能从给定枚举里选一个**；没有合适的、或与当前一致、或拿不准，就填「无」。"
    "禁止叙述、禁止解释、禁止输出 JSON 以外的任何内容。"
)


def scene_keys() -> list[str]:
    """可选场景：扫前端 `assets/背景/` 的子目录（单一真相源=美术资源）。"""
    if _SCENE_DIR.is_dir():
        names = sorted(d.name for d in _SCENE_DIR.iterdir() if d.is_dir())
        if names:
            return names
    return list(_FALLBACK_SCENES)


def music_tracks() -> list[str]:
    """可选音乐：扫前端 `assets/音乐/` 的 mp3 曲名。"""
    if _MUSIC_DIR.is_dir():
        return sorted(p.stem for p in _MUSIC_DIR.glob("*.mp3"))
    return []


def _parse_manifest(path: Path) -> dict:
    """解析 `- 名称：说明` 形式的清单为 {名称: 说明}。"""
    out = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("-"):
            continue
        body = line.lstrip("-").strip()
        for sep in ("：", ":"):
            if sep in body:
                name, desc = body.split(sep, 1)
                out[name.strip()] = desc.strip()
                break
    return out


def _split_bind(raw: str) -> tuple:
    """把 `曲名｜绑定对象` 拆成 (曲名, 绑定对象)；无绑定则返回 (曲名, "")。"""
    for sep in ("｜", "|"):
        if sep in raw:
            name, bind = raw.split(sep, 1)
            return name.strip(), bind.strip()
    return raw.strip(), ""


def scene_descriptions() -> dict:
    """场景名 → 适用情境说明（读 `trpg-world/场景清单.md`）。"""
    return _parse_manifest(_SCENE_MANIFEST)


def scene_kind_map() -> dict:
    """地点类型 → 允许的场景列表（读 `trpg-world/场景映射.md`）。"""
    out = {}
    try:
        text = _SCENE_MAP_MANIFEST.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("-"):
            continue
        body = line.lstrip("-").strip()
        for sep in ("：", ":"):
            if sep in body:
                kind, rest = body.split(sep, 1)
                scenes = [s.strip() for s in re.split(r"[,，、]", rest) if s.strip()]
                if kind.strip() and scenes:
                    out[kind.strip()] = scenes
                break
    return out


def _kind_of(location: str) -> str:
    """查玩家所在地点的地图类型（`ancient_kind`）；查不到返回 ""。"""
    if not location:
        return ""
    try:
        from tools.map_query import query_place
        rows = (query_place(name=location, limit=1) or {}).get("results") or []
        return (rows[0].get("kind") or "") if rows else ""
    except Exception:
        return ""


def scene_candidates(location: str = None) -> list[str]:
    """本地点允许的背景场景集合；地点类型未映射则返回全部场景。"""
    all_scenes = scene_keys()
    mapped = scene_kind_map().get(_kind_of(location))
    if mapped:
        allowed = [s for s in all_scenes if s in mapped]
        if allowed:
            return allowed
    return all_scenes


def _parse_music(path: Path) -> dict:
    """{曲名: {"desc": 说明, "bind": 绑定对象}}。"""
    out = {}
    for raw, desc in _parse_manifest(path).items():
        name, bind = _split_bind(raw)
        out[name] = {"desc": desc, "bind": bind}
    return out


def music_descriptions(path: Path = None) -> dict:
    """曲名 → 适用情境说明（默认读叙事清单）。"""
    return {n: v["desc"] for n, v in _parse_music(path or _MUSIC_MANIFEST).items()}


def music_bindings(path: Path = None) -> dict:
    """曲名 → 绑定对象（默认读叙事清单）。"""
    return {n: v["bind"] for n, v in _parse_music(path or _MUSIC_MANIFEST).items()}


def _binding_matches(binding: str, location: str, present, kind: str = "") -> bool:
    """绑定对象是否确实在场：**地点名 / 地点类型 / 登场人物**，任一命中即可。

    绑定可写多个（逗号分隔），任一命中即算。
    """
    if not binding:
        return False
    names = [x.strip() for x in re.split(r"[,，、/]", binding) if x.strip()]
    loc = location or ""
    for b in names:
        if b in loc or (kind and (b == kind or b in kind)):
            return True
        for name in present or ():
            if b == name or b in name or name in b:
                return True
    return False


def _listed(path: Path) -> list[str]:
    """清单里、且 mp3 实际存在的曲目（按曲库顺序）。"""
    meta = _parse_music(path)
    existing = set(music_tracks())
    order = {t: i for i, t in enumerate(music_tracks())}
    return sorted([n for n in meta if n in existing], key=lambda t: order.get(t, 0))


def narrative_tracks(location: str = None, present=None) -> list[str]:
    """叙事背景可用曲 = `音乐清单.md` 中、且**绑定命中**的曲目。

    - 无绑定 → 始终可用；
    - 有绑定 → 仅当绑定对象在场（地点名 / 地点类型 / 登场人物）时可用。
    - **战斗曲在另一个文件，天然不在此列。**
    """
    kind = _kind_of(location)
    binds = music_bindings(_MUSIC_MANIFEST)
    out = []
    for name in _listed(_MUSIC_MANIFEST):
        b = binds.get(name, "")
        if not b or _binding_matches(b, location, present, kind):
            out.append(name)
    return out


def battle_tracks() -> list[str]:
    """战斗系统可用曲 = `战斗音乐清单.md` 中、且 mp3 存在的曲目（叙事候选看不到）。

    供战斗系统（第⑨节）选曲：无绑定=通用战斗曲；有绑定（如 `温夫人`）=boss 专属。
    """
    return _listed(_BATTLE_MANIFEST)


def battle_track_for(present=None, location: str = None) -> str:
    """战斗选曲：命中「绑定」（敌人名 / 地点类型）的专属曲优先，否则用通用战斗曲。

    - `present`：敌方登场人物名（用于 boss 专属曲，如「温夫人」）。
    - `location`：地点名（用于地点绑定，如「千灯楼」）。
    无曲库时返回 ""。
    """
    listed = battle_tracks()
    if not listed:
        return ""
    binds = music_bindings(_BATTLE_MANIFEST)
    kind = _kind_of(location) if location else ""
    names = [str(x).strip() for x in (present or []) if str(x).strip()]
    for t in listed:
        b = binds.get(t, "")
        if b and _binding_matches(b, location, names, kind):
            return t
    generic = [t for t in listed if not binds.get(t)]
    return (generic or listed)[0]


def current_shichen() -> str:
    t = (state.load("基本信息", {}) or {}).get("时间", {}) or {}
    return t.get("时辰", "") or ""


def _schema(scenes: list[str], tracks: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "场景": {"type": "string", "enum": scenes + [NONE]},
            "音乐": {"type": "string", "enum": (tracks or []) + [NONE]},
        },
        "required": ["场景", "音乐"],
    }


def generate(narration: str, location: str = None,
             current_scene: str = None, current_music: str = None,
             present=None) -> list[dict]:
    """根据叙事 + 当前状态生成 UI 事件（bg / music）。失败或「无」则不含该项。

    - `location`：玩家当前地点（给背景判断一个权威依据）。
    - `current_scene` / `current_music`：当前正在显示的背景 / 音乐，供其判断是否需变。
    - `present`：本轮**登场人物**（`chat` 说话者），用于专属曲绑定匹配（非仅提及）。
    """
    if not ENABLED or not narration.strip():
        return []
    scenes = scene_candidates(location)
    tracks = narrative_tracks(location, present)
    scene_desc = scene_descriptions()
    music_desc = music_descriptions()
    scene_lines = "\n".join(
        f"- {s}：{scene_desc.get(s, '（无说明）')}" for s in scenes
    ) or "（无）"
    music_lines = "\n".join(
        f"- {t}：{music_desc.get(t, '（无说明）')}" for t in tracks
    ) or "（无）"
    user = (
        f"可选场景（据玩家当前所处环境选）：\n{scene_lines}\n"
        f"可选音乐（据叙事的情境 / 情绪选）：\n{music_lines}\n"
        f"（音乐：选最贴合情境者；**无明显更合适的就默认选「{DEFAULT_TRACK}」**。）\n"
        f"当前地点：{location or '未知'}\n"
        f"当前背景：{current_scene or '无'} ｜ 当前音乐：{current_music or '无'}\n"
        f"当前时辰：{current_shichen() or '未知'}\n"
        f"最近叙事：\n{narration[:800]}"
    )
    r = small_model.ask_json(SYSTEM, user, _schema(scenes, tracks))
    if not isinstance(r, dict):
        return []

    out = []
    pos = r.get("场景")
    if pos in scenes:
        out.append(bg_event(pos, current_shichen()))
    track = r.get("音乐")
    if track not in tracks:
        # 没有更贴合者 → 默认底色曲
        track = DEFAULT_TRACK if DEFAULT_TRACK in tracks else None
    if track:
        out.append(music_event(track))
    return out
