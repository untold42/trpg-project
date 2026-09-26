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
    音乐 = **条件判定（代码决定，不问小模型）**：清单 `trpg-world/音乐.json`「叙事」节，
        按地点/时辰/追踪/人物/天气/日期/农历/节日/好感度判定命中，取「条件最多」者；全不中 → 兜底曲。
「无」= 保持当前不变。

降级：小模型不可用 / 输出非法 → 返回空列表，前端保持原样。
总开关：`TRPG_UI_SIM=0` 关闭。
"""

import json
import os
import re
from pathlib import Path

from tools.小模型 import small_model
from tools.核心.state_manager import state
from tools.核心.ui_events import bg_event, music_event

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_SCENE_DIR = _ROOT / "trpg-client" / "src" / "assets" / "背景_重构"
#: 背景三大分类 = 三个文件夹；`室内` 随处可用，`城内/城外` 严格按 `在城内` 互斥
_SCENE_CATS = ("城内", "城外", "室内")
_MUSIC_DIR = _ROOT / "trpg-client" / "src" / "assets" / "音乐"
_MUSIC_NARRATIVE_DIR = _MUSIC_DIR / "叙事探索"   # 叙事 / 探索 BGM
_MUSIC_BATTLE_DIR = _MUSIC_DIR / "战斗"            # 战斗 BGM
_MUSIC_FIXED_DIR = _MUSIC_DIR / "固定"             # 界面专用，不进候选
_MUSIC_MANIFEST = _ROOT / "trpg-world" / "音乐.json"   # 条件表：叙事 + 战斗
_MUSIC_SECTION = "叙事"
_BATTLE_SECTION = "战斗"
_SCENE_TABLE = _ROOT / "trpg-world" / "场景表.json"   # 说明 + 地点候选 + 兜底组 + 场景原型 + 分批

ENABLED = os.environ.get("TRPG_UI_SIM", "1") != "0"

NONE = "无"

#: 没有更贴合曲目时的默认底色曲（需在叙事清单里且 mp3 存在）
DEFAULT_TRACK = "山中好岁月"

SYSTEM = (
    "你是武侠世界（南宋）的「场景标注器」，只输出 JSON。"
    "读**最近几轮叙事**，判断**玩家此刻身处的环境**最适合的场景。"
    "【场景】只能从给定候选集合里选一个——这个集合就是该地点内部可能出现的空间"
    "（例：青楼 → 青楼 / 厅堂 / 闺房 / 阁楼 / 灶房 / 后院 / 屋顶）。"
    "玩家移步、被引路、被送上楼、进房、入席、登高、被带到后院……"
    "只要叙事显示他换到了另一个空间，就选对应的；没换、或拿不准、或与当前一致，就填「无」保持当前。"
    "**读整段语义判断，不要靠某个动词。**"
    "场景只能从给定枚举里选一个；禁止叙述、禁止解释、禁止输出 JSON 以外的任何内容。\n/no_think"
)


def _period_files() -> tuple[str, ...]:
    """一个场景目录里算「有图」的时段文件名。"""
    return tuple(f"{p}.png" for p in ("白天", "黑夜", "黄昏"))


def scene_categories() -> dict[str, str]:
    """场景名 → 分类（城内 / 城外 / 室内）。分类就写在目录结构里：
    `背景_重构/<分类>/<场景>/{白天,黑夜,黄昏}.png`。只收**确实有图**的场景。
    """
    out: dict[str, str] = {}
    for cat in _SCENE_CATS:
        cat_dir = _SCENE_DIR / cat
        if not cat_dir.is_dir():
            continue
        for d in cat_dir.iterdir():
            if d.is_dir() and any((d / f).is_file() for f in _period_files()):
                out.setdefault(d.name, cat)
    return out


def scene_keys() -> list[str]:
    """可选场景 = `背景_重构/<城内|城外|室内>/` 下**确实有图**的目录名。"""
    return sorted(scene_categories())


def _mp3_stems(d: Path) -> list[str]:
    return sorted(p.stem for p in d.glob("*.mp3")) if d.is_dir() else []


def music_tracks() -> list[str]:
    """叙事/探索可选曲 = `assets/音乐/叙事探索/` 下的 mp3（`固定/` 界面专用、`战斗/` 另算）。"""
    return _mp3_stems(_MUSIC_NARRATIVE_DIR)


def _battle_stems() -> list[str]:
    return _mp3_stems(_MUSIC_BATTLE_DIR)


_MUSIC_JSON_CACHE: dict = {}


def _music_json() -> dict:
    """读 `trpg-world/音乐.json`（按 mtime 缓存）。热改免重启。"""
    try:
        m = _MUSIC_MANIFEST.stat().st_mtime
    except OSError:
        return {}
    if _MUSIC_JSON_CACHE.get("m") == m:
        return _MUSIC_JSON_CACHE["v"]
    try:
        v = json.loads(_MUSIC_MANIFEST.read_text(encoding="utf-8"))
        if not isinstance(v, dict):
            v = {}
    except (OSError, json.JSONDecodeError):
        v = {}
    _MUSIC_JSON_CACHE["m"], _MUSIC_JSON_CACHE["v"] = m, v
    return v


def default_track(tracked=None) -> str:
    """没有条件命中时的**兜底曲**。`默认` 可为字符串，或 `{"有": 曲, "无": 曲}`（按追踪任务）。"""
    d = _music_json().get("默认")
    if isinstance(d, dict):
        key = "有" if tracked else "无"
        return str(d.get(key) or d.get("无") or d.get("有") or DEFAULT_TRACK)
    return str(d or DEFAULT_TRACK)


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


def _manifest_section(title: str, path: Path) -> list:
    """取 md 清单里 `## <title>` 到下一个 `## ` 之间的行（目前只有 `音乐表.md` 用）。"""
    try:
        text = path.read_text(encoding="utf-8")
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


def _scene_table() -> dict:
    """读 `trpg-world/场景表.json`（场景说明 / 地点候选 / 兜底组 / 场景原型 / 分批）。"""
    try:
        return json.loads(_SCENE_TABLE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def scene_descriptions() -> dict:
    """场景名 → 适用情境说明（`场景表.json` 的「场景说明」）。"""
    return dict(_scene_table().get("场景说明") or {})


def scene_kind_map() -> dict:
    """地点类型 → 候选场景列表（`场景表.json` 的「地点候选」+「兜底组」室内/室外）。"""
    t = _scene_table()
    out = dict(t.get("地点候选") or {})
    out.update(t.get("兜底组") or {})
    return out


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


def _eligible_scene(scene: str, cats: dict[str, str], inside: bool) -> bool:
    """该场景此刻是否可选。

    - **城内**：所有背景都可用（不设限）；
    - **城外**：允许 `背景_重构/城外/` 的，**也允许「室内」**——
      室内是“人所在的内部”，城内城外都成立（船舱 / 画舫 / 帐篷 / 轿内 / 破庙内…）。
    """
    c = cats.get(scene)
    if c is None:
        return False
    return True if inside else (c in ("城外", "室内"))


def _scenes_for_kind(kind: str, indoor: bool = False, strict: bool = True) -> list[str]:
    """按**已解析的地点类型**给背景候选（纯查表；不查库、不调模型）。

      · **strict=True**（默认，叙事用）：城内→该 kind 候选直接可用；城外→候选 ∩ 「城外集合」。
      · **strict=False**（设施「详细」用）：**不按玩家位置过滤**，直接用该 kind 自己的候选
        （否则「画舫」这种室内类场景，在玩家于城外时会被滤掉、兜底成码头）。
      · 过滤后为空才走兜底组 / 全量兜底。
    """
    cats = scene_categories()
    inside = _player_inside_city() is True
    mapping = scene_kind_map()
    if kind and mapping.get(kind):
        if strict:
            cands = [s for s in mapping[kind] if _eligible_scene(s, cats, inside)]
        else:
            cands = [s for s in mapping[kind] if cats.get(s) is not None]   # 只要图存在
        if cands:
            return cands
    if not inside:
        group = [s for s in (mapping.get("城外") or []) if _eligible_scene(s, cats, inside)]
        return group[:12] or [s for s in scene_keys() if cats.get(s) == "城外"][:12]
    for key in (("室内" if indoor else None), "城内"):
        if not key:
            continue
        allowed = [s for s in (mapping.get(key) or []) if _eligible_scene(s, cats, inside)]
        if allowed:
            return allowed[:8]
    return [s for s in scene_keys() if _eligible_scene(s, cats, inside)][:12]


def _nearby_candidates(indoor: bool = False, radius_km: float = 0.3, limit: int = 8) -> list[str]:
    """**没有地点字段**时：取玩家附近 POI 的 kind 候选并集（按三分类过滤）。"""
    cats = scene_categories()
    inside = _player_inside_city() is True
    mapping = scene_kind_map()
    kinds: list[str] = []
    try:
        from tools.核心.map_query import query_nearby
        pos = (state.load("基本信息", {}) or {}).get("位置", {}) or {}
        lon, lat = pos.get("经度"), pos.get("纬度")
        if isinstance(lon, (int, float)) and isinstance(lat, (int, float)):
            rows = (query_nearby(lon, lat, radius_km=radius_km, limit=12) or {}).get("results") or []
            for x in rows:
                k = (x.get("kind") or "").strip()
                if k and k not in kinds:
                    kinds.append(k)
    except Exception:
        pass
    out: list[str] = []
    for k in kinds:
        for s in mapping.get(k) or []:
            if _eligible_scene(s, cats, inside) and s not in out:
                out.append(s)
    if out:
        return out[:limit]
    return _scenes_for_kind("", indoor)


def scene_candidates(location: str = None, indoor: bool = False) -> list[str]:
    """本地点允许的背景场景**候选集合**。

    - **有地点字段** → 该地点 kind 的候选集合（含内部子场景）；
    - **没有地点字段** → 附近 POI 的 kind 候选并集；
    - 城内安全网：排除城外 / 荒野类场景。
    """
    loc = (location or "").strip()
    if loc:
        return _scenes_for_kind(_kind_of(loc), indoor)
    return _nearby_candidates(indoor)


def scenes_for_kind(kind: str, indoor: bool = False, strict: bool = True) -> list[str]:
    """按地点类型（kind）直接给候选——不查库（调用方已知 kind 时用）。"""
    return _scenes_for_kind((kind or "").strip(), indoor, strict)


def scene_for(kind: str, place: str = "", indoor: bool = False, strict: bool = True) -> str:
    """**确定性**取该 kind 的**主场景**（候选集合第一个 = 设施自己的场景；不调模型）。

    用于探索态「详细」页这类需要稳定结果的场合（此时传 `strict=False`，不受玩家位置影响）；
    叙事态不用它（交小模型在候选里选）。没有可用场景时返回 ""（调用方沿用当前背景）。
    """
    cands = scenes_for_kind(kind, indoor, strict)
    return cands[0] if cands else ""


#: 叙事里表示「在屋内」的词——用于未映射地点类型时的室内/室外兜底组
_INDOOR_RE = re.compile(
    r"屋里|屋内|房内|房中|室内|堂内|殿内|内室|雅间|厢房|楼上|楼内|帐内|"
    r"进了|推门|入内|屋中|铺内|店内|厅内|阁内|舱内|洞里|洞中"
)


def looks_indoor(text: str) -> bool:
    """叙事看起来发生在室内（用于兜底分组）。"""
    return bool(_INDOOR_RE.search(text or ""))


def _cond_to_bind(cond: dict) -> str:
    """把条件里的地点/人物拍平成一个逗号串（兼容旧接口 `music_bindings`）。"""
    toks = []
    for k in ("地点", "人物"):
        for x in (cond.get(k) or []):
            toks.append(str(x))
    return ",".join(toks)


def _parse_music(section: str) -> dict:
    """{曲名: {desc, cond, bind}}（按节读 `音乐.json`）。`bind` 为条件拍平（兼容旧调用）。"""
    sec = _music_json().get(section) or {}
    out = {}
    for name, v in sec.items():
        if not isinstance(v, dict):
            continue
        cond = v.get("条件") if isinstance(v.get("条件"), dict) else {}
        out[name] = {"desc": str(v.get("说明") or ""), "cond": cond, "bind": _cond_to_bind(cond)}
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


def _listed(section: str) -> list[str]:
    """清单里、且 mp3 **实际存在**（在对应目录）的曲目（按曲库顺序）。"""
    meta = _parse_music(section)
    stems = _battle_stems() if section == _BATTLE_SECTION else music_tracks()
    existing = set(stems)
    order = {t: i for i, t in enumerate(stems)}
    return sorted([n for n in meta if n in existing], key=lambda t: order.get(t, 0))


# ------------------------------------------------------------
# 叙事选曲：**条件判定（代码决定，不问小模型）**
# ------------------------------------------------------------
_ORDER = "子丑寅卯辰巳午未申酉戌亥"

#: 条件键的**分值**（默认 1）：小游戏是「一次性特殊场景」，权重压倒常态条件（10）。
_COND_WEIGHT = {"小游戏": 10}


def _shichen_in(value, cur: str) -> bool:
    """时辰是否命中：支持单值「酉」与范围「酉-亥」。"""
    v = str(value).strip()
    if not cur:
        return False
    if "-" in v or "~" in v:
        a, b = re.split(r"[-~]", v, 1)
        a, b = a.strip(), b.strip()
        if a in _ORDER and b in _ORDER and cur in _ORDER:
            i, j, k = _ORDER.index(a), _ORDER.index(b), _ORDER.index(cur)
            return i <= k <= j if i <= j else (k >= i or k <= j)
        return False
    return v == cur


def _affinity_ok(items, ctx) -> bool:
    aff = ctx.get("好感度") or {}
    for it in (items if isinstance(items, list) else [items]):
        if not isinstance(it, dict):
            continue
        who = str(it.get("人物") or "").strip()
        if not who or who not in aff:
            continue
        ok = True
        try:
            if "至少" in it:
                ok = ok and aff[who] >= int(it["至少"])
            if "至多" in it:
                ok = ok and aff[who] <= int(it["至多"])
        except (TypeError, ValueError):
            ok = False
        if ok:
            return True
    return False


def _cond_match(cond: dict, ctx: dict) -> bool:
    """条件是否满足：各键 AND；同一键数组 OR。空条件 → True；**未知键 → False**（防写错就误播）。"""
    if not cond:
        return True
    loc = str(ctx.get("地点") or "")
    kind = str(ctx.get("kind") or "")
    for key, val in cond.items():
        vals = val if isinstance(val, list) else [val]
        if key == "地点":
            # token 命中：`=名` → **精确地点名**；否则 名字含它(宽松) 或 等于/含于地点类型(kind)
            hit = False
            for t in vals:
                ts = str(t).strip()
                if ts.startswith("="):
                    if ts[1:] and loc == ts[1:]:
                        hit = True
                        break
                elif ts and ((ts in loc) or (kind and (ts == kind or ts in kind))):
                    hit = True
                    break
            if not hit:
                return False
        elif key == "时辰":
            if not any(_shichen_in(t, str(ctx.get("时辰") or "")) for t in vals):
                return False
        elif key == "追踪":
            if not any(str(t).strip() == (ctx.get("追踪") or "") for t in vals):
                return False
        elif key == "人物":
            present = ctx.get("人物") or set()
            if not any(str(t) in present for t in vals):
                return False
        elif key == "天气":
            if not any(str(t) in str(ctx.get("天气") or "") for t in vals):
                return False
        elif key == "日期":
            # 公历具体日子 `1220-01-01`；也支持范围 `1220-01-01~1220-01-05`（ISO 串可字典序比较）
            cur = str(ctx.get("日期") or "")
            hit = False
            for t in vals:
                ts = str(t).strip()
                if "~" in ts:
                    a, _, b = ts.partition("~")
                    if cur and a.strip() <= cur <= b.strip():
                        hit = True
                        break
                elif cur and ts == cur:
                    hit = True
                    break
            if not hit:
                return False
        elif key == "农历":
            # 农历日子 `正月初三`；只写 `正月` 也能匹配整月（子串）
            cur = str(ctx.get("农历") or "")
            if not any(cur and (str(t).strip() == cur or str(t).strip() in cur) for t in vals):
                return False
        elif key == "节日":
            fest = ctx.get("节日") or set()
            if not any(str(t) in fest for t in vals):
                return False
        elif key == "小游戏":
            # 当前进行中的小游戏（如 围棋/投壶/斗蟋蟀）；需小游戏系统写入 基本信息.小游戏
            cur = str(ctx.get("小游戏") or "")
            if not any(cur and (str(t).strip() == cur or str(t).strip() in cur) for t in vals):
                return False
        elif key == "好感度":
            if not _affinity_ok(val, ctx):
                return False
        else:
            return False
    return True


def build_context(location=None, present=None, tracked=None) -> dict:
    """现拼条件判定上下文（地点/类型/时辰/追踪/在场/天气/日期/农历/节日/好感度）。"""
    basic = state.load("基本信息", {}) or {}
    t = basic.get("时间") or {}
    w = basic.get("天气") or {}
    aff = {}
    for name in (present or ()):
        try:
            from tools.大模型.character_archive import read_affinity
            v = read_affinity(name)
            if v is not None:
                aff[str(name)] = v
        except Exception:
            pass
    return {
        "地点": location or "",
        "kind": _kind_of(location) if location else "",
        "时辰": str(t.get("时辰") or ""),
        "追踪": "有" if tracked else "无",
        "人物": {str(x) for x in (present or ()) if x},
        "天气": str(w.get("状况") or ""),
        "日期": str(t.get("日期") or ""),          # 公历 1220-01-17
        "农历": str(t.get("农历") or ""),          # 农历（需日历系统写入 基本信息.时间.农历）
        "小游戏": str(basic.get("小游戏") or ""),   # 当前小游戏（需小游戏系统写入 基本信息.小游戏）
        "节日": set(),          # 日历系统接入后填这里
        "好感度": aff,
    }


def select_narrative_track(ctx: dict) -> str:
    """按条件选叙事曲：命中的曲子里取**加权分最高**者（小游戏=10，其余每键=1），

    并列按**清单出现顺序**；全不中（或只有「无条件」曲子）→ **兜底曲**（`音乐.json.默认`）。
    """
    sec = _music_json().get(_MUSIC_SECTION) or {}
    existing = set(music_tracks())
    best, best_score = "", -1
    for name, v in sec.items():
        if name not in existing:
            continue
        cond = (v or {}).get("条件") if isinstance(v, dict) else None
        cond = cond if isinstance(cond, dict) else {}
        if not cond:                       # 无条件的曲子不进「自动选」
            continue
        if not _cond_match(cond, ctx):
            continue
        score = sum(_COND_WEIGHT.get(k, 1) for k in cond)
        if score > best_score:
            best, best_score = name, score
    return best or default_track(ctx.get("追踪") == "有")


def narrative_tracks(location: str = None, present=None, tracked=None) -> list[str]:
    """当前条件下**命中**的叙事曲（确定性，不问小模型）。"""
    ctx = build_context(location, present, tracked)
    meta = _parse_music(_MUSIC_SECTION)
    return [n for n in music_tracks() if n in meta and _cond_match(meta[n].get("cond") or {}, ctx)]


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
    """通用曲：`音乐.json`「叙事」节里**无绑定/无条件**的曲目（不依附任何地点/人物）。

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


def pick_entry_track(location: str = None, present=None, tracked=None) -> str:
    """**进游戏 / 载入时**选背景乐：**条件判定（确定性，不问小模型）**。"""
    return select_narrative_track(build_context(location, present, tracked))


def default_explore_track(current: str = "", tracked=None) -> str:
    """确定性的日常探索曲（**不调小模型**）。当前已在放它 → 返回 ""（无需切换）。"""
    t = default_track(tracked)
    if current and current == t:
        return ""
    return t


def explore_track(current: str = "", tracked=None) -> str:
    """叙事 → 探索时的背景乐：回到**兜底曲**（确定性，不问小模型）。"""
    return default_explore_track(current, tracked)


def battle_tracks() -> list[str]:
    """战斗系统可用曲 = `音乐.json`「战斗」节中、且 mp3 存在于 `assets/音乐/战斗/` 的曲目。

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


def _schema(scenes: list[str], tracks: list[str] | None = None) -> dict:
    props = {"场景": {"type": "string", "enum": scenes + [NONE]}}
    req = ["场景"]
    if tracks:
        props["音乐"] = {"type": "string", "enum": tracks + [NONE]}
        req.append("音乐")
    return {"type": "object", "properties": props, "required": req}


def generate(narration: str, location: str = None,
             current_scene: str = None, current_music: str = None,
             present=None, recent=None, tracked=None) -> list[dict]:
    """根据叙事 + 当前状态生成 UI 事件（bg / music）。

    - 背景 `bg`：**小模型**从本地点候选场景里选（读整轮语义）；
    - 音乐 `music`：**条件判定（确定性，不问小模型）**——见 `select_narrative_track`。
    """
    if not ENABLED or not narration.strip():
        return []
    scenes = scene_candidates(location, indoor=looks_indoor(narration))
    scene_desc = scene_descriptions()
    scene_lines = "\n".join(
        f"- {s}：{scene_desc.get(s, '（无说明）')}" for s in scenes
    ) or "（无）"
    recent_lines = "\n".join(f"- {str(x)[:300]}" for x in (recent or [])[-3:]) or "（无）"
    user = (
        f"可选场景（本地点内可能出现的空间，选一个；没有变化就填「{NONE}」）：\n{scene_lines}\n"
        f"当前地点：{location or '未知'}\n"
        f"当前背景：{current_scene or '无'}\n"
        f"当前时辰：{current_shichen() or '未知'}\n"
        f"最近几轮（由旧到新）：\n{recent_lines}\n"
        f"本轮叙事：\n{narration[:800]}"
    )
    r = small_model.ask_json(SYSTEM, user, _schema(scenes), max_tokens=64)

    out = []
    if isinstance(r, dict):
        pos = r.get("场景")
        if pos in scenes:
            out.append(bg_event(pos, current_shichen()))
    # 音乐：条件判定（确定性；命中更具体的优先，全不中 → 日常曲）
    track = select_narrative_track(build_context(location, present, tracked))
    if track and track != current_music:
        out.append(music_event(track))
    return out
