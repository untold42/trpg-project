// useGameClock.ts
// ==============
// 连续游戏时钟的前端接入（见 README.md 第六 / 十节）。
//
// 设计：
//   - 只向 `GET /clock` **拿一次锚点**（+ 每 60s 兜底重同步），其余时间**本地插值**：
//     现在 = 游戏秒 + (本地墙钟 − 服务端墙钟) × 倍率
//   - `running` 时插值前进；其余状态（paused / accruing / disabled）冻结在锚点值
//   - **不每帧 setState**：rAF 每帧把秒数回调给组件，组件直接改 DOM（SVG transform）；
//     文字（时辰/刻/日期）只在「刻」变化时更新
//   - 暂停 / 恢复走后端（多原因，安全）；窗口失焦亦可暂停
//
// 时间域常量与后端 `tools/game_clock.py` **严格对齐**。

import { useCallback, useEffect, useRef, useState } from "react";

const API = "http://localhost:5000";

export type ClockState = "running" | "paused" | "accruing" | "disabled";

export type ClockAnchor = {
    游戏秒: number;
    服务端墙钟: number;
    状态: ClockState;
    倍率: number;
    显示: string;
    /** 年号纪年 + 中文月日，如「嘉定十三年正月十六」——由**后端**裁决 */
    纪年?: string;
    /** 干支纪年，如「庚辰年」——由**后端**裁决 */
    干支?: string;
};

// ---- 时间域常量（与后端对齐）----
export const SECONDS_PER_KE = 900;            // 1 刻 = 15 游戏分钟
export const SECONDS_PER_SHICHEN = 7200;      // 1 时辰 = 8 刻
export const SECONDS_PER_DAY = 86400;         // 1 天 = 12 时辰

export const SHICHEN = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"];
const NUM = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九"];

/** 只保留画钟所需的「时辰 / 刻」——**日期与年号由后端裁决**，前端不再自算。 */
export type Civil = {
    时辰索引: number;
    时辰: string;
    刻: number;
    刻浮点: number;   // 0..8（本时辰内，含小数）——供平滑指针
};

// ------------------------------------------------------------
// 换算（纯函数）
// ------------------------------------------------------------
export function civilFromSeconds(s: number): Civil {
    const total = Math.floor(s);
    const rem = ((total % SECONDS_PER_DAY) + SECONDS_PER_DAY) % SECONDS_PER_DAY;
    const sh = Math.floor(rem / SECONDS_PER_SHICHEN);
    const inShichen = rem - sh * SECONDS_PER_SHICHEN;
    return {
        时辰索引: sh,
        时辰: SHICHEN[sh],
        刻: Math.floor(inShichen / SECONDS_PER_KE),
        刻浮点: inShichen / SECONDS_PER_KE,
    };
}

export function formatShichenKe(c: Civil): string {
    return c.刻 > 0 ? `${c.时辰}时·${NUM[c.刻]}刻` : `${c.时辰}时`;
}

/** 全天 0..1 的进度（子时初刻 = 0），供指针角度 / 昼夜弧 */
export function dayFraction(s: number): number {
    return ((s % SECONDS_PER_DAY) + SECONDS_PER_DAY) % SECONDS_PER_DAY / SECONDS_PER_DAY;
}

export function gameSeconds(anchor: ClockAnchor, wallMs = Date.now()): number {
    if (anchor.状态 === "running") {
        return anchor.游戏秒 + (wallMs / 1000 - anchor.服务端墙钟) * anchor.倍率;
    }
    return anchor.游戏秒;
}

// ------------------------------------------------------------
// 网络
// ------------------------------------------------------------
export async function fetchClock(): Promise<ClockAnchor | null> {
    try {
        const res = await fetch(`${API}/clock`);
        if (!res.ok) return null;
        return await res.json();
    } catch {
        return null;
    }
}

async function postClock(path: string): Promise<ClockAnchor | null> {
    try {
        const res = await fetch(`${API}${path}`, { method: "POST" });
        if (!res.ok) return null;
        return await res.json();
    } catch {
        return null;
    }
}

// ---- 全局重同步（如：每次 /action 之后，把「请求窗口暂停」造成的偏移纠回来）----
const _syncListeners = new Set<() => void>();
export function requestClockSync() {
    for (const l of _syncListeners) l();
}

// ------------------------------------------------------------
// Hook
// ------------------------------------------------------------
/**
 * @param onFrame 每帧回调（拿到平滑的游戏秒 + 派生 civil）。**不触发 React 重渲染**。
 * @returns anchor（低频，用于文字/状态）、sync、pause、resume
 */
export function useGameClock(onFrame?: (seconds: number, civil: Civil) => void) {
    const anchorRef = useRef<ClockAnchor | null>(null);
    const cbRef = useRef(onFrame);
    cbRef.current = onFrame;
    const [anchor, setAnchor] = useState<ClockAnchor | null>(null);

    const apply = useCallback((a: ClockAnchor | null) => {
        if (!a) return null;
        anchorRef.current = a;
        setAnchor(a);
        return a;
    }, []);

    const sync = useCallback(async () => apply(await fetchClock()), [apply]);
    const pause = useCallback(async () => apply(await postClock("/clock/pause")), [apply]);
    const resume = useCallback(async () => apply(await postClock("/clock/resume")), [apply]);

    // 每帧插值（不 setState）
    useEffect(() => {
        let raf = 0;
        const loop = () => {
            const a = anchorRef.current;
            if (a) {
                const sec = gameSeconds(a);
                cbRef.current?.(sec, civilFromSeconds(sec));
            }
            raf = requestAnimationFrame(loop);
        };
        raf = requestAnimationFrame(loop);
        return () => cancelAnimationFrame(raf);
    }, []);

    // 首次拉取 + 60s 兜底重同步 + 全局重同步
    useEffect(() => {
        sync();
        const iv = window.setInterval(sync, 60000);
        _syncListeners.add(sync);
        return () => {
            window.clearInterval(iv);
            _syncListeners.delete(sync);
        };
    }, [sync]);

    return { anchor, sync, pause, resume };
}

// ------------------------------------------------------------
// 昼夜（供地图图标切换 <键>/day.png 与 <键>/night.png）
//   判据：卯 ~ 酉（时辰索引 3..9）为昼，戌 ~ 寅（10,11,0,1,2）为夜。
//   昼夜切换以「时辰」计，故 60s 轮询一次锚点足够（与 useGameClock 同一节奏）。
// ------------------------------------------------------------
export function isNightFromSeconds(s: number): boolean {
    const sh = civilFromSeconds(s).时辰索引;   // 0 = 子
    return sh >= 10 || sh <= 2;
}

export function useIsNight(): boolean {
    const [isNight, setIsNight] = useState(false);
    useEffect(() => {
        let alive = true;
        const tick = () => {
            fetchClock()
                .then((a) => { if (alive && a) setIsNight(isNightFromSeconds(a.游戏秒)); })
                .catch(() => { /* 后端没起来 → 保持日间 */ });
        };
        tick();
        const iv = window.setInterval(tick, 60000);
        return () => { alive = false; window.clearInterval(iv); };
    }, []);
    return isNight;
}

/** 当前游戏时间：昼夜 + 时辰索引（供地图图标：夜色发光 + 打烊判断） */
export type WorldTime = { isNight: boolean; shichen: number };

export function useWorldTime(): WorldTime {
    const [t, setT] = useState<WorldTime>({ isNight: false, shichen: -1 });
    useEffect(() => {
        let alive = true;
        const tick = () => {
            fetchClock()
                .then((a) => {
                    if (!alive || !a) return;
                    setT({
                        isNight: isNightFromSeconds(a.游戏秒),
                        shichen: civilFromSeconds(a.游戏秒).时辰索引,
                    });
                })
                .catch(() => { /* 后端没起来 → 保持日间 */ });
        };
        tick();
        const iv = window.setInterval(tick, 60000);
        return () => { alive = false; window.clearInterval(iv); };
    }, []);
    return t;
}
