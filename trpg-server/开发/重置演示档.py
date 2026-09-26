# -*- coding: utf-8 -*-
"""
重置演示档.py
=============
把「演示档」重置到开局：**只设位置与时间，其余一律初始化**。

默认落点：扬州城北郊外 **蜀冈中峰**（梁峰自枣阳逃难而来、先到城外）。
时间：1220-01-17 申时初刻（嘉定十三年正月十七）。

做的事：
    1. 先备份 游戏数据 / sessions / 归档存档 → `删档备份/<日期>_<名字>/`
    2. 重置 世界线程 / 导演简报 / 加成 / 足迹 / 状态
    3. 基本信息：保留「人物」，重设「时间」，清「天气」，位置交给 update_location 算（蜀冈）
    4. 时钟 → 开局时刻；地图设置 → yangzhou
    5. 写 游戏数据/任务.json（初始任务，时限用相对「时限时辰」，开局由代码换算）
    6. 清 sessions/current.jsonl、run_start_state.json、audit.log；清 归档存档/*.md
    7. 删过时的 曲牌.json

运行（**必须先停后端**）：cd trpg-server && python 开发/重置演示档.py
"""

from __future__ import annotations

import io
import json
import shutil
import sys
from pathlib import Path

SERVER = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from tools.核心.state_manager import state, GAME_DATA_DIR          # noqa: E402
from tools.核心.game_clock import (                                  # noqa: E402
    seconds_from_civil, civil_from_seconds, chinese_date, ganzhi_year,
)

# ---- 开局设定 ----
LON, LAT = 119.407477, 32.422021          # 蜀冈中峰
DATE, SHICHEN, KE = "1220-01-17", "申时", 0
BACKUP_NAME = "2026-09-25_演示档"

INITIAL_TASKS = {
    "任务": [
        {
            "id": "q_touqin", "标题": "投亲", "状态": "进行中",
            "可见": True, "来源": "初始",
            "描述": "梁峰自枣阳逃难至扬州，要去城南寻一门旧亲戚（崔家），问问父母的下落。",
            "委托人": "",
            "里程碑": [{"项": "打听到崔家住处", "状态": "未完成"},
                     {"项": "上门拜访", "状态": "未完成"},
                     {"项": "问出父母消息", "状态": "未完成"}],
            "时限文本": "三日内", "时限时辰": 36,
            "失败后果": "崔家已迁走或已故去，父母线索就此中断；梁峰在扬州举目无亲，盘缠将尽。",
            "真相": "崔家知道梁峰父母当年并非病故，而是被人害死；崔家收过一笔封口钱，这些年讳莫如深。崔家幼子对此并不知情。",
            "结局": "梁峰从崔家口中问出父母之死的实情与一个线索人名，正式踏入江湖。",
            "知情者": ["崔敬", "柳氏"],
            "揭示节奏": "崔家先回避、再闪烁其词，被一再追问才吐露一半；不得一见面就交底。",
            "扩展次数": 0, "已告知": False,
        },
    ]
}


def backup() -> Path:
    root = SERVER / "删档备份" / BACKUP_NAME
    if root.exists():
        shutil.rmtree(root)
    (root / "游戏数据").mkdir(parents=True)
    for f in Path(GAME_DATA_DIR).glob("*"):
        if f.is_file():
            shutil.copy2(f, root / "游戏数据" / f.name)
    for name in ("current.jsonl", "run_start_state.json", "audit.log"):
        p = SERVER / "sessions" / name
        if p.exists():
            (root / "sessions").mkdir(exist_ok=True)
            shutil.copy2(p, root / "sessions" / name)
    arch = SERVER / "归档存档"
    if arch.is_dir() and any(arch.glob("*.md")):
        shutil.copytree(arch, root / "归档存档", dirs_exist_ok=True)
    return root


def main():
    print("== 1) 备份 ==")
    root = backup()
    print("   备份 →", root)

    print("== 2) 重置档内数据 ==")
    state.save("世界线程", {"模拟游标": "", "人物线程": {}})
    state.save("导演简报", {"内容": ""})
    state.save("加成", {"_备注": "成长加成（buff）：目标 → {来源, 倍率, 到期(YYYY-MM-DD)}。", "生效": {}})
    state.save("足迹", {"points": [], "radius_km": 0.15})
    state.save("状态", {"生命值": 50, "生命上限": 50, "精力值": 75, "精力上限": 75,
                       "饥饿": 100, "健康": "康健", "饥饿挡位": "饱足"})
    state.save("地图设置", {"地图": "yangzhou",
                           "说明": "上次查看/选择的地图（仅兑底：玩家坐标在哪张图内就以哪张为准）。"})
    print("   世界线程/导演简报/加成/足迹/状态/地图设置 → 初始")

    print("== 3) 基本信息：时间 ==")
    s = seconds_from_civil(DATE, SHICHEN, KE)
    c = civil_from_seconds(s)
    basic = state.load("基本信息", {}) or {}
    basic["时间"] = {"日期": c["日期"], "时辰": c["时辰"], "刻": c["刻"],
                    "纪年": chinese_date(c), "干支": ganzhi_year(int(c["日期"][:4])) + "年"}
    basic.pop("天气", None)     # 让 weather_system 重新生成
    basic.pop("位置", None)     # 位置交给 update_location 算
    state.save("基本信息", basic)
    print("   ", c["日期"], c["时辰"], "刻", c["刻"], "|", basic["时间"]["纪年"])

    print("== 4) 位置 → 蜀冈中峰（扬州）==")
    from tools.大模型.location import update_location
    mv = update_location(lon=LON, lat=LAT, move_mode="重开")
    if not mv.get("success"):
        print("   ❌ 位置设置失败：", mv.get("error"))
        sys.exit(1)
    pos = (state.load("基本信息", {}) or {}).get("位置", {})
    print("   ", json.dumps(pos, ensure_ascii=False))
    # 重置足迹（update_location 会记一个点）
    state.save("足迹", {"points": [], "radius_km": 0.15})

    print("== 5) 时钟 ==")
    state.save("时钟", {"游戏秒": int(s), "状态": "paused"})
    print("   游戏秒 =", s, "→", civil_from_seconds(s))

    print("== 6) 任务.json（初始任务）==")
    state.save("任务", INITIAL_TASKS)
    print("   ", [t["标题"] for t in INITIAL_TASKS["任务"]])

    print("== 7) 清 sessions / 归档 / 过时文件 ==")
    for name in ("current.jsonl", "run_start_state.json"):
        p = SERVER / "sessions" / name
        if p.exists():
            p.unlink()
    (SERVER / "sessions" / "audit.log").write_text("", encoding="utf-8")
    removed = 0
    for f in (SERVER / "归档存档").glob("*.md"):
        f.unlink()
        removed += 1
    qu = Path(GAME_DATA_DIR) / "曲牌.json"
    if qu.exists():
        qu.unlink()
    print(f"   current.jsonl/run_start_state 已删；归档删 {removed} 个；曲牌.json 已删")

    print("\n✅ 演示档已重置：扬州郊外·蜀冈中峰，1220-01-17 申时初。重启后端生效。")


if __name__ == "__main__":
    main()
