from flask import Flask, request, jsonify
from flask_cors import CORS
from llm import send_messages

# 需要单独用到的非工具函数
from tools.核心.explore import read_player_position, record_position
from tools.大模型.location import update_location
from tools.大模型 import accident as accident_mod
from tools.核心.state_manager import state
from tools.核心.game_clock import clock
from tools.核心 import time_flow
from tools.服务.factions import list_factions
from tools.服务.recap import build_recap
from tools.服务.place_recall import recall_place
from tools.服务.difficulty_settings import get_settings, set_difficulty
from tools.大模型.facility import facility_detail
from tools.大模型 import facility as facility_mod
from tools.大模型 import time_weather as time_weather_mod
from tools.大模型 import turn_context as turn_context_mod
from tools.核心.map_settings import get_settings as get_map_settings, set_map
from tools.核心 import movement
from tools.核心 import quest
from tools.大模型 import quest_arbiter
from tools.小模型 import quest_sim

# 工具注册表（schema + 实现的单一真相源）
from tools.大模型.registry import TOOLS_MAP
from tools.战斗 import battle_session
from tools.战斗.battle_settings import THOUGHT_MODEL_OPTIONS, get_thought_model, set_thought_model

# 引擎（回合运行 + 会话 + 过程日志）
from engine import GameSession, TurnRunner, continue_cue, observe_cue, OBSERVE_NOTE, OOC_NOTE, is_time_action

# 存档收尾管线
from save_pipeline import run_save

# Flask后端
app = Flask(__name__)
CORS(app)

# ---- 引擎：一局会话 + 回合运行器 ----
# 规则层全量注入（热更新：改 trpg-world/主持人/*.md 即时生效）；状态每次调用现拼
session = GameSession(rules_dir="../trpg-world/主持人")
runner = TurnRunner(session, send_messages, TOOLS_MAP)

# 任务种子：开局并入任务栏（按 id 幂等）
try:
    quest.ensure_seeded()
except Exception as _e:   # 种子失败不影响启动
    print(f"[quest] 种子并入失败：{type(_e).__name__}: {_e}")

# chroma 记忆库由 tools/mem_store.py 懒加载（首次读写记忆时才连）


def _best_effort(*fns):
    """依次执行副作用（落盘 / 联动）；单个失败只记日志，不影响请求返回。

    典型失败：Windows 下文件被外部程序（编辑器 / 杀软 / 另一个实例）占用。
    """
    for fn in fns:
        try:
            fn()
        except Exception as e:   # noqa: BLE001 — 副作用不阻断读取型接口
            print(f"[best-effort] {getattr(fn, '__name__', fn)} 失败：{e}")


# 玩家位置/探索接口见 tools/explore.py（读取 游戏数据/基本信息.json 与 足迹.json）
@app.route("/location", methods=["GET"])
def get_location():
    pos = read_player_position()
    return jsonify(pos)


@app.route("/explored", methods=["GET"])
def get_explored():
    """玩家位置 + 足迹（探索迷雾）。
    每次调用都会把玩家当前位置记入足迹，前端据此只显示去过的区域。
    """
    pos = read_player_position()
    points, radius = record_position(pos.get("lon"), pos.get("lat"), pos.get("地点"))
    return jsonify({
        "lon": pos.get("lon"),
        "lat": pos.get("lat"),
        "地点": pos.get("地点"),
        "区域": pos.get("区域"),
        "footprints": points,
        "radius_km": radius,
    })


@app.route("/state", methods=["GET"])
def get_player_state():
    """玩家真实状态（金钱 / 状态 / 背包 / 属性 / 基本信息）。前端菜单读这个，不再写死。"""
    _best_effort(clock.maybe_persist, time_flow.pump)   # 时间流逝 → 精力 / 跨日联动（失败不 500）
    data = state.snapshot()
    data.pop("任务", None)   # 任务走 GET /quests（玩家投影，不含隐藏字段）
    data["移动"] = movement.config()   # 移动参数（轻功→步速 / 奔跑倍率）——非 游戏数据文件
    return jsonify(data)


@app.route("/run", methods=["POST"])
def settle_run():
    """探索奔跑结算：按「超出步行的距离」扣精力。前端在奔跑累积到一定距离 / 松手时调用。

    入参 `{奔跑米: number}`；返回最新的完整状态（含 移动 参数），前端直接 applyState。
    """
    data = request.json or {}
    try:
        meters = float(data.get("奔跑米", 0) or 0)
    except (TypeError, ValueError):
        meters = 0.0
    _best_effort(lambda: movement.drain_run(meters))
    snapshot = state.snapshot()
    snapshot["移动"] = movement.config()
    return jsonify(snapshot)


@app.route("/clock", methods=["GET"])
def get_clock():
    """连续时钟锚点。前端据此**本地插值**驱动古钟（不必每帧轮询后端）。"""
    _best_effort(clock.maybe_persist, time_flow.pump)   # 前端每 60s 轮询一次，顺便落实跨时辰/跨日
    return jsonify(clock.anchor())


@app.route("/clock/pause", methods=["POST"])
def pause_clock():
    """暂停时钟（菜单 / 历史记录 / 失焦）。"""
    clock.pause("client")
    return jsonify(clock.anchor())


@app.route("/clock/resume", methods=["POST"])
def resume_clock():
    """恢复时钟。"""
    clock.resume("client")
    return jsonify(clock.anchor())


@app.route("/factions", methods=["GET"])
def get_factions():
    """玩家可见的势力条目（画廊用）。数据源：trpg-world/势力介绍.json。"""
    return jsonify(list_factions())


@app.route("/settings", methods=["GET"])
def get_settings_route():
    """游戏设置（目前：难度）。数据源：游戏数据/难度设置.json。"""
    return jsonify(get_settings())


@app.route("/settings", methods=["POST"])
def set_settings_route():
    """修改设置（目前：难度）。请求体 {\"难度\": \"普通\"}。"""
    data = request.json or {}
    return jsonify(set_difficulty(data.get("难度", "")))


# ------------------------------------------------------------
# 地图（多城市）：前端主菜单「环境设定 → 地图」调用
#   切图会换掉整张地图（瓦片/点击层/碰撞层/空间库），前端需同步重载 `?map=<id>`
# ------------------------------------------------------------

@app.route("/maps", methods=["GET"])
def get_maps_route():
    """可用地图 + 当前地图。数据源：trpg-map/城市.py + 游戏数据/地图设置.json。"""
    return jsonify(get_map_settings())


@app.route("/map", methods=["POST"])
def set_map_route():
    """切换地图。请求体 {"地图": "yueyang"}。"""
    data = request.json or {}
    return jsonify(set_map(data.get("地图", "")))


@app.route("/search", methods=["GET"])
def search_route():
    """跳地图用：跨所有地图按名字搜城市/地点。`?q=锦香`"""
    from tools.核心.map_query import search_all_maps
    return jsonify({"results": search_all_maps(request.args.get("q", ""), limit=20)})


@app.route("/scene", methods=["GET"])
def get_scene_route():
    """当前地点建议的背景场景（进游戏时给初值用，不用等第一轮叙事）。

    返回 {地点, 类型, 时辰, 场景, 候选}；场景名与前端 assets/背景_重构/ 目录同名。
    """
    from tools.小模型.ui_sim import _kind_of, scene_candidates

    basic = state.load("基本信息", {}) or {}
    pos = basic.get("位置", {}) or {}
    loc = pos.get("地点") or ""
    shichen = (basic.get("时间", {}) or {}).get("时辰") or ""
    cands = scene_candidates(loc, indoor=False) or scene_candidates(loc, indoor=True) or []
    return jsonify({
        "地点": loc,
        "类型": _kind_of(loc),
        "时辰": shichen,
        "场景": cands[0] if cands else "",
        "候选": cands,
    })


# ------------------------------------------------------------
# 探索 → 叙事：把光标的「从哪到哪」交给主持人
# ------------------------------------------------------------
def _apply_move(coord) -> str:
    """探索模式：前端带上光标坐标 → 更新玩家位置，返回给主持人的【移动】提醒。

    硬事实（从哪到哪 / 距离 / 耗时）由代码给（总纲第 5 条），模型只叙事。
    坐标来自前端光标；「上一个位置」以后端已存的 位置 为准（单一真相源）。
    """
    if not isinstance(coord, dict):
        return ""
    lon, lat = coord.get("lon"), coord.get("lat")
    if not (isinstance(lon, (int, float)) and isinstance(lat, (int, float))):
        return ""
    pos = (state.load("基本信息", {}) or {}).get("位置", {}) or {}
    from_place = pos.get("地点") or ""
    mv = update_location(lon=lon, lat=lat, move_mode="探索")
    if not mv.get("success"):
        return ""
    to_place = (mv.get("位置") or {}).get("地点") or ""
    dist = mv.get("移动距离（米）")
    if from_place and to_place and from_place != to_place:
        msg = f"梁峰自「{from_place}」来到「{to_place}」"
    elif to_place:
        msg = f"梁峰此刻在「{to_place}」"
    else:
        return ""
    if dist:
        msg += f"，相距约 {dist} 米"
    hint = mv.get("耗时提示") or ""
    return "【移动】" + msg + "。" + (f"（{hint}）" if hint else "")


#: 过城门意图词（玩家点「出城/入城」或直接说）
_GATE_WORDS = ("出城", "入城", "进城", "过城门", "出城门")


def _gate_note(raw: str) -> str:
    """玩家要过城门 → 算「城墙另一侧」落脚点，返回给主持人的系统提醒。

    城门是硬事实（由城墙算），但**移动仍由大模型调 `update_location` 落库**（不自动挪）。
    """
    if not any(w in (raw or "") for w in _GATE_WORDS):
        return ""
    pos = (state.load("基本信息", {}) or {}).get("位置", {}) or {}
    try:
        from tools.核心.map_query import gate_crossing
        gc = gate_crossing(pos.get("经度"), pos.get("纬度"))
    except Exception:
        return ""
    if not gc:
        return ""
    lp = gc["落脚点"]
    side = "外" if gc.get("落脚在城内") is False else "内"
    closed = (
        "⚠️ 此刻城门**闭着**——不得放行，只能等开门（先 advance_time）或另想办法。"
        if not gc.get("可通行") else "（此刻门开着）"
    )
    # 起点以状态为准（防止模型凭印象另编一条街/一段路线）
    cur = pos.get("地点") or "（未知）"
    cur_bear = pos.get("城区方位") or ("城内" if pos.get("在城内") else "城外")
    cur_dist = pos.get("距城墙（米）")
    from_desc = f"「{cur}」（{cur_bear}" + (f"，距城墙约 {cur_dist} 米" if cur_dist is not None else "") + "）"
    # 落脚点真实周边（硬事实，供叙事取景）
    nearby = []
    try:
        from tools.核心.map_query import query_nearby
        nb = query_nearby(lp["lon"], lp["lat"], radius_km=0.8, limit=25)
        for x in (nb.get("results") or []):
            nm = x.get("name")
            if not nm:
                continue
            km = x.get("distance_km") or 0
            nearby.append(f"{nm}（{x.get('kind') or '—'}·约{int(round(km * 1000))}米）")
            if len(nearby) >= 8:
                break
    except Exception:
        pass
    nearby_txt = "、".join(nearby) if nearby else "（取不到，改用泛称）"
    return (
        f"【过城门】玩家此刻在{from_desc}，欲{gc['方向']}，最近城门「{gc['城门']}」。{closed}"
        f"落脚点 `lon={lp['lon']}, lat={lp['lat']}`，其附近真实地点：{nearby_txt}。"
        f"请从当前地点按实际方位叙到城门、验籍 / 门军，再调 `update_location(lon={lp['lon']}, lat={lp['lat']})` "
        f"把梁峰移到城墙{side}侧；**沿途与墙外景物一律用上述真实地点，不得另编街名 / 水田 / 土路等**。"
    )


# ------------------------------------------------------------
# 战斗（回合制 n vs n）
# ------------------------------------------------------------
def _battle_note(s: dict) -> str:
    """把战斗结果摘要拼成给主持人的系统提醒。"""
    p = s.get("玩家") or {}
    parts = [f"战斗结束（{s.get('原因') or '—'}）"]
    if s.get("胜方"):
        parts.append(f"胜方：{s['胜方']}")
    if p:
        parts.append(f"梁峰 生命 {p.get('生命')}/{p.get('生命上限')}、内力 {p.get('内力')}/{p.get('内力上限')}")
    if s.get("倒下"):
        parts.append("倒下：" + "、".join(s["倒下"]))
    if s.get("撤离"):
        parts.append("撤离：" + "、".join(s["撤离"]))
    if s.get("约定撤退"):
        parts.append("（事先约定撤退者：" + "、".join(s["约定撤退"]) + "，可叙其是否跟撤）")
    return "、".join(parts) + "。请据此叙事后效（伤势 / 尸体 / 战利品 / 被俘等），不要重述战斗过程。"


@app.route("/battle/state", methods=["GET"])
def battle_state_route():
    """当前战斗状态（无战斗时 {active:false}）。"""
    return jsonify(battle_session.state())


@app.route("/battle/action", methods=["POST"])
def battle_action_route():
    """玩家在战斗界面提交一个动作。

    请求体：{\"动作\", \"目标\", \"移动\", \"招式\", \"目标格\", \"思路\"}。
    返回推进后的完整战斗状态；战斗结束时附 \"结果\" 并把结果注入下一轮 GM 提示。
    """
    data = request.json or {}
    action = {k: data[k] for k in ("动作", "目标", "移动", "招式", "目标格")
              if data.get(k) is not None}
    st = battle_session.submit(action, data.get("思路", ""))
    # 只有**正式**战斗才把结果注入下一轮叙事；模拟战斗不得污染游戏（session 是全局单例）
    if isinstance(st, dict) and st.get("结果") and not st.get("模拟"):
        runner.session.pending_notes.append("【战斗结果】" + _battle_note(st["结果"]))
    return jsonify(st)


@app.route("/battle/settings", methods=["GET"])
def battle_settings_get():
    """战斗设置：思路判定模型（小模型 / 大模型）。"""
    return jsonify({"思路判定模型": get_thought_model(),
                    "可选思路判定模型": list(THOUGHT_MODEL_OPTIONS)})


@app.route("/battle/settings", methods=["POST"])
def battle_settings_post():
    """切换思路判定模型。请求体 {\"思路判定模型\": \"小模型\"|\"大模型\"}。"""
    data = request.json or {}
    return jsonify(set_thought_model(data.get("思路判定模型", "")))


@app.route("/battle/roster", methods=["GET"])
def battle_roster_route():
    """模拟战斗可选名单（来自 武力排名.md）。"""
    return jsonify(battle_session.roster())


@app.route("/battle/sim", methods=["POST"])
def battle_sim_route():
    """环境设定里的「模拟战斗」：直接开局，不走 GM。

    请求体：{\"友方\": [名字...], \"敌人\": [名字...], \"缘由\": \"...\"}。
    玩家（梁峰）固定参战。返回完整战斗状态（前端直接开战斗界面）。
    """
    data = request.json or {}
    return jsonify(battle_session.start(
        data.get("敌人") or [], data.get("友方") or [],
        缘由=data.get("缘由") or "模拟战斗", 模拟=True,
    ))


@app.route("/battle/abort", methods=["POST"])
def battle_abort_route():
    """中止/丢弃当前战斗（不写回状态）。"""
    battle_session.clear()
    return jsonify({"success": True})


@app.route("/music", methods=["GET"])
def get_music_route():
    """进游戏时**重新选一次**背景乐（小模型）。

    前端每次载入游戏都调：不依赖存档 / 前情回顾，保证开局、续玩都有曲子。
    返回 {曲}；失败或挑不出就返回空串，前端保持现状（不报错）。
    """
    from tools.小模型.ui_sim import pick_entry_track

    basic = state.load("基本信息", {}) or {}
    loc = ((basic.get("位置", {}) or {}).get("地点")) or ""
    try:
        return jsonify({"曲": pick_entry_track(loc)})
    except Exception as e:
        return jsonify({"曲": "", "error": str(e)})


@app.route("/recap", methods=["GET"])
def get_recap():
    """前情回顾（进入游戏前的加载）：浓缩上一轮存档为 ≤10 段 narration + 选最后一幕 bg/音乐。"""
    try:
        return jsonify(build_recap())
    except Exception as e:
        return jsonify({"has_recap": False, "error": str(e)})


@app.route("/recall", methods=["GET"])
def recall():
    """地点「回忆」：place_notes（本局见闻）+ gm_memory（客观记忆）Top2。"""
    return jsonify(recall_place(request.args.get("place", ""), n=2))


@app.route("/history", methods=["GET"])
def get_history():
    """当前本局的历史（单一真相源：current.jsonl）。

    前端用途：① 历史面板文本行；② 中途退出后续玩（tail = 最后一轮的指令）。
    """
    return jsonify(session.history_view())


@app.route("/abandon", methods=["POST"])
def abandon():
    """放弃本轮：玩家状态回滚到本局开始，丢弃本局日志（不蒸馏、不归档）。"""
    restored = session.abandon()
    return jsonify({"success": True, "restored": restored})


@app.route("/reject", methods=["POST"])
def reject_turn():
    """驳回上一轮：回滚到本轮开始前（不含本次生成），用同一输入重发一次。

    返回与 `/action` 同形状的事件流，前端用它**替换**上一轮的叙事（不是追加）。
    """
    events = runner.reject()
    return jsonify(events)


@app.route("/save", methods=["POST", "GET"])   # GET 便于在浏览器地址栏直接触发 / 诊断
def save():
    """存档收尾管线（存档 = 结束本局）。

    前端在收到 UI 事件 save_requested（或玩家点「存档」）时调用。
    内部：LLM 蒸馏记忆 → 代码誊写/归档 → 重置会话（玩家状态保留）。
    """
    try:
        result = run_save(session, runner)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    return jsonify(result)


@app.route("/explore", methods=["POST"])
def enter_explore_route():
    """玩家自主从叙事切回探索（**纯前后端逻辑，不经 GM、不调大模型**）。

    何时回大地图是玩家的自由，不需要主持人同意，也不该花一次 LLM 回合。
    返回统一 UI 事件流（mode:explore + 通用 BGM），不写 history / current.jsonl。
    """
    return jsonify(runner.enter_explore())


@app.route("/facility", methods=["GET"])
def get_facility_route():
    """基础设施「详细」界面用：名称 + 选项 + 耗时 + **背景**（映射，不调模型）。

    **秒返回**：选项查 `facilities.json`，背景查 `场景表.md` + 按地名稳定散列。
    参数：`?kind=棋馆&name=棋馆`（kind 优先；设施不在表里也能返回通用选项 + 背景）。
    """
    q = request.args.get("kind") or request.args.get("name") or ""
    nm = request.args.get("name") or q
    return jsonify(facility_detail(q, nm))


@app.route("/skilltree", methods=["GET"])
def get_skilltree_route():
    """技能树全貌 + 玩家状态（技能点 / 每节点 已学·可学·锁定 + 原因）。**不调模型、秒回**。"""
    from tools.核心 import skill_tree
    return jsonify(skill_tree.view())


@app.route("/skilltree/learn", methods=["POST"])
def learn_skill_route():
    """点亮一个技能（花技能点）→ 同步写 `属性.json` + `招式表.json`。body: `{name}`。"""
    from tools.核心 import skill_tree
    data = request.get_json(silent=True) or {}
    name = str(data.get("name") or data.get("技能") or "").strip()
    return jsonify(skill_tree.learn(name))


# ------------------------------------------------------------
# 任务（后端为主）
# ------------------------------------------------------------
@app.route("/quests", methods=["GET"])
def get_quests_route():
    """任务栏：进行中 + 已了结（玩家投影，不含失败后果等隐藏字段）。"""
    return jsonify(quest.player_view())


@app.route("/quest/add", methods=["POST"])
def quest_add_route():
    """玩家点「任务化」：旁路大模型读会话记录 → `add_quest` 建任务。

    请求体可选 `{提示: ""}`。返回新增任务 + 任务栏全貌。
    """
    data = request.json or {}
    hint = str(data.get("提示") or data.get("hint") or "").strip()
    try:
        created = quest_arbiter.arbitrate_add(runner.session.history, hint)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    return jsonify({"success": True, "新增": len(created),
                    "新增任务": [quest.card(t) for t in created],
                    "任务": quest.player_view()})


@app.route("/action", methods=["POST"])
def action():
    data = request.json or {}
    raw = data.get("input", "")
    # mode: action=角色行动｜say=台词｜gm=场外话｜continue=继续｜observe=驻足观察（不切叙事）
    mode = data.get("mode", "action")
    if mode not in ("action", "say", "gm", "continue", "observe"):
        mode = "action"

    # 叙事 → 探索已改走专用入口 `POST /explore`（玩家自主决定，不经 GM）。
    # 以前这里对 `mode=gm` 且输入含「进入探索」做字符串短路，已废弃：
    # 那个匹配不看上下文，玩家在主持人输入框里问一句「怎么进入探索」会被误伤切回地图。

    # 探索模式：前端带上光标坐标 → 更新玩家位置，并把「从哪到哪」作为系统提醒注入本轮
    from_explore = bool(data.get("坐标"))
    note = _apply_move(data.get("坐标"))
    if note:
        runner.session.pending_notes.append(note)

    # 过城门：玩家点「出城/入城」（或直说）→ 注入「墙另一侧落脚点」，由 GM 调 update_location
    if mode == "action":
        gate_note = _gate_note(raw)
        if gate_note:
            runner.session.pending_notes.append(gate_note)

    # 意外机制：只作用于角色行动（每轮都要**重置标志**，避免上轮残留）
    acc = bool(mode == "action" and accident_mod.accident())
    accident_mod.set_turn(acc)
    facility_mod.reset_turn()          # 设施耗时标志：每轮重置
    time_weather_mod.reset_turn()      # 时间工具使用标志：每轮重置
    turn_context_mod.set_turn(raw, mode)   # 本轮玩家动作（供 modify_hunger 等工具判定）
    if acc:
        raw += "(意外：梁峰行动失败)"

    # 时间工具的**硬门禁**：只有玩家本轮在说「花时间的事」（睡觉 / 等待 / 工作 / 修行…）
    # 才把 advance_time / update_time / sleep 下发给大模型；否则模型根本看不到这些工具。
    # 「继续」按钮（ke>0）另算。详见 engine.is_time_action / TIME_ACTION_KEYWORDS。
    if mode == "continue":
        try:
            ke = max(0, int(data.get("ke", 2)))
        except (TypeError, ValueError):
            ke = 2
    else:
        ke = 0
    allow_time = is_time_action(mode, raw, ke)

    # 组装 LLM 看到的文本
    if mode == "continue":
        text = continue_cue(ke)
    elif mode == "say":
        text = "梁峰开口说：「" + raw + "」"
    elif mode == "observe":
        text = observe_cue(raw)
        # 要求走系统提醒（不写进 history / 存档）
        runner.session.pending_notes.append(OBSERVE_NOTE)
    elif mode == "action":
        text = "梁峰：" + raw
    else:
        text = "玩家的对主持人说的话：" + raw
        # 场外话（OOC）：用现代白话直答，不得入戏
        runner.session.pending_notes.append(OOC_NOTE)
    events = runner.run(text, mode, from_explore, allow_time=allow_time)
    # 任务进度（小模型，仅对玩家追踪的任务）→ 追加 UI 事件；
    # 里程碑全部完成的 → 旁路大模型裁定「补新里程碑 / 算真正完成」
    try:
        q_events, q_todo = quest_sim.run(events, data.get("追踪"))
        events = events + q_events
        for t in q_todo:
            quest_arbiter.arbitrate_milestones_async(t)
    except Exception as e:
        print(f"[quest] quest_sim 失败：{type(e).__name__}: {e}")
    time_flow.pump()   # 回合结束后结算时间流逝（精力 / 跨日；含任务 DDL）
    return jsonify(events)


if __name__ == "__main__":
    app.run(port=5000)
