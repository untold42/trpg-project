# -*- coding: utf-8 -*-
"""
game_clock.py
=============
连续游戏时钟（**时间的单一真相源**）。

设计（见 README.md 第六节）：
    - **单一标量**：自纪元起的整数「游戏秒」（epoch = 1220-01-01 子时初刻）。
    - **三态**：`running`（探索 / 叙事）/ `paused`（菜单 / 历史 / 失焦 / LLM 请求窗口）
      / `accruing`（战斗，按回合折算）。
    - **惰性求值**：不跑后台线程。`running` 时 now = 锚点秒 + (墙钟 − 锚点墙钟) × 倍率；
      其余状态冻结在锚点秒。
    - **投影**：派生出的 日期 / 时辰 / 刻 写回 `基本信息.json` 的「时间」字段，
      既有读取方（ui_sim / world_sim / 前端 `/state`）无需改动。

时刻换算（与 time_weather 一致）：
    - 1 刻 = 15 游戏分钟 = 900 游戏秒
    - 1 时辰 = 8 刻 = 7200 游戏秒
    - 1 天 = 12 时辰 = 96 刻 = 86400 游戏秒
    - 子时 = 一天的起点（与既有 update_time「跨过子时进入新一天」一致）

速率：默认 **1 真实分钟 = 1 刻**（15 游戏分钟）→ 15 游戏秒 / 真实秒。
     `TRPG_CLOCK_RATE` 可调。
开关：`TRPG_CLOCK=0` 关闭（时钟恒冻结，便于对照旧行为）。
"""

from __future__ import annotations

import datetime
import os
import threading
import time as _time

from tools.state_manager import state

# ------------------------------------------------------------
# 时间域常量
# ------------------------------------------------------------
# 十二时辰（顺序固定；子时 = 一天的起点）
SHICHEN = ["子时", "丑时", "寅时", "卯时", "辰时", "巳时",
           "午时", "未时", "申时", "酉时", "戌时", "亥时"]

KE_PER_SHICHEN = 8          # 每时辰 8 刻
KE_CN = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七"}

SECONDS_PER_KE = 15 * 60                               # 900
SECONDS_PER_SHICHEN = KE_PER_SHICHEN * SECONDS_PER_KE  # 7200
SECONDS_PER_DAY = len(SHICHEN) * SECONDS_PER_SHICHEN   # 86400

#: 纪元：游戏秒 = 0 对应 1220-01-01 子时初刻
EPOCH = datetime.date(1220, 1, 1)

#: 时钟持久化文件名（游戏数据/时钟.json）
CLOCK_FILE = "时钟"

#: 默认速率：游戏秒 / 真实秒（1 真实分钟 = 1 刻 = 900 游戏秒）
DEFAULT_RATE = 15.0
#: 战斗：1 回合 = 1 游戏分钟
DEFAULT_BATTLE_SECONDS_PER_ROUND = 60


# ------------------------------------------------------------
# 纯函数换算（无状态，便于测试）
# ------------------------------------------------------------
def _parse_date(s):
    """'1220-01-15' -> datetime.date，失败返回 None。"""
    try:
        y, m, d = (int(x) for x in str(s).split("-"))
        return datetime.date(y, m, d)
    except (ValueError, TypeError):
        return None


def seconds_from_civil(date_s, shichen, ke):
    """(日期, 时辰, 刻) -> 游戏秒；任一非法返回 None。"""
    d = _parse_date(date_s)
    if d is None or shichen not in SHICHEN:
        return None
    if not isinstance(ke, int) or isinstance(ke, bool) or not (0 <= ke < KE_PER_SHICHEN):
        ke = 0
    days = (d - EPOCH).days
    return (days * SECONDS_PER_DAY
            + SHICHEN.index(shichen) * SECONDS_PER_SHICHEN
            + ke * SECONDS_PER_KE)


def civil_from_seconds(total):
    """游戏秒 -> {'日期', '时辰', '刻'}。"""
    total = int(total)
    days, rem = divmod(total, SECONDS_PER_DAY)
    d = EPOCH + datetime.timedelta(days=days)
    sh, rem2 = divmod(rem, SECONDS_PER_SHICHEN)
    return {
        "日期": d.strftime("%Y-%m-%d"),
        "时辰": SHICHEN[sh],
        "刻": int(rem2 // SECONDS_PER_KE),
    }


def render_civil(c):
    """{'日期','时辰','刻'} -> '1220-01-16 辰时一刻'（刻级，**给 LLM 用**）。"""
    ke = c.get("刻", 0)
    ke_txt = ""
    if isinstance(ke, int) and ke > 0:
        ke_txt = KE_CN.get(ke, str(ke)) + "刻"
    return f"{c.get('日期', '')} {c.get('时辰', '')}{ke_txt}".strip()


# ------------------------------------------------------------
# 年号 / 干支 / 中文月日（南宋全表）—— **年号的唯一真相源**
# 前端不再自备年号表，改从 `/clock` 锚点取；LLM 从 基本信息.时间.纪年 取。
# ------------------------------------------------------------
#: 南宋 年号表：(起始年, 结束年, 年号)  —— 1127 建炎南渡 ~ 1279 崖山
#: （1276 年 德祐/景炎 重叠，按顺序取先匹配者 = 德祐）
ERAS = [
    (1127, 1130, "建炎"),
    (1131, 1162, "绍兴"),
    (1163, 1164, "隆兴"),
    (1165, 1173, "乾道"),
    (1174, 1189, "淳熙"),
    (1190, 1194, "绍熙"),
    (1195, 1200, "庆元"),
    (1201, 1204, "嘉泰"),
    (1205, 1207, "开禧"),
    (1208, 1224, "嘉定"),
    (1225, 1227, "宝庆"),
    (1228, 1233, "绍定"),
    (1234, 1236, "端平"),
    (1237, 1240, "嘉熙"),
    (1241, 1252, "淳祐"),
    (1253, 1258, "宝祐"),
    (1259, 1259, "开庆"),
    (1260, 1264, "景定"),
    (1265, 1274, "咸淳"),
    (1275, 1276, "德祐"),
    (1276, 1278, "景炎"),
    (1278, 1279, "祥兴"),
]

_CN_DIGITS = "零一二三四五六七八九"
_CN_MONTHS = ["正月", "二月", "三月", "四月", "五月", "六月",
              "七月", "八月", "九月", "十月", "冬月", "腊月"]
_CN_STEMS = "甲乙丙丁戊己庚辛壬癸"
_CN_BRANCHES = "子丑寅卯辰巳午未申酉戌亥"


def cn_number(n: int) -> str:
    """1..9999 -> 中文数字（口语习惯：13=十三、20=二十、32=三十二）。"""
    if n <= 0:
        return "零"
    s = str(n)
    units = ["", "十", "百", "千"]
    out = ""
    L = len(s)
    for i, ch in enumerate(s):
        d = int(ch)
        pos = L - 1 - i
        if d == 0:
            if out and not out.endswith("零"):
                out += "零"
        else:
            if not (d == 1 and pos == 1):   # 十 / 十几：不写「一十」
                out += _CN_DIGITS[d]
            if pos < len(units):
                out += units[pos]
    return out.rstrip("零") or "零"


def cn_day(d: int) -> str:
    """1..31 -> 初一…初十 / 十一…二十 / 廿一…三十 / 三十一。"""
    if d <= 10:
        return "初" + ("十" if d == 10 else _CN_DIGITS[d])
    if d < 20:
        return "十" + _CN_DIGITS[d - 10]
    if d == 20:
        return "二十"
    if d < 30:
        return "廿" + _CN_DIGITS[d - 20]
    if d == 30:
        return "三十"
    return "三十" + _CN_DIGITS[d - 30]   # 31（公历月）


def era_name(year: int) -> str:
    """年号纪年：1220 -> '嘉定十三年'；超出南宋范围退回 '公元1220年'。

    重叠年（如 1276 属 德祐/景炎）取**起始年最新**的年号（新纪元取代旧纪元），
    使每个年号都能出现「元年」。
    """
    best = None   # (起始年, 年号)
    for start, end, name in ERAS:
        if start <= year <= end and (best is None or start > best[0]):
            best = (start, name)
    if best is None:
        return f"公元{year}年"
    n = year - best[0] + 1
    return f"{best[1]}{'元' if n == 1 else cn_number(n)}年"


def ganzhi_year(year: int) -> str:
    """干支纪年：1220 -> '庚辰'。"""
    i = ((year - 4) % 60 + 60) % 60
    return _CN_STEMS[i % 10] + _CN_BRANCHES[i % 12]


def _year_of(c: dict) -> int:
    d = _parse_date(c.get("日期"))
    return d.year if d else 0


def chinese_date(c: dict) -> str:
    """{'日期':'1220-01-16'} -> '嘉定十三年正月十六'。"""
    d = _parse_date(c.get("日期"))
    if d is None:
        return ""
    return f"{era_name(d.year)}{_CN_MONTHS[d.month - 1]}{cn_day(d.day)}"


def render_era(c: dict) -> str:
    """{'日期','时辰','刻'} -> '嘉定十三年正月十六 辰时一刻'（给 LLM / 前情）。"""
    ke = c.get("刻", 0)
    ke_txt = KE_CN.get(ke, str(ke)) + "刻" if isinstance(ke, int) and ke > 0 else ""
    return f"{chinese_date(c)} {c.get('时辰', '')}{ke_txt}".strip()


# ------------------------------------------------------------
# 时钟
# ------------------------------------------------------------
class GameClock:
    """连续游戏时钟。线程安全；惰性求值；单一标量 + 暂停原因集合。"""

    def __init__(self):
        self._lock = threading.RLock()
        self._enabled = os.environ.get("TRPG_CLOCK", "1") != "0"
        self._rate = self._env_float("TRPG_CLOCK_RATE", DEFAULT_RATE)
        if self._rate <= 0:
            self._rate = DEFAULT_RATE
        self._battle_per_round = int(
            self._env_float("TRPG_CLOCK_BATTLE_ROUND", DEFAULT_BATTLE_SECONDS_PER_ROUND)
        )
        self._base = 0            # 锚点游戏秒（冻结值）
        self._base_wall = _time.time()
        self._reasons: set = set()  # 暂停原因（非空 => paused）
        self._accruing = False      # 战斗折算中
        self._last_sync = None      # 上次写回 基本信息 的 (日期,时辰,刻)
        self._last_persist = 0.0    # 上次落盘墙钟（节流用）
        self._seen_day = None       # 跨日检测游标（全局第几天）
        self._seen_shichen = None   # 跨时辰检测游标（全局第几时辰）
        self._load()

    @staticmethod
    def _env_float(name, default):
        try:
            return float(os.environ.get(name, default))
        except (TypeError, ValueError):
            return float(default)

    # ---- 持久化 / 加载 ----
    def _load(self):
        self._last_sync = None
        self._seen_day = None       # 重启 / 回滚后重新对齐（不补结算）
        self._seen_shichen = None
        data = state.load(CLOCK_FILE, None)
        if isinstance(data, dict) and data.get("游戏秒") is not None:
            try:
                self._base = int(data["游戏秒"])
            except (TypeError, ValueError):
                self._base = 0
            self._base_wall = _time.time()
            return
        # 迁移：从 基本信息.时间 初始化（首次引入时钟时）
        t = (state.load("基本信息", {}) or {}).get("时间", {}) or {}
        s = seconds_from_civil(t.get("日期"), t.get("时辰"), t.get("刻", 0))
        self._base = int(s) if s is not None else 0
        self._base_wall = _time.time()
        self._persist_locked()

    def _persist_locked(self):
        state.save(CLOCK_FILE, {"游戏秒": int(self._base), "状态": self.state_name()})
        self._last_persist = _time.time()

    def maybe_persist(self, interval: float = 30.0) -> bool:
        """惰性落盘：探索中可能长时间不触发暂停/推进，距上次落盘超过 interval 秒才写。

        避免服务重启后时间倒回太久。文件被占用等瞬时错误**不抛**（下次再试）。
        """
        with self._lock:
            if _time.time() - self._last_persist < interval:
                return False
            self._materialize_locked()
            try:
                self._persist_locked()
                self._sync_locked()
            except OSError as e:
                print(f"[clock] 落盘失败，稍后重试：{e}")
                return False
            return True

    def persist(self):
        """立即冻结当前值并落盘（快照前调用，保证快照里的时钟是最新的）。"""
        with self._lock:
            self._materialize_locked()
            self._persist_locked()
            self._sync_locked()

    def reload(self):
        """从 游戏数据/时钟.json 重新载入（放弃本轮回滚后调用）。"""
        with self._lock:
            self._load()

    # ---- 状态机 ----
    def state_name(self) -> str:
        if not self._enabled:
            return "disabled"
        if self._accruing:
            return "accruing"
        if self._reasons:
            return "paused"
        return "running"

    def _now_locked(self) -> int:
        if self.state_name() == "running":
            elapsed = _time.time() - self._base_wall
            return int(self._base + elapsed * self._rate)
        return int(self._base)

    def _materialize_locked(self):
        """把当前计算值冻结进锚点（任何状态切换前调用）。"""
        self._base = self._now_locked()
        self._base_wall = _time.time()

    # ---- 读取 ----
    def seconds(self) -> int:
        with self._lock:
            return self._now_locked()

    def civil(self) -> dict:
        return civil_from_seconds(self.seconds())

    def render(self) -> str:
        """刻级可读串（给 LLM / 日志）。"""
        return render_civil(self.civil())

    def day_index(self) -> int:
        """自纪元起的第几天（跨日检测用）。"""
        return self.seconds() // SECONDS_PER_DAY

    def take_crossings(self, cap: int = 96) -> dict:
        """自上次调用以来**跨过的「时辰 / 日」**——供 `time_flow` 落实数值与联动。

        - 返回 `{days, shichen, shichen_indices, date}`；
        - 首次调用只**对齐游标**、不结算（重启/回滚后不会凭空扣一波）；
        - 时间被设回过去 → 重新对齐、不结算；
        - `shichen_indices` 上限 `cap`（大跨度只结算最近 cap 个时辰）。
        """
        with self._lock:
            now = self._now_locked()
            day = now // SECONDS_PER_DAY
            sh = now // SECONDS_PER_SHICHEN
            date = civil_from_seconds(now)["日期"]
            if self._seen_day is None:
                self._seen_day, self._seen_shichen = day, sh
                return {"days": 0, "shichen": 0, "shichen_indices": [], "date": date}
            days = day - self._seen_day
            n_sh = sh - self._seen_shichen
            indices = []
            if n_sh > 0:
                lo = self._seen_shichen + 1
                if n_sh > cap:
                    lo = sh - cap + 1
                indices = list(range(lo, sh + 1))
            if days < 0 or n_sh < 0:      # 时间被设回过去：对齐，不结算
                days, indices = 0, []
            self._seen_day, self._seen_shichen = day, sh
            return {"days": days, "shichen": len(indices),
                    "shichen_indices": indices, "date": date}

    def anchor(self) -> dict:
        """给前端的锚点：前端据此本地插值，**不必每帧轮询后端**。"""
        with self._lock:
            now = self._now_locked()
            c = civil_from_seconds(now)
            return {
                "游戏秒": now,
                "服务端墙钟": _time.time(),   # 本地单机：前后端同一台机器，无需校时
                "状态": self.state_name(),
                "倍率": self._rate,
                "显示": render_civil(c),
                # 年号 / 干支 由**后端**统一裁决（前端不再自备年号表）
                "纪年": chinese_date(c),
                "干支": ganzhi_year(_year_of(c)) + "年",
            }

    # ---- 推进 / 设置 ----
    def advance(self, game_seconds) -> dict:
        """推进若干游戏秒，返回新 civil。"""
        with self._lock:
            self._materialize_locked()
            self._base += int(game_seconds)
            self._persist_locked()
            self._sync_locked()
            return civil_from_seconds(self._base)

    def set_civil(self, date=None, shichen=None, ke=None):
        """直接设置 日期 / 时辰 / 刻（LLM 的 update_time 设置语义）。非法返回 None。"""
        with self._lock:
            cur = civil_from_seconds(self._now_locked())
            if date is not None:
                d = _parse_date(date)
                if d is None:
                    return None
                cur["日期"] = d.strftime("%Y-%m-%d")
            if shichen is not None:
                if shichen not in SHICHEN:
                    return None
                cur["时辰"] = shichen
            if ke is not None:
                if not isinstance(ke, int) or isinstance(ke, bool) or not (0 <= ke < KE_PER_SHICHEN):
                    return None
                cur["刻"] = ke
            s = seconds_from_civil(cur["日期"], cur["时辰"], cur["刻"])
            if s is None:
                return None
            self._base = int(s)
            self._base_wall = _time.time()
            self._persist_locked()
            self._sync_locked()
            return dict(cur)

    # ---- 暂停 / 恢复（多原因，互不干扰）----
    def pause(self, reason: str = "manual") -> str:
        with self._lock:
            if reason not in self._reasons:
                self._materialize_locked()
                self._reasons.add(reason)
                self._persist_locked()
                self._sync_locked()   # 冻结时同步投影，避免 基本信息.时间 停在旧值
            return self.state_name()

    def resume(self, reason: str = "manual") -> str:
        with self._lock:
            self._reasons.discard(reason)
            self._base_wall = _time.time()  # 从恢复这一刻继续走
            self._persist_locked()
            return self.state_name()

    # ---- 战斗：按回合折算 ----
    def begin_battle(self) -> str:
        with self._lock:
            if not self._accruing:
                self._materialize_locked()
                self._accruing = True
                self._persist_locked()
            return self.state_name()

    def end_battle(self, rounds: int) -> dict:
        """战斗结束：时钟 += 回合数 × 每回合游戏秒（跨时辰/跨日自动重算）。"""
        with self._lock:
            self._materialize_locked()
            self._base += int(rounds) * self._battle_per_round
            self._accruing = False
            self._persist_locked()
            self._sync_locked()
            return civil_from_seconds(self._base)

    # ---- 投影：写回 基本信息.json 的「时间」----
    def sync_state(self) -> bool:
        with self._lock:
            return self._sync_locked()

    def _sync_locked(self) -> bool:
        """把派生时刻写回 基本信息.时间（**仅在内容变化时落盘**）。

        含 `纪年`（年号 + 中文月日）与 `干支`——**给 LLM 看的**，落实总纲第 5 条：
        年号是硬事实，由代码裁决，不让模型自己猜（否则它会说错朝代纪年）。
        """
        c = civil_from_seconds(self._now_locked())
        target = {
            "日期": c["日期"],
            "时辰": c["时辰"],
            "刻": c["刻"],
            "纪年": chinese_date(c),
            "干支": ganzhi_year(_year_of(c)) + "年",
        }
        key = (target["日期"], target["时辰"], target["刻"], target["纪年"])
        if key == self._last_sync:
            return False
        data = state.load("基本信息", {}) or {}
        t = data.setdefault("时间", {})
        if any(t.get(k) != v for k, v in target.items()):
            t.update(target)
            try:
                state.save("基本信息", data)
            except OSError as e:      # 文件被占用：不更新 _last_sync，下次再试
                print(f"[clock] 写回 基本信息.时间 失败，稍后重试：{e}")
                return False
        self._last_sync = key
        return True


#: 全局单例
clock = GameClock()
