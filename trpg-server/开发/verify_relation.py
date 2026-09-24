# -*- coding: utf-8 -*-
"""
verify_relation.py
==================
【一次性验证脚本，非正式模块】好感度增减是否适合交给本地小模型（Qwen3-4B）。

背景：
    任务完成 / NPC 反应需要一个「好感度」数值（`游戏数据/关系.json`，-100~+100）。
    决策不交给大模型（不给它好感度工具）；候选方案是**小模型**每回合判一次。

本脚本验证能力：
    用一批带**人工标注**的真实感场景，逐条（或批量）问 4B「这个 NPC 对梁峰的好感度应如何变」，
    统计：**方向命中率（最要紧）**、档位命中率、危险反向错误、越界、失败、延迟、重复稳定性。

设计决定（重要）：
    小模型**不输出数字**，只从五档里选一个 —— `明显下降 / 略降 / 不变 / 略升 / 明显升`；
    档位 → 数值由**代码**映射（生产里走 `配置/任务.json` 或 `关系.json` 的映射表）。
    4B 对绝对数字没有校准能力；封闭枚举既好测又稳。

运行（需 LM Studio 已加载 qwen/qwen3-4b-2507）：
    cd trpg-server
    python 开发/verify_relation.py                 # 单条 + 批量
    python 开发/verify_relation.py --mode single
    python 开发/verify_relation.py --repeats 3     # 看稳定性
    python 开发/verify_relation.py --mock          # 只验脚本流程，不调模型

退出码：0=跑完；2=小模型不可用（LM Studio 没起 / 模型没加载）。
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

# 允许 `python 开发/verify_relation.py` 直接跑（把 trpg-server 加入 import 路径）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")   # Windows 控制台默认 GBK，中文会乱码
except Exception:
    pass

from tools.小模型 import small_model  # noqa: E402

# ------------------------------------------------------------
# 五档 + 方向
# ------------------------------------------------------------
BANDS = ["明显下降", "略降", "不变", "略升", "明显升"]
SIGN = {"明显下降": -1, "略降": -1, "不变": 0, "略升": 1, "明显升": 1}

#: 生产候选提示词（relation_sim.py 若落地，用这一版）
SYSTEM = (
    "你是南宋武侠小说的「好感度标注器」，只输出 JSON。"
    "给你一段本轮叙事（旁白 + 台词）、某个角色对梁峰的**当前好感度**，"
    "判断**这个角色对梁峰的好感度**在本轮后应如何变化。"
    "只能从五档里选一个，不得自创、不得输出数字："
    "明显下降 / 略降 / 不变 / 略升 / 明显升。\n"
    "判断原则：\n"
    "1. 只看**这个角色自己感知到**的梁峰言行；梁峰做的好事若该角色不知情、没看见，记「不变」。\n"
    "2. 同一件事对不同角色轻重不同——看这个角色的立场与底线。\n"
    "3. 真心帮助、守信、维护、舍身相护 → 升；侮辱、威胁、失约、背叛、触其底线 → 降。\n"
    "4. 虚伪讨好、敷衍、无关寒暄 → 不变。\n"
    "5. 拿不准时一律「不变」。\n"
    "禁止思考、禁止解释、禁止输出 JSON 以外的任何内容。/no_think"
)

MOCK = False


def _ask(system: str, user: str, schema: dict, max_tokens: int, timeout: float):
    if MOCK:
        props = schema.get("properties") or {}
        return {k: ((v.get("enum") or ["不变"])[0]) for k, v in props.items()}
    return small_model.ask_json(system, user, schema, max_tokens=max_tokens, timeout=timeout)


# ------------------------------------------------------------
# 测试用例
#   npc     : 要判断好感度的角色
#   now     : 当前好感度（给模型参考）
#   scene   : 本轮整段叙事（旁白 + 台词）
#   accept  : 可接受的档位（第一个为首选）；方向必须一致，档位可放宽
#   why     : 人工标注的理由（报告里显示，便于复盘）
# ------------------------------------------------------------
CASES = [
    {"npc": "龙湘", "now": 20, "accept": ["略升", "明显升"],
     "scene": "旁白：几个泼皮围住龙湘讨要酒钱。梁峰一步跨上前，把几枚铜钱拍在桌上：「算我的。」\n"
              "龙湘：「咦？你这人倒有意思。」",
     "why": "替她解围付账"},
    {"npc": "郁竹", "now": 30, "accept": ["明显升"],
     "scene": "旁白：梁峰从火里将郁竹背了出来，自己手臂烧焦一片。\n"
              "郁竹：「你……你疯了么！」",
     "why": "舍身救她性命"},
    {"npc": "魏菊", "now": 0, "accept": ["明显下降"],
     "scene": "梁峰：「一个卖笑的，也配谈什么骨气。」\n"
              "旁白：魏菊脸色一白，手中茶盏几乎捏碎。",
     "why": "当面侮辱其人格"},
    {"npc": "上官隼", "now": -20, "accept": ["略降", "明显下降"],
     "scene": "梁峰按住刀柄：「我劝你想清楚再说。」\n"
              "旁白：上官隼眯起眼，缓缓后退半步。",
     "why": "武力威胁"},
    {"npc": "王二壮", "now": 40, "accept": ["不变"],
     "scene": "梁峰：「今日天色不错。」\n王二壮：「是啊，是啊。」",
     "why": "无关寒暄"},
    {"npc": "王二壮", "now": 40, "accept": ["不变"],
     "scene": "旁白：梁峰趁无人，把王二壮落在酒肆的钱袋悄悄送了回去。\n"
              "旁白：王二壮自始至终并不知晓此事。",
     "why": "帮了但对方不知情（关键：应不变）"},
    {"npc": "唐默铃", "now": 15, "accept": ["明显升", "略升"],
     "scene": "旁白：三日前答应替唐默铃寻回药方，梁峰今日果然将方子放到她案上。\n"
              "唐默铃：「你真的……找到了！」",
     "why": "信守承诺，对方极在意"},
    {"npc": "唐默铃", "now": 15, "accept": ["明显下降", "略降"],
     "scene": "旁白：梁峰把答应唐默铃的事忘得一干二净，三日后才想起。\n"
              "唐默铃：「算了，我本就不该指望你。」",
     "why": "失约"},
    {"npc": "温夫人", "now": 0, "accept": ["不变", "略降"],
     "scene": "梁峰：「夫人真是天人之姿，晚生仰慕已久。」\n"
              "旁白：温夫人淡淡瞥了他一眼，并不答话。",
     "why": "虚伪讨好（老练者看得穿）"},
    {"npc": "温夫人", "now": 10, "accept": ["明显下降"],
     "scene": "梁峰：「你们这群女子聚在一处，成什么体统。」\n"
              "旁白：温夫人手中琵琶一停，弦音骤冷。",
     "why": "触其底线（侮辱锦香宫众女）"},
    {"npc": "龙湘", "now": 20, "accept": ["略升", "明显升"],
     "scene": "旁白：梁峰把最后半只鸡腿递过去。\n龙湘：「唔……那我不客气啦！」（她啃得油光满面）",
     "why": "分享食物（投其所好）"},
    {"npc": "刘鄂", "now": 0, "accept": ["明显升", "略升"],
     "scene": "旁白：旁人讥讽刘鄂是海寇，梁峰拍案而起：「他救过一村人的命，你们算什么东西。」\n"
              "刘鄂：「哈哈哈！好小子！」（他重重拍了下梁峰肩膀）",
     "why": "当众维护"},
    {"npc": "郁竹", "now": 20, "accept": ["明显下降", "略降"],
     "scene": "旁白：眼睁睁看着那少年被拖走，梁峰始终没有出手。\n"
              "郁竹回头看了他一眼，什么也没说。",
     "why": "见死不救（她目睹）"},
    {"npc": "夏侯兰", "now": 0, "accept": ["略升", "不变"],
     "scene": "梁峰：「实不相瞒，那日是我失手，不是旁人。」\n"
              "旁白：夏侯兰指尖一顿，重新打量他。",
     "why": "坦白过错（诚实加分，但不必然）"},
    {"npc": "瑞杏", "now": 0, "accept": ["不变", "略降"],
     "scene": "梁峰不等瑞杏说完便抢白：「少说这些弯弯绕绕。」\n"
              "旁白：瑞杏端起茶盏，不置可否。",
     "why": "无礼打断（对方城府深，反应淡）"},
    {"npc": "王二壮", "now": 40, "accept": ["略升", "明显升"],
     "scene": "旁白：梁峰将一坛醉仙酿放到桌上。\n王二壮眼睛一亮：「好小子，懂我！」",
     "why": "投其所好送礼"},
    {"npc": "申屠龙", "now": 0, "accept": ["略降", "不变"],
     "scene": "旁白：一封密信自梁峰袖中滑落，落款却非他的字迹。\n"
              "旁白：申屠龙盯着那封信，久久不语。",
     "why": "疑似背叛、证据不足（模糊）"},
    {"npc": "叶云裳", "now": 30, "accept": ["明显升"],
     "scene": "旁白：刀锋袭来，梁峰侧身挡在叶云裳身前，肩上血如泉涌。\n叶云裳：「哥哥——！」",
     "why": "舍身相护"},
    {"npc": "刘鄂", "now": 20, "accept": ["明显下降", "略降"],
     "scene": "旁白：梁峰与追杀白鲨帮的官军把酒言欢。\n旁白：刘鄂远远看在眼里。",
     "why": "与敌方交好（立场背叛）"},
    {"npc": "魏菊", "now": -10, "accept": ["明显升"],
     "scene": "旁白：梁峰从火中抢出那本烧焦的曲谱，交到魏菊手中。\n"
              "旁白：魏菊接过，指节发白。",
     "why": "救回她珍视之物（与此前侮辱对照）"},

    # ---- 中性用例：普通对话 / 日常互动，期望一律「不变」——专测误动率 ----
    {"npc": "王二壮", "now": 20, "accept": ["不变"],
     "scene": "梁峰：「请问，城南崔家怎么走？」\n王二壮：「往南走两个街口便是。」",
     "why": "问路"},
    {"npc": "龙湘", "now": 20, "accept": ["不变"],
     "scene": "梁峰：「这鸡腿怎么卖？」\n龙湘：「五文一只。」\n旁白：梁峰付了钱，接过鸡腿。",
     "why": "买卖交易"},
    {"npc": "温夫人", "now": 10, "accept": ["不变"],
     "scene": "梁峰：「夫人院中花木甚好。」\n温夫人：「公子过奖。」",
     "why": "客套称赞"},
    {"npc": "唐默铃", "now": 15, "accept": ["不变"],
     "scene": "梁峰：「这方子里的甘草是做什么用的？」\n唐默铃：「调和诸药罢了。」",
     "why": "中性求教"},
    {"npc": "刘鄂", "now": 20, "accept": ["不变"],
     "scene": "梁峰：「今日风浪不小。」\n刘鄂：「海上日日如此。」",
     "why": "普通寒暄"},
    {"npc": "上官隼", "now": -20, "accept": ["不变"],
     "scene": "旁白：梁峰与上官隼在街口相遇，二人拱手为礼，各自走过。",
     "why": "点头致意"},
    {"npc": "瑞杏", "now": 0, "accept": ["不变"],
     "scene": "旁白：梁峰在茶楼看瑞杏与人弈棋，看了半个时辰，未发一言。",
     "why": "旁观不语"},
    {"npc": "王二壮", "now": 20, "accept": ["不变"],
     "scene": "梁峰：「多谢指点。」\n王二壮：「小事小事。」",
     "why": "道谢"},
]

# ------------------------------------------------------------
# 立场档案（拟进 关系.json 的 NPC 上下文）
#   小模型之前错判（如刘鄂、瑞杏），根因就是缺这些。
# ------------------------------------------------------------
PROFILES = {
    "龙湘": {"所属": "锦香宫", "主张": "护同门、重情义",
             "偏好": ["吃食", "爽快", "护着锦香宫的人"],
             "反感": ["欺侮女子", "小气", "虚伪"]},
    "郁竹": {"所属": "峨嵋（六大派）", "主张": "行侠仗义、护无辜",
             "底线": ["见死不救"],
             "偏好": ["救人", "坦荡", "勇气"],
             "反感": ["见死不救", "怯懦", "滥杀"]},
    "魏菊": {"所属": "杏花仙一系", "主张": "琴艺自重、清高",
             "偏好": ["琴曲", "才艺", "知音"],
             "反感": ["轻慢她的才艺", "侮辱卖艺女子", "粗鲁"]},
    "上官隼": {"所属": "上官世家", "主张": "维护朝廷体面与家族利益",
               "偏好": ["识时务", "名分", "体面"],
               "反感": ["武力威胁", "失礼", "江湖草莽"]},
    "王二壮": {"所属": "丐帮", "主张": "劫富济贫、讲义气",
               "偏好": ["酒", "义气", "豪爽", "施舍"],
               "反感": ["吝啬", "看不起穷人", "官腔"]},
    "唐默铃": {"所属": "唐门", "主张": "守信、钻研药毒",
               "偏好": ["守信", "看重她的药方/学识"],
               "反感": ["失约", "轻视她"]},
    "温夫人": {"所属": "锦香宫", "主张": "护住那群女子",
               "底线": ["侮辱锦香宫众女"],
               "偏好": ["尊重女子", "护弱", "真心"],
               "反感": ["轻浮讨好", "侮辱女子"]},
    "刘鄂": {"所属": "白鲨帮", "主张": "抗倭护海民，与官军、朝廷为敌",
             "底线": ["背叛白鲨帮", "与官军勾结"],
             "偏好": ["义气", "豪爽", "并肩抗倭", "骂官军"],
             "反感": ["与官军交好", "畏缩", "看不起海寇"]},
    "夏侯兰": {"所属": "六大派", "主张": "名门正道、观人",
               "偏好": ["诚实", "坦荡"],
               "反感": ["欺骗", "伪饰"]},
    "瑞杏": {"所属": "杏花仙（瑞家）", "主张": "以天下为棋，城府极深",
             "偏好": ["有趣的人", "有主见"],
             "反感": ["粗鲁无礼（但不为小事动容）"]},
    "申屠龙": {"所属": "千灯楼", "主张": "邪道、以力量为尊",
               "底线": ["背叛"],
               "偏好": ["力量", "有用之人", "合作"],
               "反感": ["背叛", "欺瞒"]},
    "叶云裳": {"所属": "六大派", "主张": "依恋梁峰、怕被丢下",
               "底线": ["弃她不顾"],
               "偏好": ["保护她", "陪伴"],
               "反感": ["弃她不顾"]},
}

NO_PROFILE = False
TWO_STAGE = False

#: 两段式追加的系统指令：先把“该不该动”与“动多少”分开
SYSTEM_TWO_STAGE = (
    "\n你必须先判断：本轮梁峰是否对**这个角色**（或他/她在意的人/事/立场）做出了**有意义的举动**，"
    "或该角色是否**目睹**了这样的举动。\n"
    "- 「有」：帮助、伤害、守信、失约、维护、冒犯、威胁、背叛、舍身相护、投其所好……"
    "（**不论该角色有没有开口**）。\n"
    "- 「无」：只是旁观、路过、无实质举动；买卖、问路、客套、普通寒暄、中性求教。\n"
    "- 注意：「未发一言」不等于「无」——若梁峰当着他的面做了针对他立场的事"
    "（如与他的仇敌交好），应记「有」。\n"
    "宁可不记，不可误动。"
)


def _profile_text(npc: str) -> str:
    """把立场档案拼成给模型的文本（--no-profile 时返回空）。"""
    if NO_PROFILE:
        return ""
    p = PROFILES.get(npc)
    if not p:
        return ""
    lines = ["立场档案："]
    for k in ("所属", "主张", "底线", "偏好", "反感"):
        v = p.get(k)
        if v:
            lines.append(f"  {k}：{'、'.join(v) if isinstance(v, list) else v}")
    return "\n".join(lines) + "\n"


def _selfcheck() -> None:
    bad = []
    for i, c in enumerate(CASES):
        if not c.get("npc") or not c.get("scene"):
            bad.append(f"#{i} 缺 npc/scene")
        if not c.get("accept"):
            bad.append(f"#{i} 缺 accept")
        for b in c.get("accept", []):
            if b not in BANDS:
                bad.append(f"#{i} accept「{b}」不在档位")
        if c.get("npc") not in PROFILES:
            bad.append(f"#{i} {c.get('npc')} 缺 PROFILES 档案")
    if bad:
        print("用例自检失败：")
        for b in bad:
            print("  -", b)
        sys.exit(1)


# ------------------------------------------------------------
# 调用
# ------------------------------------------------------------
def single_call(case: dict, timeout: float):
    if TWO_STAGE:
        schema = {
            "type": "object",
            "properties": {
                "互动": {"type": "string", "enum": ["有", "无"]},
                "judgement": {"type": "string", "enum": BANDS},
            },
            "required": ["互动", "judgement"],
        }
    else:
        schema = {
            "type": "object",
            "properties": {"judgement": {"type": "string", "enum": BANDS}},
            "required": ["judgement"],
        }
    user = (
        f"角色：{case['npc']}\n"
        f"当前好感度：{case.get('now', 0)}\n"
        f"{_profile_text(case['npc'])}"
        f"本轮叙事：\n{case['scene']}\n"
        + ("先判断「互动」有无，再给好感度变化档位。"
           if TWO_STAGE else
           f"请判断这个角色对梁峰的好感度应如何变化（五档选一）：{BANDS}")
    )
    system = SYSTEM + (SYSTEM_TWO_STAGE if TWO_STAGE else "")
    t0 = time.time()
    try:
        r = _ask(system, user, schema, max_tokens=40, timeout=timeout)
    except Exception as e:
        return None, time.time() - t0, {"error": f"{type(e).__name__}: {e}"}
    if not isinstance(r, dict):
        return None, time.time() - t0, r
    if TWO_STAGE:
        # 「无互动」→ 代码强制不变（把“该不该动”与“动多少”分开）
        if r.get("互动") == "无":
            return "不变", time.time() - t0, {"gated": True, "raw": r}
        return r.get("judgement"), time.time() - t0, r
    return r.get("judgement"), time.time() - t0, r


def batch_call(cases: list[dict], timeout: float):
    """一次问全部（每个用例一个 L 键；生产里一回合多 NPC 同场景）。"""
    keys = [f"L{n}" for n in range(len(cases))]
    props = {keys[n]: {"type": "string", "enum": BANDS} for n in range(len(cases))}
    schema = {"type": "object", "properties": props, "required": keys}
    lines = []
    for n, c in enumerate(cases):
        lines.append(
            f"- {keys[n]}｜角色：{c['npc']}｜当前好感度：{c.get('now', 0)}"
            f"｜档案：{_profile_text(c['npc']).replace(chr(10), ' ').strip() or '（无）'}"
            f"｜场景：{c['scene']}"
        )
    user = "下面每一行各判断一个角色的好感度变化：\n" + "\n".join(lines)
    t0 = time.time()
    try:
        r = _ask(SYSTEM, user, schema, max_tokens=24 * len(cases), timeout=timeout)
    except Exception as e:
        return {}, time.time() - t0, {"error": f"{type(e).__name__}: {e}"}
    return (r or {}), time.time() - t0, r


# ------------------------------------------------------------
# 报告
# ------------------------------------------------------------
def _fmt(x: float) -> str:
    return f"{x:.2f}s"


def _lat_stats(lat: list[float]) -> str:
    lat = [x for x in lat if x > 0]
    if not lat:
        return "（无模型调用）"
    lat.sort()
    p95 = lat[min(len(lat) - 1, int(round(0.95 * (len(lat) - 1))))]
    return (f"n={len(lat)}  均 {statistics.mean(lat):.2f}s  "
            f"p50 {statistics.median(lat):.2f}s  p95 {p95:.2f}s  max {max(lat):.2f}s")


def _verdict(got: str, case: dict) -> str:
    if got is None:
        return "失败"
    if got not in BANDS:
        return "越界"
    if got == case["accept"][0]:
        return "首选"
    if got in case["accept"]:
        return "可接受"
    return "偏离"


def _sign_class(got: str, case: dict) -> str:
    """方向层面的判定：方向对 / 反向（危险） / 该动却不动 / 该不动却动。"""
    exp = {SIGN[b] for b in case["accept"]}
    g = SIGN[got]
    if g in exp:
        return "方向对"
    if exp == {0}:
        return "该不动却动"
    if 1 in exp and g == -1:
        return "反向"
    if -1 in exp and g == 1:
        return "反向"
    return "该动却不动"


def run_single(cases, timeout):
    print("\n" + "=" * 78)
    print("【单条模式】逐条调用小模型")
    print("=" * 78)
    band_hit = dir_hit = reverse = over = failed = false_move = 0
    lats = []
    for i, c in enumerate(cases):
        got, dt, raw = single_call(c, timeout)
        status = _verdict(got, c)
        lats.append(dt)
        if got is None:
            failed += 1
        elif got not in BANDS:
            over += 1
        else:
            if got == c["accept"][0]:
                band_hit += 1
            sc = _sign_class(got, c)
            if sc == "方向对":
                dir_hit += 1
            elif sc == "反向":
                reverse += 1
            elif sc == "该不动却动":
                false_move += 1
        mark = {"首选": "✅", "可接受": "🟡", "偏离": "❌", "越界": "⛔", "失败": "💥"}.get(status, "?")
        print(f"{mark} [{i:02d}] {c['npc']:<4} 得={str(got):<5} 首选={c['accept'][0]:<5} "
              f"可接受={c['accept']}  {_fmt(dt)}  {status}（{c['why']}）")
        if raw and isinstance(raw, dict) and raw.get("error"):
            print(f"        raw error: {raw['error']}")
    n = len(cases)
    print("-" * 78)
    print(f"总 {n} 条")
    print(f"★ 方向命中率 {dir_hit}/{n}    档位首选命中 {band_hit}/{n}    "
          f"误动（该不变却变）{false_move}    危险反向 {reverse}    越界 {over}    失败 {failed}")
    print("延迟：" + _lat_stats(lats))
    return dir_hit, n, band_hit, reverse, over, failed, false_move


def run_batch(cases, timeout):
    print("\n" + "=" * 78)
    print("【批量模式】全部用例一次问")
    print("=" * 78)
    got_map, dt, raw = batch_call(cases, timeout)
    band_hit = dir_hit = reverse = over = failed = false_move = 0
    for n, c in enumerate(cases):
        got = got_map.get(f"L{n}")
        if got is None:
            failed += 1
            status = "失败"
        elif got not in BANDS:
            over += 1
            status = "越界"
        else:
            if got == c["accept"][0]:
                band_hit += 1
            sc = _sign_class(got, c)
            if sc == "方向对":
                dir_hit += 1
            elif sc == "反向":
                reverse += 1
            elif sc == "该不动却动":
                false_move += 1
            status = "首选" if got == c["accept"][0] else ("可接受" if got in c["accept"] else "偏离")
        mark = {"首选": "✅", "可接受": "🟡", "偏离": "❌", "越界": "⛔", "失败": "💥"}.get(status, "?")
        print(f"{mark} [{n:02d}] {c['npc']:<4} 得={str(got):<5} 首选={c['accept'][0]:<5}  {status}")
    if raw and isinstance(raw, dict) and raw.get("error"):
        print("raw error:", raw["error"])
    print("-" * 78)
    print(f"一次调用含 {len(cases)} 条，耗时 {_fmt(dt)}")
    print(f"★ 方向命中率 {dir_hit}/{len(cases)}    档位首选命中 {band_hit}/{len(cases)}    "
          f"误动（该不变却变）{false_move}    危险反向 {reverse}    越界 {over}    失败 {failed}")
    return dir_hit, len(cases), band_hit, reverse, over, failed, false_move


def main():
    ap = argparse.ArgumentParser(description="验证小模型判好感度增减是否可行")
    ap.add_argument("--mode", choices=["single", "batch", "both"], default="both")
    ap.add_argument("--timeout", type=float, default=10.0, help="单次调用超时（秒）")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条（0=全部）")
    ap.add_argument("--repeats", type=int, default=1, help="重复轮数（看稳定性）")
    ap.add_argument("--mock", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--no-profile", action="store_true", help="不带立场档案（对照组）")
    ap.add_argument("--two-stage", action="store_true", help="两段式：先判是否有实质互动")
    args = ap.parse_args()

    global MOCK, NO_PROFILE, TWO_STAGE
    MOCK = args.mock
    NO_PROFILE = args.no_profile
    TWO_STAGE = args.two_stage
    _selfcheck()
    cases = CASES[: args.limit] if args.limit > 0 else CASES

    if not MOCK and not small_model.available():
        print("❌ 小模型不可用：请确认 LM Studio 已启动并加载 qwen/qwen3-4b-2507。")
        print("   （只想验证脚本流程可用 --mock）")
        sys.exit(2)
    print(f"小模型{'[MOCK]' if MOCK else ''}；用例 {len(cases)} 条；"
          f"timeout={args.timeout}s；repeats={args.repeats}；"
          f"档案={'无（对照）' if NO_PROFILE else '带'}；"
          f"模式={'两段' if TWO_STAGE else '单段'}")

    agg = {"dir": 0, "n": 0, "band": 0, "rev": 0, "over": 0, "fail": 0, "fm": 0}
    for rep in range(args.repeats):
        if args.repeats > 1:
            print(f"\n########## 第 {rep + 1}/{args.repeats} 轮 ##########")
        if args.mode in ("single", "both"):
            d, n, b, r, o, f, fm = run_single(cases, args.timeout)
            agg["dir"] += d; agg["n"] += n; agg["band"] += b
            agg["rev"] += r; agg["over"] += o; agg["fail"] += f; agg["fm"] += fm
        if args.mode in ("batch", "both"):
            d, n, b, r, o, f, fm = run_batch(cases, args.timeout)
            agg["dir"] += d; agg["n"] += n; agg["band"] += b
            agg["rev"] += r; agg["over"] += o; agg["fail"] += f; agg["fm"] += fm
    if args.repeats > 1:
        print("\n" + "=" * 78)
        print(f"合计：方向命中 {agg['dir']}/{agg['n']}，档位首选 {agg['band']}/{agg['n']}，"
              f"误动 {agg['fm']}，危险反向 {agg['rev']}，越界 {agg['over']}，失败 {agg['fail']}")


if __name__ == "__main__":
    main()
