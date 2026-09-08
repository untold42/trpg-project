import json

with open("map_clean.json", "r", encoding="utf-8") as f:
    data = json.load(f)

print("顶层字段：", data.keys())
print("objects 类型：", type(data["objects"]))
print("objects 数量：", len(data["objects"]))

print("\n第一个 object：")
print(json.dumps(data["objects"][0], ensure_ascii=False, indent=2))
