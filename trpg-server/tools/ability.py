import json
from pathlib import Path

ABILITY_PATH = Path("./tools/游戏数据/属性.json")

def get_ability():
    with open(ABILITY_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return json.dumps(data, ensure_ascii=False)