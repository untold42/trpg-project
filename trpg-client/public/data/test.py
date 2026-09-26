import json
import time
from pathlib import Path

path_geojson = "C:\\Users\\20866\\Desktop\\trpg-project\\trpg-client\\public\\data\\yangzhou\\clickable.geojson"
path_art_assets= Path(r"C:\Users\20866\Desktop\trpg-project\trpg-client\src\assets\背景_重构")
st_geojson,st_art_assets=set(),set()

start=time.time()
with open (path_geojson,"r",encoding="utf-8") as f:
    text=json.load(f)
    
    for each in text["features"]:
        if "properties" in each:
            if "kind" in each["properties"]:
                st_geojson.add(each["properties"]["kind"])

for p in path_art_assets.iterdir():
    if p.is_dir():          # 只要文件夹，跳过文件
        st_art_assets.add(p.name)       # 只要名字，如 "子文件夹1

res=st_geojson - (st_art_assets & st_geojson)
print(res)

print(f"cost {time.time()-start} s")
exit(0)