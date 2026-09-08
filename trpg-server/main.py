from flask import Flask, request, jsonify
from flask_cors import CORS
from llm import send_messages
import json

# 引入工具
from tools.money import get_money, modify_money
from tools.bag import modify_item, get_inventory, add_item, remove_item
from tools.state import modify_hunger,modify_health,modify_injury,modify_tp,modify_hp,get_state
from tools.ability import get_ability
from tools.dice import roll_dice
from tools.file_tools import list_directory, read_file, write_file, edit_file
from tools.find_specific_expression import check_expression
from tools.folder_to_prompt import folder_to_prompt
from tools.find_specific_character import find_specific_character
from tools.DB import DB_query_tool_in_saving, DB_add_and_update_tool, check_DB_length, DB_query_tool
from tools.map_query import query_nearby, query_place, list_map_kinds
from tools.explore import read_player_position, record_position
from tools.location import update_location
from tools.time_weather import update_time, update_weather
from tools.weather_system import get_weather
from tools.event_dice import daily_event_dice, travel_event_dice

# 引入机制
from tools.accident import accident
from tools.save_game import save_game

# 引入RAG数据库
import chromadb
from sentence_transformers import SentenceTransformer

# Flask后端
app = Flask(__name__)
CORS(app)

history = [
    {"role": "system", "content": folder_to_prompt("../trpg-world/主持人")},
    {"role": "system", "content": folder_to_prompt("./tools/游戏数据")},
]


def collapse_tool_messages(history):
    """塌缩工具中间消息。
    每轮工具循环结束后调用：删掉所有 tool 结果，以及只有 tool_calls 没有正文的
    assistant 消息。历史里只保留 system / user / assistant 正文，避免工具中间
    过程永久累积撑大上下文。
    """
    cleaned = []
    for m in history:
        if m.get("role") == "tool":
            continue
        if m.get("role") == "assistant" and m.get("tool_calls"):
            if not m.get("content"):
                continue
            # 少数模型会“正文 + tool_calls”一起出：去掉 tool_calls 保留正文
            m = {k: v for k, v in m.items() if k != "tool_calls"}
        cleaned.append(m)
    history[:] = cleaned

tools_map = {
    # 金钱
    "modify_money": modify_money,
    "get_money": get_money,
    # 背包
    "modify_item": modify_item,
    "add_item": add_item,
    "remove_item": remove_item,
    "get_inventory": get_inventory,
    # 状态
    "modify_hunger": modify_hunger,
    "modify_health": modify_health,
    "modify_injury": modify_injury,
    "modify_hp": modify_hp,
    "modify_tp": modify_tp,
    "get_state": get_state,
    # 属性能力
    "get_ability": get_ability,
    # 文件系统
    "list_directory": list_directory,
    "read_file": read_file,
    "write_file": write_file,
    "edit_file": edit_file,
    # 查找特定
    "check_expression": check_expression,
    "find_specific_character": find_specific_character,
    # 骰子
    "roll_dice": roll_dice,
    # 机制
    "save_game": save_game,
    # 数据库
    "DB_query_tool_in_saving": DB_query_tool_in_saving,
    "DB_add_and_update_tool": DB_add_and_update_tool,
    "DB_query_tool": DB_query_tool,
    "check_DB_length": check_DB_length,
    # 地图空间查询
    "query_nearby": query_nearby,
    "query_place": query_place,
    "list_map_kinds": list_map_kinds,
    # 玩家位置移动
    "update_location": update_location,
    # 时间与天气
    "update_time": update_time,
    "update_weather": update_weather,
    "get_weather": get_weather,
    # 骰子事件
    "daily_event_dice": daily_event_dice,
    "travel_event_dice": travel_event_dice,
}
    

 # 数据库

client = chromadb.PersistentClient(
    path="C:/Users/20866/Desktop/trpg-project/trpg-db/chroma_db"
)
memory = client.get_collection(name="memory")
model = SentenceTransformer("Qwen/Qwen3-Embedding-0.6B")
print("数据库加载成功")


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


@app.route("/action", methods=["POST"])
def action():
    data = request.json
    player_input = data["input"]
    if accident() and player_input[0] == "梁":
        history.append(
            {"role": "user", "content": player_input + "(意外：梁峰行动失败)"}
        )
    else:
        history.append({"role": "user", "content": player_input})

    result = send_messages(history)
    while result.tool_calls:

        # 1. 保存 LLM 的 tool_calls 消息
        history.append(
            {
                "role": "assistant",
                "content": result.content,
                "tool_calls": [
                    tool_call.model_dump() for tool_call in result.tool_calls
                ],
            }
        )

        # 2. 执行工具
        for tool_call in result.tool_calls:
            tool_name = tool_call.function.name
            arguments = json.loads(tool_call.function.arguments)
            tool = tools_map.get(tool_name)
            if tool is None:
                tool_result = {"success": False, "error": f"未知工具: {tool_name}"}
            else:
                try:
                    tool_result = tool(**arguments)
                except Exception as e:
                    tool_result = {"success": False, "error": str(e)}

            # 3. 保存工具结果
            history.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(tool_result, ensure_ascii=False),
                }
            )

        # 4. 工具执行完，再次请求 LLM
        result = send_messages(history)

    # 5. 只有不需要工具了，才处理最终 JSON
    history.append({"role": "assistant", "content": result.content})
    print("最终 result.content:")
    print(repr(result.content))
    
    try:
        response = json.loads(result.content)
    except json.JSONDecodeError:
        history.append({
        "role": "user",
        "content": "后端发现你的最终回复格式有误，请严格按照系统规定输出合法JSON数组，不要输出任何额外内容。"
    })
        result = send_messages(history)
        print("修正后的 result.content:")
        print(repr(result.content))
        response = json.loads(result.content)

    # 塌缩工具中间消息：本轮工具循环已结束，tool 结果与 tool_calls 不再需要留在上下文
    collapse_tool_messages(history)

    return jsonify(response)

if __name__ == "__main__":
    app.run(port=5000)