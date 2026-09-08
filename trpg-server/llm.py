from openai import OpenAI
from dotenv import load_dotenv
import os

money = [
    {
        "type": "function",
        "function": {
            "name": "modify_money",
            "description": "修改玩家的金钱数据，可以增加或减少，单位为文。",
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["增加", "减少"],
                        "description": "增加：给玩家加钱；减少：给玩家扣钱",
                    },
                    "amount": {
                        "type": "integer",
                        "description": "变化量，必须为正整数",
                    },
                },
                "required": ["operation", "amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_money",
            "description": "查看玩家的金钱，单位为文，不需要传入参数。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

bag = [
    {
        "type": "function",
        "function": {
            "name": "modify_item",
            "description": "用于修改背包中已有物品的数量或描述。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "quantity": {
                        "type": "integer",
                        "description": "修改后的物品数量，不填则不修改",
                    },
                    "description": {
                        "type": "string",
                        "description": "修改后的物品描述，不填则不修改",
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_item",
            "description": "用于添加新物品至背包。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "物品名称"},
                    "item_type": {"type": "string", "description": "物品类型，如 武器/食物/药物/材料/书籍"},
                    "quantity": {"type": "integer", "description": "数量"},
                    "description": {"type": "string", "description": "物品描述"},
                },
                "required": ["name", "item_type", "quantity", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_item",
            "description": "用于删除背包中已有的物品。",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_inventory",
            "description": "查看背包已有物品，不需要传参。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

state = [
    {
        "type": "function",
        "function": {
            "name": "modify_hunger",
            "description": "修改玩家的饥饿度。时间流逝或进食后需更新。",
            "parameters": {
                "type": "object",
                "properties": {
                    "hunger": {
                        "type": "string",
                        "enum": ["饱足", "正常", "空腹", "饥饿", "濒饿"],
                    }
                },
                "required": ["hunger"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "modify_injury",
            "description": "用于修改玩家的伤势(无,轻伤,中等伤,重伤,致命伤)",
            "parameters": {
                "type": "object",
                "properties": {
                    "injury": {
                        "type": "string",
                        "enum": ["无", "轻伤", "中等伤", "重伤", "致命伤"],
                    }
                },
                "required": ["injury"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "modify_health",
            "description": "用于修改玩家的健康度(康健,微恙,抱病,沉疴,垂危)",
            "parameters": {
                "type": "object",
                "properties": {
                    "health": {
                        "type": "string",
                        "enum": ["康健", "微恙", "抱病", "沉疴", "垂危"],
                    }
                },
                "required": ["health"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "modify_hp",
            "description": "修改玩家生命值。hp为变化量，正数增加，负数减少。每次睡觉可以增加20。",
            "parameters": {
                "type": "object",
                "properties": {
                    "hp": {
                        "type": "integer",
                    }
                },
                "required": ["hp"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "modify_tp",
            "description": "修改玩家精力值。tp为变化量，正数增加，负数减少。每次睡觉可以增加20。",
            "parameters": {
                "type": "object",
                "properties": {
                    "tp": {
                        "type": "integer",
                    }
                },
                "required": ["tp"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_state",
            "description": "用于获取玩家完整的状态数据，不需要传参",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

ability = [
    {
        "type": "function",
        "function": {
            "name": "get_ability",
            "description": "用于获取玩家的属性能力，不需要传参。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

file_tools = [
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "查看目录中的文件和文件夹。类似 Linux 的 ls 命令。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "目录路径，例如 '.'、'src'、'src/components'",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取一个文本文件的完整内容。类似 Linux 的 cat 命令。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件路径，例如 'app.py' 或 'src/App.tsx'",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "创建文件或完全覆盖已有文件。用于编写代码和文本文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "content": {
                        "type": "string",
                        "description": "要写入文件的完整内容",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "修改已有文件中的一段文本。old_text必须精确匹配文件中的原始文本。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "old_text": {
                        "type": "string",
                        "description": "需要被替换的原始文本",
                    },
                    "new_text": {"type": "string", "description": "替换后的文本"},
                },
                "required": ["path", "old_text", "new_text"],
            },
        },
    },
]

find_specific = [
    {
        "type": "function",
        "function": {
            "name": "check_expression",
            "description": "查看特定人物的表情资源。",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "人物名称"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_specific_character",
            "description": "查看特定人物的人物档案。",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "人物名称"}},
                "required": ["name"],
            },
        },
    },
]

dice = [
    {
        "type": "function",
        "function": {
            "name": "roll_dice",
            "description": "可能性骰：判定玩家主动提出的某个不确定行动的结果（成功/失败/程度）。注意与 daily_event_dice（城市随机事件）、travel_event_dice（旅途随机事件）区分。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    }
]

save = [
    {
        "type": "function",
        "function": {
            "name": "save_game",
            "description": "保存游戏时调用，返回存档流程规则（读取 trpg-world/存档流程.md 的内容）。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    }
]

db = [
    {
        "type": "function",
        "function": {
            "name": "DB_query_tool_in_saving",
            "description": "用于保存游戏时的操作",
            "parameters": {
                "type": "object",
                "properties": {
                    "time": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["time", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "DB_add_and_update_tool",
            "description": "用于添加数据到数据库，或者更新数据库的数据",
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["add", "update"],
                    },
                    "id": {"type": "string"},
                    "time": {"type": "string"},
                    "data_type": {
                        "type": "string",
                        "enum": ["event", "information", "relationship"],
                    },
                    "content": {"type": "string"},
                },
                "required": ["operation", "id", "time", "data_type", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_DB_length",
            "description": "用于获取数据库中最后一条数据的编号，便于添加新的数据",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "DB_query_tool",
            "description": "用于游戏进行过程中，主持人确认历史信息（特别是NPC出场时，或者是玩家提问时）",
            "parameters": {
                "type": "object",
                "properties": {
                    "time": {"type": "string", "description": "可选，用于筛选游戏时间，格式形如1220-01-01"},
                    "data_type": {
                        "type": "string",
                        "enum":["event","relationship","information"],
                        "description": "可选，用于筛选数据类型。event是客观事实，意义是规定这个世界到底发生了什么，用于主持人主持游戏。information是知识情报，意义是确立NPC的信息边界，它的结构主要是“谁得知什么/不知道什么”，“谁认为什么”或者“谁打算什么”等等，它的主语一般为某个人。知识情报一般是主观的，可以是虚假的。relationship是人与人，人与组织或者是组织与组织的关系。",
                    },
                    "n": {"type": "integer", "description": "可选，用于选择返回的信息条数(默认是2)"},
                    "content": {"type": "string", "description": "必选，查询的内容"},
                },
                "required": ["content"],
            },
        },
    },
]

map_query = [
    {
        "type": "function",
        "function": {
            "name": "query_nearby",
            "description": "查询南宋扬州地图上某坐标附近的地点（精确空间查询）。用于回答“这附近有什么”“附近有没有客栈/茶坊/医馆”等地图问题。坐标为 WGS84 经纬度，经度约 118.9~119.96，纬度约 32.17~32.68。",
            "parameters": {
                "type": "object",
                "properties": {
                    "lon": {"type": "number", "description": "经度"},
                    "lat": {"type": "number", "description": "纬度"},
                    "radius_km": {"type": "number", "description": "查询半径（公里），默认1"},
                    "kind": {"type": "string", "description": "南宋类别，如：酒楼/茶坊/客栈/食铺/寺/观/祠/青楼/教坊/画舫/瓦舍/勾栏/坊/桥/渡口/码头/城门/医馆/药铺/市集/书院 等，可选"},
                    "category": {"type": "string", "description": "数据大类：water/waterway/road/building/custom/area/place/tourism/historic 等，可选"},
                    "limit": {"type": "integer", "description": "最多返回条数，默认20"},
                },
                "required": ["lon", "lat"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_place",
            "description": "按名称（模糊）或类别查找南宋扬州地图上的地点，返回其坐标与属性。用于“文昌阁在哪”“有哪些青楼”“太平坊在何处”这类问题。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "地点名称，支持模糊匹配，如“文昌阁”“太平坊”"},
                    "kind": {"type": "string", "description": "南宋类别，可选"},
                    "category": {"type": "string", "description": "数据大类，可选"},
                    "limit": {"type": "integer", "description": "最多返回条数，默认20"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_map_kinds",
            "description": "列出南宋扬州地图上所有地点类别（kind）及数量，用于了解地图上存在哪些类型的场所。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

location = [
    {
        "type": "function",
        "function": {
            "name": "update_location",
            "description": "移动玩家的位置。当玩家说要去某地、前往某处、离开当前地点等移动行为时必须调用本工具，不要用文件工具直接改 基本信息.json 的位置字段。可用地名（如“东关街”“文昌阁”“太平坊”），也可直接给经纬度。移动成功后会自动把该处标记为已探索。",
            "parameters": {
                "type": "object",
                "properties": {
                    "place_name": {"type": "string", "description": "目标地名，支持模糊匹配，如“东关街”“太平坊”“大明寺”"},
                    "lon": {"type": "number", "description": "目标经度（若已知，与 lat 一起直接传）"},
                    "lat": {"type": "number", "description": "目标纬度（若已知，与 lon 一起直接传）"},
                    "move_mode": {"type": "string", "description": "可选，移动方式，如“步行”“骑马”“乘船”“乘轿”，用于叙事"},
                },
                "required": [],
            },
        },
    },
]

time_weather = [
    {
        "type": "function",
        "function": {
            "name": "update_time",
            "description": "修改或推进游戏时间。玩家睡觉、赶路、等待、劳作、活动结束等导致时间流逝时必须调用，不要用文件工具直接改 基本信息.json 的时间字段。日期格式 YYYY-MM-DD，时辰为十二时辰之一：子时、丑时、寅时、卯时、辰时、巳时、午时、未时、申时、酉时、戌时、亥时。两种用法：1) 直接设置 date 和/或 hour；2) 用 advance_hours 推进若干时辰（后端自动算日期与时辰，跨过子时算新一天）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "新日期，格式 YYYY-MM-DD，如 1220-01-16"},
                    "hour": {"type": "string", "description": "新时辰，十二时辰之一，如 辰时、酉时"},
                    "advance_hours": {"type": "integer", "description": "推进的时辰数（正整数），如 6 表示过了 6 个时辰"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_weather",
            "description": "手动覆盖游戏天气（仅特殊剧情需要，如法术改天、极端事件）。常规天气变化请用 get_weather 查表。只传需要修改的字段，不传的保持原样。",
            "parameters": {
                "type": "object",
                "properties": {
                    "condition": {"type": "string", "description": "天气状况，如：晴、多云、阴、小雨、大雨、雪、雾"},
                    "temperature": {"type": "string", "description": "温度体感，如：微凉、温暖、寒冷、炎热"},
                    "wind": {"type": "string", "description": "风力，如：无风、轻风、微风、大风"},
                    "description": {"type": "string", "description": "天气整体描述，如：宜人、闷热、清冷"},
                },
                "required": [],
            },
        },
    },
]

weather = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "查询天气：根据日期与区域查天气数据表，把结果写入基本信息.json的天气字段。时间推进到第二天或未来某一天时必须调用。可传 date/region 查询指定日期或区域的天气。",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "可选，日期 YYYY-MM-DD，默认玩家当前日期"},
                    "region": {"type": "string", "description": "可选，区域名，如 扬州/临安/成都/开封，默认玩家当前区域"},
                },
                "required": [],
            },
        },
    },
]

event_dice = [
    {
        "type": "function",
        "function": {
            "name": "daily_event_dice",
            "description": "日常骰子事件：玩家在城市里主动说「投骰子」时调用。一级骰定事件类型（场景热闹/城市风味/有人搭话/麻烦与危险），二级骰加混乱修正定烈度（偏顺/中性/带刺/危险）。返回后主持人按事件类型与档位叙述。",
            "parameters": {
                "type": "object",
                "properties": {
                    "chaos": {"type": "number", "description": "可选，混乱值 0-100。不传则从 混乱度.json 读取"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "travel_event_dice",
            "description": "旅途骰子事件：玩家在非城市旅途（陆路/水路/海路）中掷。单骰加混乱修正，低顺高不顺，返回事件等级（顺风顺水/偶遇友善/平淡无事/天气变化/小波折/旅途异象/麻烦上门/危险）。返回后主持人按等级叙述，异象/麻烦要从已有钩子推进。",
            "parameters": {
                "type": "object",
                "properties": {
                    "chaos": {"type": "number", "description": "可选，混乱值 0-100。不传则从 混乱度.json 读取"},
                },
                "required": [],
            },
        },
    },
]

all_tools = (
    money + bag + state + ability + file_tools + find_specific + dice + save + db + map_query + location + time_weather + weather + event_dice
)

load_dotenv()

client = OpenAI(
    api_key=os.getenv("LLM_API_KEY"), base_url="https://api.deepseek.com"
)


def send_messages(history):
    response = client.chat.completions.create(
        model="deepseek-v4-flash", messages=history, tools=all_tools
    )

    print()
    print("LLM的完整回复数据")
    print(response)
    print()

    return response.choices[0].message
