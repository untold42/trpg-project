# -*- coding: utf-8 -*-
"""
registry.py
===========
单一工具注册表：每个工具在此「一处定义」schema + 实现函数。

    TOOLS     : {name: (schema, fn)}   单一真相源
    ALL_TOOLS : [schema, ...]          供 llm.send_messages 用
    TOOLS_MAP : {name: fn}             供 engine.TurnRunner 用

新增工具只需在 _ENTRIES 里加一行，不必再同时改 llm.py 与 main.py。
（本文件由 _gen_registry.py 从旧 llm.py / main.py 生成，之后请手工维护。）
"""

from tools.money import modify_money, get_money
from tools.bag import modify_item, add_item, remove_item, get_inventory
from tools.state import (
    modify_hunger,
    modify_injury,
    modify_health,
    modify_hp,
    modify_tp,
    get_state,
)
from tools.ability import get_ability
from tools.file_tools import list_directory, read_file, write_file, edit_file
from tools.find_specific_expression import check_expression
from tools.get_character import get_character
from tools.character_archive import update_character_archive
from tools.dice import roll_dice
from tools.DB import (
    DB_query_tool_in_saving,
    DB_add_and_update_tool,
    DB_query_tool,
)
from tools.map_query import query_nearby, query_place, list_map_kinds, update_place_note
from tools.location import update_location
from tools.time_weather import update_time, update_weather
from tools.weather_system import get_weather
from tools.event_dice import daily_event_dice, travel_event_dice

_ENTRIES = [
    (
        "modify_money",
        {
            "type": "function",
            "function": {
                "name": "modify_money",
                "description": "增减玩家的钱（**直接落账**）：增加=收入，减少=支出。"
                "支出 / 收入都要调它，并在**同一轮叙述里说明金额与事由**；余额不足会整笔拒绝。"
                "**禁止按时间流逝 / 在场 / \"该记账了\"自动扣费。**",
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
                        "reason": {
                            "type": "string",
                            "description": "这笔钱的事由，如「一壶酒」「卖马所得」，供玩家查账",
                        },
                    },
                    "required": ["operation", "amount"],
                },
            },
        },
        modify_money,
    ),
    (
        "get_money",
        {
            "type": "function",
            "function": {
                "name": "get_money",
                "description": "查看玩家的金钱，单位为文，不需要传入参数。",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        get_money,
    ),
    (
        "modify_item",
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
        modify_item,
    ),
    (
        "add_item",
        {
            "type": "function",
            "function": {
                "name": "add_item",
                "description": "用于添加新物品至背包。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "物品名称"},
                        "item_type": {
                            "type": "string",
                            "description": "物品类型，如 " "武器/食物/药物/材料/书籍",
                        },
                        "quantity": {"type": "integer", "description": "数量"},
                        "description": {"type": "string", "description": "物品描述"},
                    },
                    "required": ["name", "item_type", "quantity", "description"],
                },
            },
        },
        add_item,
    ),
    (
        "remove_item",
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
        remove_item,
    ),
    (
        "get_inventory",
        {
            "type": "function",
            "function": {
                "name": "get_inventory",
                "description": "查看背包已有物品，不需要传参。",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        get_inventory,
    ),
    (
        "modify_hunger",
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
        modify_hunger,
    ),
    (
        "modify_injury",
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
        modify_injury,
    ),
    (
        "modify_health",
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
        modify_health,
    ),
    (
        "modify_hp",
        {
            "type": "function",
            "function": {
                "name": "modify_hp",
                "description": "修改玩家生命值。hp为变化量，正数增加，负数减少。每次睡觉可以增加20。",
                "parameters": {
                    "type": "object",
                    "properties": {"hp": {"type": "integer"}},
                    "required": ["hp"],
                },
            },
        },
        modify_hp,
    ),
    (
        "modify_tp",
        {
            "type": "function",
            "function": {
                "name": "modify_tp",
                "description": "修改玩家精力值。tp为变化量，正数增加，负数减少。每次睡觉可以增加20。",
                "parameters": {
                    "type": "object",
                    "properties": {"tp": {"type": "integer"}},
                    "required": ["tp"],
                },
            },
        },
        modify_tp,
    ),
    (
        "get_state",
        {
            "type": "function",
            "function": {
                "name": "get_state",
                "description": "用于获取玩家完整的状态数据，不需要传参",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        get_state,
    ),
    (
        "get_ability",
        {
            "type": "function",
            "function": {
                "name": "get_ability",
                "description": "用于获取玩家的属性能力，不需要传参。",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        get_ability,
    ),
    (
        "list_directory",
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
                            "description": "目录路径，例如 "
                            "'.'、'src'、'src/components'",
                        }
                    },
                    "required": [],
                },
            },
        },
        list_directory,
    ),
    (
        "read_file",
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
                            "description": "文件路径，例如 "
                            "'app.py' "
                            "或 "
                            "'src/App.tsx'",
                        }
                    },
                    "required": ["path"],
                },
            },
        },
        read_file,
    ),
    (
        "write_file",
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
        write_file,
    ),
    (
        "edit_file",
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
        edit_file,
    ),
    (
        "check_expression",
        {
            "type": "function",
            "function": {
                "name": "check_expression",
                "description": "查看特定人物的表情资源。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "人物名称"}
                    },
                    "required": ["name"],
                },
            },
        },
        check_expression,
    ),
    (
        "get_character",
        {
            "type": "function",
            "function": {
                "name": "get_character",
                "description": (
                    "特定人物登场时先调用：一次读全该人物的档案——"
                    "静态正典（外貌/身份/性格/身世等）+ 动态近记忆（与梁峰的关系/当前情绪/信息边界）。"
                    "不含长期深层记忆；若需更早的记忆，再自行调用 DB_query_tool"
                    "（collection=char_memory, owner=人物名）。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "人物名称（可用全名或绰号）"}
                    },
                    "required": ["name"],
                },
            },
        },
        get_character,
    ),
    (
        "update_character_archive",
        {
            "type": "function",
            "function": {
                "name": "update_character_archive",
                "description": (
                    "【仅存档蒸馏时使用】更新某 NPC 的**动态档案**（近记忆·热）：追加里程碑 / 情感记忆，"
                    "覆写当前情绪状态与信息边界。**先查静态档案**：已有→只更新动态（静态不覆盖）；"
                    "没有→用 `static` 字段建静态并建动态。本局有实质互动的 NPC 都要为其调用一次。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "人物规范名（与 char_memory.owner 一致）"},
                        "static": {
                            "type": "object",
                            "description": "首次登场的静态字段（可选）：全名/年纪/籍贯/外貌/身份/说话方式/性格/技能/身世/关系网",
                        },
                        "milestone": {
                            "type": "object",
                            "properties": {"time": {"type": "string"}, "event": {"type": "string"}},
                            "description": "§9 里程碑追加一行",
                        },
                        "feeling": {
                            "type": "object",
                            "properties": {"time": {"type": "string"}, "event": {"type": "string"}, "feeling": {"type": "string"}},
                            "description": "§10 情感记忆追加一行（从她的视角·具体·身体化）",
                        },
                        "recent": {"type": "string", "description": "§9 最近互动（追加一段）"},
                        "attitude": {"type": "string", "description": "§9 态度（一句话：她把梁峰当成什么）"},
                        "emotion": {
                            "type": "object",
                            "properties": {
                                "主要情绪": {"type": "string"},
                                "强度": {"type": "integer"},
                                "触发源": {"type": "string"},
                                "距今": {"type": "string"},
                            },
                            "description": "§11 当前情绪状态（覆写）",
                        },
                        "behaviors": {"type": "array", "items": {"type": "string"}, "description": "§11 行为表现（覆写，3-5 条）"},
                        "want": {"type": "string", "description": "§11 想要什么（此时此刻·一句话）"},
                        "volatility": {"type": "string", "description": "§11 挥发性（高/中/低）"},
                        "known": {"type": "array", "items": {"type": "string"}, "description": "§12 已知"},
                        "unknown": {"type": "array", "items": {"type": "string"}, "description": "§12 不知"},
                        "info_attitude": {"type": "string", "description": "§12 对未知部分的态度"},
                    },
                    "required": ["name"],
                },
            },
        },
        update_character_archive,
    ),
    (
        "roll_dice",
        {
            "type": "function",
            "function": {
                "name": "roll_dice",
                "description": "可能性骰：判定玩家主动提出的某个不确定行动的结果（成功/失败/程度）。注意与 "
                "daily_event_dice（城市随机事件）、travel_event_dice（旅途随机事件）区分。",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        roll_dice,
    ),
    (
        "DB_query_tool_in_saving",
        {
            "type": "function",
            "function": {
                "name": "DB_query_tool_in_saving",
                "description": "存档蒸馏用：对一条待写入的信息，找出最相似的前4条旧记忆，用于判断该add还是update。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "collection": {
                            "type": "string",
                            "enum": ["gm_memory", "char_memory"],
                            "description": "gm_memory=主持人客观事实；char_memory=角色主观记忆（须给owner）",
                        },
                        "owner": {
                            "type": "string",
                            "description": "char_memory必填：这是谁的记忆",
                        },
                        "time": {"type": "string"},
                    },
                    "required": ["content", "collection"],
                },
            },
        },
        DB_query_tool_in_saving,
    ),
    (
        "DB_add_and_update_tool",
        {
            "type": "function",
            "function": {
                "name": "DB_add_and_update_tool",
                "description": "向长期记忆新增或更新一条。add：不用给id，系统自动编号；update：必须给id（旧记忆的id）。gm_memory只增（客观事实）；char_memory须带owner。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["add", "update"]},
                        "id": {
                            "type": "string",
                            "description": "update 必填：旧记忆的 id（如 gm_5）。add 不用给。",
                        },
                        "collection": {
                            "type": "string",
                            "enum": ["gm_memory", "char_memory"],
                        },
                        "content": {"type": "string"},
                        "time": {
                            "type": "string",
                            "description": "游戏时间，形如1220-01-01",
                        },
                        "owner": {
                            "type": "string",
                            "description": "写char_memory时必填：这是谁的记忆",
                        },
                        "kind": {
                            "type": "string",
                            "description": "可选子类，如 event/fact/knowledge/relationship/feeling",
                        },
                    },
                    "required": ["operation", "collection", "content"],
                },
            },
        },
        DB_add_and_update_tool,
    ),
    (
        "DB_query_tool",
        {
            "type": "function",
            "function": {
                "name": "DB_query_tool",
                "description": "检索长期记忆。游戏进行中主持人确认历史信息（尤其NPC出场或玩家提问时）用。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "必选，查询内容"},
                        "collection": {
                            "type": "string",
                            "enum": ["gm_memory", "char_memory"],
                            "description": "gm_memory=主持人客观事实（全局）；char_memory=角色主观记忆（须给owner）",
                        },
                        "owner": {
                            "type": "string",
                            "description": "查char_memory时必填：这是谁的记忆（角色名）",
                        },
                        "time": {
                            "type": "string",
                            "description": "可选，按游戏时间筛选，形如1220-01-01",
                        },
                        "n": {
                            "type": "integer",
                            "description": "可选，返回条数（默认2）",
                        },
                    },
                    "required": ["content", "collection"],
                },
            },
        },
        DB_query_tool,
    ),
    (
        "query_nearby",
        {
            "type": "function",
            "function": {
                "name": "query_nearby",
                "description": "查询南宋扬州地图上某坐标附近的地点（精确空间查询）。用于回答“这附近有什么”“附近有没有客栈/茶坊/医馆”等地图问题。坐标为 "
                "WGS84 经纬度，经度约 118.9~119.96，纬度约 32.17~32.68。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "lon": {"type": "number", "description": "经度"},
                        "lat": {"type": "number", "description": "纬度"},
                        "radius_km": {
                            "type": "number",
                            "description": "查询半径（公里），默认1",
                        },
                        "kind": {
                            "type": "string",
                            "description": "南宋类别，如：酒楼/茶坊/客栈/食铺/寺/观/祠/青楼/教坊/画舫/瓦舍/勾栏/坊/桥/渡口/码头/城门/医馆/药铺/市集/书院 "
                            "等，可选",
                        },
                        "category": {
                            "type": "string",
                            "description": "数据大类：water/waterway/road/building/custom/area/place/tourism/historic "
                            "等，可选",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "最多返回条数，默认20",
                        },
                    },
                    "required": ["lon", "lat"],
                },
            },
        },
        query_nearby,
    ),
    (
        "query_place",
        {
            "type": "function",
            "function": {
                "name": "query_place",
                "description": "按名称（模糊）或类别查找南宋扬州地图上的地点，返回其坐标与属性。用于“文昌阁在哪”“有哪些青楼”“太平坊在何处”这类问题。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "地点名称，支持模糊匹配，如“文昌阁”“太平坊”",
                        },
                        "kind": {"type": "string", "description": "南宋类别，可选"},
                        "category": {"type": "string", "description": "数据大类，可选"},
                        "limit": {
                            "type": "integer",
                            "description": "最多返回条数，默认20",
                        },
                    },
                    "required": [],
                },
            },
        },
        query_place,
    ),
    (
        "list_map_kinds",
        {
            "type": "function",
            "function": {
                "name": "list_map_kinds",
                "description": "列出南宋扬州地图上所有地点类别（kind）及数量，用于了解地图上存在哪些类型的场所。",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        list_map_kinds,
    ),
    (
        "update_place_note",
        {
            "type": "function",
            "function": {
                "name": "update_place_note",
                "description": (
                    "【仅存档蒸馏时使用】把本局在某地点发生的事记一条进该地点的**见闻**"
                    "（如某人被强暴、某处起过冲突、某桥塌了）。以后任何查询命中该地名都会显示出来。"
                    "一条一句，写清楚时间/人物/事由；只记值得记住的大事，小事不记。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "place": {"type": "string", "description": "地名（与地图上的名称一致，如「怀茂青楼」）"},
                        "note": {"type": "string", "description": "发生了什么，一句话"},
                        "time": {"type": "string", "description": "游戏时间，如 1220-01-16"},
                    },
                    "required": ["place", "note"],
                },
            },
        },
        update_place_note,
    ),
    (
        "update_location",
        {
            "type": "function",
            "function": {
                "name": "update_location",
                "description": "移动玩家的位置。当玩家说要去某地、前往某处、离开当前地点等移动行为时必须调用本工具，不要用文件工具直接改 "
                "基本信息.json "
                "的位置字段。可用地名（如“东关街”“文昌阁”“太平坊”），也可直接给经纬度。移动成功后会自动把该处标记为已探索。"
                "**只移动玩家明确要去的地方**；返回会给出“移动距离（米）”与“耗时提示”，据此决定叙事与是否 `update_time`（短距离不要推进时辰）。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "place_name": {
                            "type": "string",
                            "description": "目标地名，支持模糊匹配，如“东关街”“太平坊”“大明寺”",
                        },
                        "lon": {
                            "type": "number",
                            "description": "目标经度（若已知，与 "
                            "lat "
                            "一起直接传）",
                        },
                        "lat": {
                            "type": "number",
                            "description": "目标纬度（若已知，与 "
                            "lon "
                            "一起直接传）",
                        },
                        "move_mode": {
                            "type": "string",
                            "description": "可选，移动方式，如“步行”“骑马”“乘船”“乘轿”，用于叙事",
                        },
                    },
                    "required": [],
                },
            },
        },
        update_location,
    ),
    (
        "update_time",
        {
            "type": "function",
            "function": {
                "name": "update_time",
                "description": "修改或推进游戏时间。玩家睡觉、赶路、等待、劳作、活动结束等导致时间流逝时必须调用，不要用文件工具直接改 "
                "基本信息.json 的时间字段。**以十二时辰计，每时辰 8 刻（1 刻 ≈ 15 分钟），不使用 24 小时制。**"
                "日期格式 YYYY-MM-DD，时辰为十二时辰之一：子时、丑时、寅时、卯时、辰时、巳时、午时、未时、申时、酉时、戌时、亥时。"
                "两种用法：1) 直接设置 date / shichen / ke；2) 用 advance_shichen（时辰）或 advance_ke（刻）推进"
                "（8 刻 = 1 时辰，12 时辰 = 1 天，跨过子时算新一天）。短时间流逝用 advance_ke（如过了一刻钟传 advance_ke=1）。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": "新日期，格式 YYYY-MM-DD，如 1220-01-16",
                        },
                        "shichen": {
                            "type": "string",
                            "description": "新时辰，十二时辰之一，如 辰时、酉时",
                        },
                        "ke": {
                            "type": "integer",
                            "description": "新刻，0-7（每时辰 8 刻，1 刻 ≈ 15 分钟）",
                        },
                        "advance_shichen": {
                            "type": "integer",
                            "description": "推进的时辰数（正整数）。12 个时辰 = 1 天；如 6 表示过了 6 个时辰（半天）。",
                        },
                        "advance_ke": {
                            "type": "integer",
                            "description": "推进的刻数（正整数）。8 刻 = 1 时辰；如 1 表示过了一刻钟（约 15 分钟）。",
                        },
                    },
                    "required": [],
                },
            },
        },
        update_time,
    ),
    (
        "update_weather",
        {
            "type": "function",
            "function": {
                "name": "update_weather",
                "description": "手动覆盖游戏天气（仅特殊剧情需要，如法术改天、极端事件）。常规天气变化请用 "
                "get_weather 查表。只传需要修改的字段，不传的保持原样。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "condition": {
                            "type": "string",
                            "description": "天气状况，如：晴、多云、阴、小雨、大雨、雪、雾",
                        },
                        "temperature": {
                            "type": "string",
                            "description": "温度体感，如：微凉、温暖、寒冷、炎热",
                        },
                        "wind": {
                            "type": "string",
                            "description": "风力，如：无风、轻风、微风、大风",
                        },
                        "description": {
                            "type": "string",
                            "description": "天气整体描述，如：宜人、闷热、清冷",
                        },
                    },
                    "required": [],
                },
            },
        },
        update_weather,
    ),
    (
        "get_weather",
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "查询天气：根据日期与区域查天气数据表，把结果写入基本信息.json的天气字段。时间推进到第二天或未来某一天时必须调用。可传 "
                "date/region 查询指定日期或区域的天气。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "date": {
                            "type": "string",
                            "description": "可选，日期 " "YYYY-MM-DD，默认玩家当前日期",
                        },
                        "region": {
                            "type": "string",
                            "description": "可选，区域名，如 "
                            "扬州/临安/成都/开封，默认玩家当前区域",
                        },
                    },
                    "required": [],
                },
            },
        },
        get_weather,
    ),
    (
        "daily_event_dice",
        {
            "type": "function",
            "function": {
                "name": "daily_event_dice",
                "description": "日常骰子事件：玩家在城市里主动说「投骰子」时调用。一级骰定事件类型（场景热闹/城市风味/有人搭话/麻烦与危险），二级骰加混乱修正定烈度（偏顺/中性/带刺/危险）。返回后主持人按事件类型与档位叙述。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "chaos": {
                            "type": "number",
                            "description": "可选，混乱值 "
                            "0-100。不传则从 "
                            "混乱度.json "
                            "读取",
                        }
                    },
                    "required": [],
                },
            },
        },
        daily_event_dice,
    ),
    (
        "travel_event_dice",
        {
            "type": "function",
            "function": {
                "name": "travel_event_dice",
                "description": "旅途骰子事件：玩家在非城市旅途（陆路/水路/海路）中掷。单骰加混乱修正，低顺高不顺，返回事件等级（顺风顺水/偶遇友善/平淡无事/天气变化/小波折/旅途异象/麻烦上门/危险）。返回后主持人按等级叙述，异象/麻烦要从已有钩子推进。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "chaos": {
                            "type": "number",
                            "description": "可选，混乱值 "
                            "0-100。不传则从 "
                            "混乱度.json "
                            "读取",
                        }
                    },
                    "required": [],
                },
            },
        },
        travel_event_dice,
    ),
]


TOOLS = {name: (schema, fn) for name, schema, fn in _ENTRIES}
#: 仅存档蒸馏回合可见的工具（不发给游戏中的主持人，防误用）
_SAVE_ONLY = {"update_character_archive", "update_place_note"}
#: 游戏中（正常回合）用
ALL_TOOLS = [schema for name, schema, _fn in _ENTRIES if name not in _SAVE_ONLY]
#: 存档蒸馏回合用（含存档专用工具）
SAVE_TOOLS = [schema for _name, schema, _fn in _ENTRIES]
TOOLS_MAP = {name: fn for name, _schema, fn in _ENTRIES}
