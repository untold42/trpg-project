# -*- coding: utf-8 -*-
"""
图标体检：找出「地图上会变成棕色圆点」的键。
    python check_icons.py

检查三件事（任一不满足，前端就会退化成棕色圆点）：
  1. `public/mapicons/<键>/{day,night}.png` 是否都存在且非空
  2. geojson 里用到的 icon 键是否都有文件（反向也要查多余的文件）
  3. 文件是否是浏览器能读的 PNG（签名/IHDR/IDAT 完整、CRC 正确）
"""

import json
import os
import re
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
MAPICONS = os.path.join(ROOT, "trpg-client", "public", "mapicons")
GEOJSON = os.path.join(ROOT, "trpg-client", "public", "data", "clickable.geojson")


def png_sane(p):
    d = open(p, "rb").read()
    if d[:8] != b"\x89PNG\r\n\x1a\n":
        return "PNG 签名错误"
    i, idat, n = 8, b"", 0
    while i < len(d):
        ln = struct.unpack(">I", d[i:i + 4])[0]
        typ = d[i + 4:i + 8]
        data = d[i + 8:i + 8 + ln]
        crc = struct.unpack(">I", d[i + 8 + ln:i + 12 + ln])[0]
        if zlib.crc32(d[i + 4:i + 8 + ln]) & 0xFFFFFFFF != crc:
            return "chunk %s CRC 错误" % typ.decode("latin1", "replace")
        if typ == b"IDAT":
            idat += data
        i += 12 + ln
        n += 1
        if typ == b"IEND":
            break
    if i != len(d):
        return "IEND 之后有多余字节（文件可能被截断/追加）"
    try:
        zlib.decompress(idat)
    except Exception as e:
        return "IDAT 解压失败：%s" % e
    return None


def main():
    keys = sorted(d for d in os.listdir(MAPICONS)
                  if os.path.isdir(os.path.join(MAPICONS, d)))
    used = set()
    if os.path.exists(GEOJSON):
        fc = json.load(open(GEOJSON, encoding="utf-8"))
        for f in fc["features"]:
            if f["properties"].get("icon"):
                used.add(f["properties"]["icon"])

    bad = []
    for k in keys:
        for m in ("day", "night"):
            p = os.path.join(MAPICONS, k, m + ".png")
            if not os.path.exists(p):
                bad.append("%s/%s.png 缺文件" % (k, m))
                continue
            if os.path.getsize(p) < 200:
                bad.append("%s/%s.png 文件过小" % (k, m))
            err = png_sane(p)
            if err:
                bad.append("%s/%s.png %s" % (k, m, err))

    missing_dir = sorted(used - set(keys))
    unused_dir = sorted(set(keys) - used)

    print("图标键 %d 个（geojson 用到 %d 个），文件 %d 张"
          % (len(keys), len(used), len(keys) * 2))
    print("文件损坏/缺失：%s" % (bad if bad else "无"))
    print("geojson 用到但没有文件夹（→ 必定是棕点）：%s" % (missing_dir if missing_dir else "无"))
    print("有文件夹但 geojson 没用到（不影响显示）：%s" % (unused_dir if unused_dir else "无"))
    print()
    if bad or missing_dir:
        print("**结论：地图上会有棕色圆点**")
        print("  先跑 make_icons.py --all 补齐，仍不显示就 Ctrl+Shift+R 强刷（浏览器可能缓存了旧的失败响应）")
        return 1
    print("结论：所有图标齐全且文件合法 —— 若地图上仍是棕点，那是**浏览器缓存**：Ctrl+Shift+R 强刷一次。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
