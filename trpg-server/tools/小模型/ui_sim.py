# -*- coding: utf-8 -*-
"""
ui_sim.py
=========
小模型 UI 事件管线（背景 `bg` / 音乐 `music`）。

设计（README.md §5.5 / §5.6）：
    - 大模型只产 `chat` / `narration`；
    - 背景与音乐由**本地小模型**根据「这一幕的叙事 + 当前地点 + 当前背景/音乐」判断；
    - 产出统一 UI 事件（`tools/ui_events.ui_event`），由引擎旁路送到前端。

小模型只做**从固定枚举里选一个**（离散、无幻觉面）：
    场景 ∈ 前端 `assets/背景_重构/` 下**已经有图**的场景目录 + 「无」
    音乐 ∈ `音乐表.md`「叙事」节里的曲目 + 「无」；战斗曲在同文件的「战斗」节，叙事候选看不到
「无」= 保持当前不变。

降级：小模型不可用 / 输出非法 → 返回空列表，前端保持原样。
总开关：`TRPG_UI_SIM=0` 关闭。
"""

import hashlib
import os
import re
from pathlib import Path

from tools.小模型 import small_model
from tools.核心.state_manager import state
from tools.核心.ui_events import bg_event, music_event

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_SCENE_DIR = _ROOT / "trpg-client" / "src" / "assets" / "背景_重构"
_MUSIC_DIR = _ROOT / "trpg-client" / "src" / "assets" / "音乐"
_MUSIC_DYNAMIC_DIR = _MUSIC_DIR / "动态"   # AI 选曲在 动态/；固定/ 是界面专用，不进候选
_MUSIC_MANIFEST = _ROOT / "trpg-world" / "音乐表.md"   # 一份两节：叙事 + 战斗
_MUSIC_SECTION = "叙事"
_BATTLE_SECTION = "战斗"
_SCENE_MANIFEST = _ROOT / "trpg-world" / "场景表.md"   # 一份两节：场景说明 + 地点类型映射

ENABLED = os.environ.get("TRPG_UI_SIM", "1") != "0"

NONE = "无"

#: 没有更贴合曲目时的默认底色曲（需在叙事清单里且 mp3 存在）
DEFAULT_TRACK = "山中好岁月"

SYSTEM = (
    "你是武侠世界（南宋）的「场景 / 音乐」标注器，只输出 JSON。"
    "读一段叙事，判断**玩家此刻身处的环境**最适合的背景场景与背景音乐。"
    "**以玩家此刻的站位为准**：叙事说「门前 / 街上 / 门外 / 墙外 / 楼下」→ 用**室外**场景；"
    "「推门进了 / 屋里 / 雅间 / 房内 / 楼上」→ 用**室内**场景；分不清就用能涵盖两者的（如 街区 / 城市大街 / 坊）。"
    "音乐要按叙事的**情境 / 情绪**选（用户会给出候选与说明）。"
    "场景与音乐都**只能从给定枚举里选一个**；没有合适的、或与当前一致、或拿不准，就填「无」。"
    "禁止叙述、禁止解释、禁止输出 JSON 以外的任何内容。\n/no_think"
)


def _period_files() -> tuple[str, ...]:
    """一个场景目录里算「有图」的时段文件名。"""
    return tuple(f"{p}.png" for p in ("白天", "黑夜", "黄昏"))


def scene_keys() -> list[str]:
    """可选场景：扫 `assets/背景_重构/` 的子目录（单一真相源=美术资源）。

    只收**确实有图**的目录：还没出图的 kind 不进候选，
    否则小模型会选到一个前端拿不到图的场景（只能退回主页面）。
    一张图都没有时返回 []——不发 bg 事件，前端保持主页面。
    """
    if not _SCENE_DIR.is_dir():
        return []
    return sorted(
        d.name for d in _SCENE_DIR.iterdir()
        if d.is_dir() and any((d / f).is_file() for f in _period_files())
    )


def music_tracks() -> list[str]:
    """可选音乐：扫前端 `assets/音乐/动态/` 的 mp3 曲名（`固定/` 是界面专用，不走 AI）。"""
    if _MUSIC_DYNAMIC_DIR.is_dir():
        return sorted(p.stem for p in _MUSIC_DYNAMIC_DIR.glob("*.mp3"))
    return []


def _parse_lines(lines) -> dict:
    """解析 `- 名称：说明` 形式的行 → {名称: 说明}。"""
    out = {}
    for line in lines:
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


def _parse_manifest(path: Path) -> dict:
    """解析 `- 名称：说明` 形式的清单为 {名称: 说明}。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    return _parse_lines(text.splitlines())


def _manifest_section(title: str, path: Path = None) -> list:
    """取清单文件里 `## <title>` 到下一个 `## ` 之间的行（默认 `场景表.md`）。"""
    try:
        text = (path or _SCENE_MANIFEST).read_text(encoding="utf-8")
    except OSError:
        return []
    out, on = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            on = line[3:].strip() == title
            continue
        if on:
            out.append(line)
    return out


def _split_bind(raw: str) -> tuple:
    """把 `曲名｜绑定对象` 拆成 (曲名, 绑定对象)；无绑定则返回 (曲名, "")。"""
    for sep in ("｜", "|"):
        if sep in raw:
            name, bind = raw.split(sep, 1)
            return name.strip(), bind.strip()
    return raw.strip(), ""


def scene_descriptions() -> dict:
    """场景名 → 适用情境说明（`trpg-world/场景表.md` 的「场景说明」节）。"""
    return _parse_lines(_manifest_section("场景说明"))


def scene_kind_map() -> dict:
    """地点类型 → 允许的场景列表（`trpg-world/场景表.md` 的「地点类型映射」节）。"""
    out = {}
    for line in _manifest_section("地点类型映射"):
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


#: 明显的「城外 / 荒野」场景（按 kind 命名）——玩家在城内时一律排除
#: 防「人在城里被切到山里」（新素材一 kind 一图，这里只列非城市场所）
_WILD_SCENES = {
    "山", "林", "湖", "水域", "洲", "义冢", "坟地",
    "盐场", "矿冶", "窑场", "造船场", "榷场",
}


def _player_inside_city():
    """玩家是否在城内（读 基本信息.位置.在城内）；未知返回 None。"""
    try:
        from tools.核心.state_manager import state
        v = ((state.load("基本信息", {}) or {}).get("位置", {}) or {}).get("在城内")
        return v if isinstance(v, bool) else None
    except Exception:
        return None


def _kind_of(location: str) -> str:
    """玩家所在地点的地图类型（`ancient_kind`）。

    **路网要素（坊巷 / 大街 / 官道）没有名字**，按名查不到 → 退回「玩家坐标附近的
    最近有类型要素」。都不行返回 ""（此时不做场景限制，但有城内的安全网）。
    """
    # ① 按地名查（如「怀茂青楼」→ 青楼）。
    #    优先**完全同名**：query_place 是 LIKE 模糊匹配，
    #    「岳阳楼」会先撞上「岳阳楼街道」(kind=村)，得跳过。
    if location:
        try:
            from tools.核心.map_query import query_place
            rows = (query_place(name=location, limit=8) or {}).get("results") or []
            for r in rows:
                if (r.get("name") or "") == location:
                    k = (r.get("kind") or "").strip()
                    if k:
                        return k
            for r in rows:
                k = (r.get("kind") or "").strip()
                if k:
                    return k
        except Exception:
            pass
    # ② 退回玩家坐标附近（路网地名查不到时的主路径）
    try:
        from tools.核心.map_query import query_nearby
        from tools.核心.state_manager import state
        pos = (state.load("基本信息", {}) or {}).get("位置", {}) or {}
        lon, lat = pos.get("经度"), pos.get("纬度")
        if isinstance(lon, (int, float)) and isinstance(lat, (int, float)):
            rows = (query_nearby(lon, lat, radius_km=0.1, limit=4) or {}).get("results") or []
            for x in rows:
                k = (x.get("kind") or "").strip()
                if k:
                    return k
    except Exception:
        pass
    return ""


def _scenes_for_kind(kind: str, indoor: bool = False) -> list[str]:
    """按**已解析的地点类型**给背景候选（纯查表 + 城内安全网；不查库、不调模型）。

    每个 kind 在 `场景表.md` 里有一条**优先级链**（自己的同名场景排第一，后面是同类的兜底），
    这里取链里第一个**已经有图**的，作为唯一候选；
    该类一张图都没有、或地点类型查不到时，才退回 `室内` / `室外` 兜底组
    （那一组是并列候选，由叙事判断屋里/屋外来选）。
    """
    all_scenes = set(scene_keys())
    mapping = scene_kind_map()
    if kind and mapping.get(kind):
        # 链是**优先级顺序**，只取第一个有图的；
        # 不能把整条链当并列候选，否则人在青楼可能被切成画舫。
        for s in mapping[kind]:
            if s in all_scenes and not (_player_inside_city() is True and s in _WILD_SCENES):
                return [s]
    group = mapping.get("室内" if indoor else "室外")
    if group:
        allowed = [s for s in group if s in all_scenes]
        if allowed:
            return allowed[:6]
    if _player_inside_city() is True:
        urban = [s for s in scene_keys() if s not in _WILD_SCENES]
        if urban:
            return urban
    return scene_keys()


def scene_candidates(location: str = None, indoor: bool = False) -> list[str]:
    """本地点允许的背景场景集合。

    - 地点类型能查到、且该类链上有图 → **只有一个候选**（链里第一个有图的）；
    - 否则用 `室内` / `室外` 兜底组（并列候选，按叙事判断屋里/屋外选）；
    - 城内安全网：排除城外 / 荒野类场景。
    """
    return _scenes_for_kind(_kind_of(location), indoor)


def scenes_for_kind(kind: str, indoor: bool = False) -> list[str]:
    """按地点类型（kind）直接给候选——不查库（调用方已知 kind 时用）。"""
    return _scenes_for_kind((kind or "").strip(), indoor)


def scene_for(kind: str, place: str = "", indoor: bool = False) -> str:
    """**确定性**选一个背景场景（不调模型）。

    在候选里按 `place`（地点名）做**稳定散列**取一个——同一地点每次相同，
    不同地点可能不同；没有可用场景时返回 ""（调用方沿用当前背景）。
    """
    cands = scenes_for_kind(kind, indoor)
    if not cands:
        return ""
    seed = (place or kind or "").encode("utf-8")
    idx = int(hashlib.md5(seed).hexdigest(), 16) % len(cands)
    return cands[idx]


#: 叙事里表示「进/出/移动」的词——只有出现这些才允许换背景（场景状态机，见 engine）
_SCENE_SWITCH_RE = re.compile(
    r"推门|进门|进了|走入|走进|踏入|步入|迈入|跨进|入内|进屋|上楼|登上|拾级|进入|"
    r"来到|走到|行至|前往|抵达|回到|返回|赶到|出了|出门|走出|离开|下楼|退出|"
    r"跨出|迈出|转过|拐进|拐过|穿过|穿出|上到|下到|出了门|走出去|走进来|退到|移步"
)

#: 叙事里表示「在屋内」的词——用于未映射地点类型时的室内/室外兜底组
_INDOOR_RE = re.compile(
    r"屋里|屋内|房内|房中|室内|堂内|殿内|内室|雅间|厢房|楼上|楼内|帐内|"
    r"进了|推门|入内|屋中|铺内|店内|厅内|阁内|舱内|洞里|洞中"
)


def looks_indoor(text: str) -> bool:
    """叙事看起来发生在室内（用于兜底分组）。"""
    return bool(_INDOOR_RE.search(text or ""))


def scene_switch_signal(text: str) -> bool:
    """叙事里有没有「进/出/移动」的动作——没有就不该换背景（防抖）。"""
    return bool(_SCENE_SWITCH_RE.search(text or ""))


def _parse_music(section: str) -> dict:
    """{曲名: {"desc": 说明, "bind": 绑定对象}}（按节读 `音乐表.md`）。"""
    out = {}
    for raw, desc in _parse_lines(_manifest_section(section, _MUSIC_MANIFEST)).items():
        name, bind = _split_bind(raw)
        out[name] = {"desc": desc, "bind": bind}
    return out


def music_descriptions(section: str = None) -> dict:
    """曲名 → 适用情境说明（默认读「叙事」节）。"""
    return {n: v["desc"] for n, v in _parse_music(section or _MUSIC_SECTION).items()}


def music_bindings(section: str = None) -> dict:
    """曲名 → 绑定对象（默认读「叙事」节）。"""
    return {n: v["bind"] for n, v in _parse_music(section or _MUSIC_SECTION).items()}


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
    """叙事背景可用曲 = `音乐表.md`「叙事」节中、且绑定命中的曲目。

    - 无绑定 → 始终可用；
    - 有绑定 → 仅当绑定对象在场（地点名 / 地点类型 / 登场人物）时可用。
    - 战斗曲在「战斗」节，天然不在此列。
    """
    kind = _kind_of(location)
    binds = music_bindings()
    out = []
    for name in _listed(_MUSIC_SECTION):
        b = binds.get(name, "")
        if not b or _binding_matches(b, location, present, kind):
            out.append(name)
    return out


def location_bound_tracks(location: str, kind: str = None) -> list[str]:
    """当前地点 / 地点类型**专属绑定**的叙事曲（不计人物绑定）。

    仅当一曲的绑定命中当前地点名 / 地点类型时算数；用于「进入某地就放它的主题曲」。
    例：锦香宫 → 锦绣织岁，玄烛照心；青城 → 雨后松林香。
    """
    if not location:
        return []
    kind = kind if kind is not None else _kind_of(location)
    binds = music_bindings()
    out = []
    for name in _listed(_MUSIC_SECTION):
        b = binds.get(name, "")
        if b and _binding_matches(b, location, (), kind):
            out.append(name)
    return out


def general_tracks() -> list[str]:
    """通用曲：`音乐表.md`「叙事」节里无绑定的曲目（不依附任何地点/人物）。

    探索大地图用它们，避免从青楼/酒楼等地出来还搂着场所专属曲。
    """
    binds = music_bindings()
    return [t for t in _listed(_MUSIC_SECTION) if not binds.get(t)]


_EXPLORE_SYSTEM = (
    "你是武侠游戏「探索大地图」的配乐师。玩家正从室内 / 剧情走回大地图自由走动。"
    "从给定通用曲里挑**一首**适合赶路 / 逛街 / 探索的（偏中性、清闲、行进感），只输出 JSON。"
    "只能选给定清单里的一首；拿不准就选「" + DEFAULT_TRACK + "」。禁止思考、禁止解释。\n/no_think"
)


_ENTRY_SYSTEM = (
    "你是武侠游戏（南宋）的配乐师。玩家刚进游戏（开局 / 续玩），你按**他此刻所在的地点**"
    "挑一首背景乐：偏中性、有空间感，能长期循环不吵。只输出 JSON。"
    "若清单里某首标了【本地点专属】，优先选它。只能选给定清单里的一首；拿不准就选「"
    + DEFAULT_TRACK + "」。禁止思考、禁止解释。\n/no_think"
)


def pick_entry_track(location: str = None, present=None) -> str:
    """**进游戏 / 载入时**重新选一次背景乐（小模型）。

    与 `explore_track` 的区别：那个只从「通用曲」里挑（走回大地图用），
    这个连「本地点专属曲」一起给候选，用于每次载入游戏都要有曲子的场景。
    地点恰好只绑一首 → 硬选它，不劳模型。失败退回确定性兜底。
    """
    bound = location_bound_tracks(location) if location else []
    if len(bound) == 1:
        return bound[0]
    tracks = narrative_tracks(location, present) or general_tracks()
    if not tracks:
        return ""
    if len(tracks) == 1:
        return tracks[0]
    desc = music_descriptions()
    lines = "\n".join(
        f"- {t}：{desc.get(t, '')}" + ("【本地点专属】" if t in bound else "")
        for t in tracks
    )
    user = (
        f"可选音乐：\n{lines}\n"
        f"当前地点：{location or '未知'}\n"
        f"（带【本地点专属】的是当前地点的主题曲，有的话优先选它。）"
    )
    schema = {
        "type": "object",
        "properties": {"音乐": {"type": "string", "enum": tracks}},
        "required": ["音乐"],
    }
    r = small_model.ask_json(_ENTRY_SYSTEM, user, schema)
    track = r.get("音乐") if isinstance(r, dict) else None
    if track not in tracks:
        track = DEFAULT_TRACK if DEFAULT_TRACK in tracks else tracks[0]
    return track


def default_explore_track(current: str = "") -> str:
    """确定性的通用探索曲（**不调小模型**，瞬时返回）。

    优先 `DEFAULT_TRACK`，否则取通用曲第一首；当前已在放通用曲则返回 ""（无需切换）。
    供 `engine.enter_explore()`（玩家自主切探索）使用。
    """
    tracks = general_tracks()
    if not tracks:
        return ""
    if current and current in tracks:
        return ""
    return DEFAULT_TRACK if DEFAULT_TRACK in tracks else tracks[0]


def explore_track(current: str = "") -> str:
    """叙事 → 探索时用的**通用背景乐**。叫小模型从通用曲里挑；失败/无候选返回 ""。

    （调用方：`engine.TurnRunner` 检测到 `resume_exploration` 时。）
    """
    tracks = general_tracks()
    if not tracks:
        return ""
    if len(tracks) == 1:
        return tracks[0]
    desc = music_descriptions()
    lines = "\n".join(f"- {t}：{desc.get(t, '')}" for t in tracks)
    user = (
        f"可选通用曲：\n{lines}\n"
        f"当前曲目：{current or '无'}（它是场所/剧情专属，在探索地图上继续放不合适）"
    )
    schema = {
        "type": "object",
        "properties": {"音乐": {"type": "string", "enum": tracks}},
        "required": ["音乐"],
    }
    r = small_model.ask_json(_EXPLORE_SYSTEM, user, schema)
    t = r.get("音乐") if isinstance(r, dict) else None
    if t not in tracks:
        t = DEFAULT_TRACK if DEFAULT_TRACK in tracks else tracks[0]
    return t


def battle_tracks() -> list[str]:
    """战斗系统可用曲 = `音乐表.md`「战斗」节中、且 mp3 存在的曲目（叙事候选看不到）。

    供战斗系统（第⑨节）选曲：无绑定=通用战斗曲；有绑定（如 `温夫人`）=boss 专属。
    """
    return _listed(_BATTLE_SECTION)


_BATTLE_BGM_SYSTEM = (
    "你是武侠战斗的「配乐师」。读战局情境，从给定战斗曲里挑**一首**最贴合的，只输出 JSON。\n"
    "判断顺序：先看敌我强弱（压制 / 势均力敌 / 劣势 / 绝境），"
    "再看性质（对决 / 追杀 / 军阵 / 决战 / 苦战 / 牺牲）。\n"
    "只能选给定清单里的一首；拿不准就选「侠心凛然」。禁止思考、禁止解释。\n/no_think"
)


def battle_track_model(context: str, present=None, location: str = None,
                       avoid: str = None) -> str:
    """小模型据战局情境选战斗曲。返回曲名；失败/超时返回 ""（调用方代码兜底）。

    - 只把**适用**曲目给它：通用曲 + 绑定命中（boss 在场）的专属曲。
    - boss 专属只能命中一首时直接用它，不劳模型。
    - `avoid`：上一首（在提示里请模型避免）。
    """
    listed = battle_tracks()
    if not listed:
        return ""
    binds = music_bindings(_BATTLE_SECTION)
    kind = _kind_of(location) if location else ""
    names = [str(x).strip() for x in (present or []) if str(x).strip()]
    适用 = [t for t in listed
            if not binds.get(t) or _binding_matches(binds.get(t, ""), location, names, kind)]
    if not 适用:
        return ""
    if len(适用) == 1:
        return 适用[0]
    # boss 在场（绑定命中）→ 直接给专属曲，不劳模型
    bound = [t for t in 适用 if binds.get(t)]
    if bound:
        return bound[0]

    desc = music_descriptions(_BATTLE_SECTION)
    lines = "\n".join(f"- {t}：{desc.get(t, '')}" for t in 适用)
    user = (
        f"战局情境：\n{context}\n\n"
        f"可选战斗曲（只能选一首）：\n{lines}\n"
        + (f"（避免重复上一首「{avoid}」）\n" if avoid and avoid in 适用 else "")
        + "请选一首最贴合的。"
    )
    schema = {"type": "object",
              "properties": {"音乐": {"type": "string", "enum": 适用}},
              "required": ["音乐"]}
    r = small_model.ask_json(_BATTLE_BGM_SYSTEM, user, schema, max_tokens=40, timeout=6)
    t = str((r or {}).get("音乐", "")).strip()
    return t if t in 适用 else ""


def battle_track_for(present=None, location: str = None, avoid: str = None) -> str:
    """战斗选曲：命中「绑定」（敌人名 / 地点类型）的专属曲优先，否则从**通用战斗曲里随机**。

    - `present`：敌方登场人物名（用于 boss 专属曲，如「温夫人」）。
    - `location`：地点名（用于地点绑定，如「千灯楼」）。
    - `avoid`：上一首，尽量不重复。
    无曲库时返回 ""。
    """
    import random as _random
    listed = battle_tracks()
    if not listed:
        return ""
    binds = music_bindings(_BATTLE_SECTION)
    kind = _kind_of(location) if location else ""
    names = [str(x).strip() for x in (present or []) if str(x).strip()]
    for t in listed:
        b = binds.get(t, "")
        if b and _binding_matches(b, location, names, kind):
            return t
    pool = [t for t in listed if not binds.get(t)] or listed
    if avoid and len(pool) > 1:
        pool = [t for t in pool if t != avoid] or pool
    return _random.choice(pool)


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
    scenes = scene_candidates(location, indoor=looks_indoor(narration))
    tracks = narrative_tracks(location, present)
    loc_bound = location_bound_tracks(location)
    scene_desc = scene_descriptions()
    music_desc = music_descriptions()
    scene_lines = "\n".join(
        f"- {s}：{scene_desc.get(s, '（无说明）')}" for s in scenes
    ) or "（无）"
    music_lines = "\n".join(
        f"- {t}：{music_desc.get(t, '（无说明）')}" + ("【本地点专属】" if t in loc_bound else "")
        for t in tracks
    ) or "（无）"
    user = (
        f"可选场景（据玩家当前所处环境选）：\n{scene_lines}\n"
        f"可选音乐（据叙事的情境 / 情绪选）：\n{music_lines}\n"
        f"（音乐：带【本地点专属】的是**当前地点的主题曲**，进入该地点应优先选它；"
        f"没有更贴合的就填「{NONE}」＝保持当前曲。）\n"
        f"当前地点：{location or '未知'}\n"
        f"当前背景：{current_scene or '无'} ｜ 当前音乐：{current_music or '无'}\n"
        f"当前时辰：{current_shichen() or '未知'}\n"
        f"最近叙事：\n{narration[:800]}"
    )
    r = small_model.ask_json(SYSTEM, user, _schema(scenes, tracks), max_tokens=128)
    if not isinstance(r, dict):
        return []

    out = []
    pos = r.get("场景")
    if pos in scenes:
        out.append(bg_event(pos, current_shichen()))
    # 地点主题曲：当前地点 / 类型恰好只绑一首 → 硬选它（不劳模型）；
    # 多首（如书坊的两首）才交模型按情境挑。
    if len(loc_bound) == 1:
        track = loc_bound[0]
    else:
        track = r.get("音乐")
        if track == NONE or track not in tracks:
            track = None          # 「无」= 保持当前曲，不再兵底到默认曲
    if track:
        out.append(music_event(track))
    return out
