from flask import Flask, request, jsonify
from flask_cors import CORS
from llm import send_messages

# 需要单独用到的非工具函数
from tools.folder_to_prompt import folder_to_prompt
from tools.explore import read_player_position, record_position
from tools.accident import accident
from tools.state_manager import state

# 工具注册表（schema + 实现的单一真相源）
from tools.registry import TOOLS_MAP

# 引擎（回合运行 + 会话 + 过程日志）
from engine import GameSession, TurnRunner

# 存档收尾管线
from save_pipeline import run_save

# Flask后端
app = Flask(__name__)
CORS(app)

# ---- 引擎：一局会话 + 回合运行器 ----
# 规则层全量注入；状态每次调用现拼（见 engine.snapshot_state），history 只存纯叙事
session = GameSession(rules_prompt=folder_to_prompt("../trpg-world/主持人"))
runner = TurnRunner(session, send_messages, TOOLS_MAP)

# chroma 记忆库由 tools/mem_store.py 懒加载（首次读写记忆时才连）


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
    return jsonify(state.snapshot())


@app.route("/history", methods=["GET"])
def get_history():
    """当前本局的历史（单一真相源：turns.jsonl）。

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
    # mode: "action"=角色行动（IC）｜"gm"=玩家对主持人的场外话（OOC）
    mode = data.get("mode", "action")
    if mode not in ("action", "gm"):
        mode = "action"

    # 意外机制：只作用于角色行动
    if mode == "action" and accident():
        raw += "(意外：梁峰行动失败)"

    # 组装 LLM 看到的文本：带前缀区分 IC / OOC；mode 一并交给引擎存日志
    prefix = "梁峰：" if mode == "action" else "玩家的对主持人说的话："
    events = runner.run(prefix + raw, mode)
    return jsonify(events)


if __name__ == "__main__":
    app.run(port=5000)
