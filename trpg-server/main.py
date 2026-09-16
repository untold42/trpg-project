from flask import Flask, request, jsonify
from flask_cors import CORS
from llm import send_messages

# 需要单独用到的非工具函数
from tools.explore import read_player_position, record_position
from tools.location import update_location
from tools.accident import accident
from tools.state_manager import state
from tools.game_clock import clock
from tools import time_flow
from tools.factions import list_factions
from tools.recap import build_recap
from tools.difficulty_settings import get_settings, set_difficulty

# 工具注册表（schema + 实现的单一真相源）
from tools.registry import TOOLS_MAP
from tools import battle_session
from tools.battle_settings import THOUGHT_MODEL_OPTIONS, get_thought_model, set_thought_model

# 引擎（回合运行 + 会话 + 过程日志）
from engine import GameSession, TurnRunner, continue_cue

# 存档收尾管线
from save_pipeline import run_save

# Flask后端
app = Flask(__name__)
CORS(app)

# ---- 引擎：一局会话 + 回合运行器 ----
# 规则层全量注入（热更新：改 trpg-world/主持人/*.md 即时生效）；状态每次调用现拼
session = GameSession(rules_dir="../trpg-world/主持人")
runner = TurnRunner(session, send_messages, TOOLS_MAP)

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
    return jsonify(state.snapshot())


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


@app.route("/recap", methods=["GET"])
def get_recap():
    """前情回顾（进入游戏前的加载）：浓缩上一轮存档为 ≤10 段 narration + 选最后一幕 bg/音乐。"""
    try:
        return jsonify(build_recap())
    except Exception as e:
        return jsonify({"has_recap": False, "error": str(e)})


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


@app.route("/save", methods=["POST"])
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


@app.route("/action", methods=["POST"])
def action():
    data = request.json or {}
    raw = data.get("input", "")
    # mode: "action"=角色行动｜"say"=对 NPC 说的话（IC 台词）｜"gm"=对主持人的场外话（OOC）｜"continue"=继续
    mode = data.get("mode", "action")
    if mode not in ("action", "say", "gm", "continue"):
        mode = "action"

    # 探索模式：前端带上光标坐标 → 更新玩家位置，并把「从哪到哪」作为系统提醒注入本轮
    from_explore = bool(data.get("坐标"))
    note = _apply_move(data.get("坐标"))
    if note:
        runner.session.pending_notes.append(note)

    # 意外机制：只作用于角色行动
    if mode == "action" and accident():
        raw += "(意外：梁峰行动失败)"

    # 组装 LLM 看到的文本
    if mode == "continue":
        try:
            ke = max(0, int(data.get("ke", 2)))
        except (TypeError, ValueError):
            ke = 2
        text = continue_cue(ke)
    elif mode == "say":
        text = "梁峰开口说：「" + raw + "」"
    elif mode == "action":
        text = "梁峰：" + raw
    else:
        text = "玩家的对主持人说的话：" + raw
    events = runner.run(text, mode, from_explore)
    time_flow.pump()   # 回合结束后结算时间流逝（精力 / 跨日）
    return jsonify(events)


if __name__ == "__main__":
    app.run(port=5000)
