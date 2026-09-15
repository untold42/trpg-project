// Clock.tsx
// =========
// 左上角「古代会动的钟」HUD（见 README.md 第十节）。
//
// 结构：十二时辰环 + 平滑指针 + 96 刻刻度 + 昼夜日月弧 + 日期。
// 性能：指针 / 日月由 rAF **直接改 DOM**（SVG transform / cx cy），不每帧 setState；
//       文字（时辰·刻 / 日期）只在「刻」变化时更新。
//
// 暂停原因（交给后端多原因集合，互不干扰）：
//   - 外部 `paused`（如历史记录面板打开）
//   - 窗口失焦 / 页面隐藏

import { useCallback, useEffect, useRef, useState } from "react";
import "../styles/Clock.css";
import {
    useGameClock, dayFraction, formatShichenKe,
    SHICHEN, type Civil,
} from "./useGameClock";

type Props = {
    /** 外部暂停（如历史记录 / 菜单打开时） */
    paused?: boolean;
};

// ---- 几何常量（viewBox 200×200，圆心 100,100）----
const C = 100;
const R_SHICHEN = 79;   // 十二时辰文字半径
const R_TICK_OUT = 73;  // 刻刻度外径
const R_TICK_MIN = 69;  // 刻刻度内径（小刻）
const R_TICK_MAJ = 66;  // 刻刻度内径（时辰分界）
const R_ARC = 56;       // 昼夜弧半径
const R_HAND = 50;      // 指针长度

/** 极坐标 → 直角（0° = 正上，顺时针） */
function polar(r: number, deg: number) {
    const rad = (deg * Math.PI) / 180;
    return { x: C + r * Math.sin(rad), y: C - r * Math.cos(rad) };
}

export default function Clock({ paused = false }: Props) {
    const handRef = useRef<SVGGElement>(null);
    const sunRef = useRef<SVGCircleElement>(null);
    const moonRef = useRef<SVGCircleElement>(null);
    const lastKeyRef = useRef("");
    const [civil, setCivil] = useState<Civil | null>(null);

    const { anchor, pause, resume } = useGameClock((sec, c) => {
        const frac = dayFraction(sec);

        // 指针：全天 = 360°
        if (handRef.current) {
            handRef.current.setAttribute("transform", `rotate(${frac * 360} ${C} ${C})`);
        }

        // 日月：昼（卯→酉，frac 0.25~0.75）走上半弧，夜走下半弧
        const isDay = frac >= 0.25 && frac <= 0.75;
        if (sunRef.current) {
            if (isDay) {
                const ang = Math.PI * (1 + (frac - 0.25) / 0.5);
                sunRef.current.setAttribute("cx", String(C + R_ARC * Math.cos(ang)));
                sunRef.current.setAttribute("cy", String(C + R_ARC * Math.sin(ang)));
            }
            sunRef.current.style.opacity = isDay ? "1" : "0";
        }
        if (moonRef.current) {
            if (!isDay) {
                const q = frac >= 0.75 ? (frac - 0.75) / 0.5 : (frac + 0.25) / 0.5;
                const ang = Math.PI * q;
                moonRef.current.setAttribute("cx", String(C + R_ARC * Math.cos(ang)));
                moonRef.current.setAttribute("cy", String(C + R_ARC * Math.sin(ang)));
            }
            moonRef.current.style.opacity = isDay ? "0" : "1";
        }

        // 文字：只在「时辰/刻」变化时更新（低频）。日期与年号走 anchor，不在此处。
        const key = `${c.时辰索引}-${c.刻}`;
        if (key !== lastKeyRef.current) {
            lastKeyRef.current = key;
            setCivil(c);
        }
    });

    // ---- 暂停原因（本地归并，只在与后端切换时发一次请求）----
    const reasonsRef = useRef<Set<string>>(new Set());
    const setPaused = useCallback((reason: string, on: boolean) => {
        const had = reasonsRef.current.size > 0;
        if (on) reasonsRef.current.add(reason);
        else reasonsRef.current.delete(reason);
        const has = reasonsRef.current.size > 0;
        if (has && !had) pause();
        else if (!has && had) resume();
    }, [pause, resume]);

    useEffect(() => { setPaused("ui", paused); }, [paused, setPaused]);

    useEffect(() => {
        const onBlur = () => setPaused("blur", true);
        const onFocus = () => setPaused("blur", false);
        const onVis = () => setPaused("blur", document.hidden);
        window.addEventListener("blur", onBlur);
        window.addEventListener("focus", onFocus);
        document.addEventListener("visibilitychange", onVis);
        return () => {
            window.removeEventListener("blur", onBlur);
            window.removeEventListener("focus", onFocus);
            document.removeEventListener("visibilitychange", onVis);
        };
    }, [setPaused]);

    // 卸载时清掉本组件的暂停原因，避免时钟卡在 paused
    useEffect(() => () => {
        reasonsRef.current.clear();
        resume();
    }, [resume]);

    // 后端关闭时钟（disabled）时不显示
    if (anchor?.状态 === "disabled") return null;

    const curShichen = civil?.时辰索引 ?? -1;
    const statusText = anchor?.状态 === "paused" ? "时光凝滞"
        : anchor?.状态 === "accruing" ? "战中" : "";

    return (
        <div className={`game-clock status-${anchor?.状态 ?? "loading"}`}>
            <svg viewBox="0 0 200 200" className="clock-svg" role="img" aria-label="游戏内时辰">
                <defs>
                    <radialGradient id="clockPlate" cx="50%" cy="42%" r="70%">
                        <stop offset="0%" stopColor="#2b1d12" stopOpacity="0.92" />
                        <stop offset="70%" stopColor="#1a1009" stopOpacity="0.9" />
                        <stop offset="100%" stopColor="#0d0704" stopOpacity="0.94" />
                    </radialGradient>
                    <linearGradient id="clockGold" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#f4e2a8" />
                        <stop offset="50%" stopColor="#d8b45a" />
                        <stop offset="100%" stopColor="#a9822f" />
                    </linearGradient>
                </defs>

                {/* 盘面 */}
                <circle cx={C} cy={C} r="94" className="clock-plate" />
                <circle cx={C} cy={C} r="94" className="clock-rim" />
                <circle cx={C} cy={C} r="86" className="clock-rim-inner" />

                {/* 96 刻刻度（每 8 刻 = 时辰分界，加长加粗）*/}
                <g className="clock-ticks">
                    {Array.from({ length: 96 }, (_, i) => {
                        const deg = i * 3.75;
                        const major = i % 8 === 0;
                        const p1 = polar(major ? R_TICK_MAJ : R_TICK_MIN, deg);
                        const p2 = polar(R_TICK_OUT, deg);
                        return (
                            <line
                                key={i}
                                x1={p1.x} y1={p1.y} x2={p2.x} y2={p2.y}
                                className={major ? "tick tick-major" : "tick"}
                            />
                        );
                    })}
                </g>

                {/* 十二时辰 */}
                <g className="clock-shichen">
                    {SHICHEN.map((ch, i) => {
                        const p = polar(R_SHICHEN, i * 30);
                        return (
                            <text
                                key={ch}
                                x={p.x} y={p.y}
                                textAnchor="middle"
                                dominantBaseline="central"
                                className={i === curShichen ? "shichen cur" : "shichen"}
                            >
                                {ch}
                            </text>
                        );
                    })}
                </g>

                {/* 昼夜弧 + 日月 */}
                <path d={`M ${C - R_ARC} ${C} A ${R_ARC} ${R_ARC} 0 0 1 ${C + R_ARC} ${C}`} className="arc arc-day" />
                <path d={`M ${C - R_ARC} ${C} A ${R_ARC} ${R_ARC} 0 0 0 ${C + R_ARC} ${C}`} className="arc arc-night" />
                <circle ref={sunRef} cx={C} cy={C - R_ARC} r="4.6" className="celestial sun" />
                <circle ref={moonRef} cx={C} cy={C + R_ARC} r="4.2" className="celestial moon" />

                {/* 指针 */}
                <g ref={handRef} className="clock-hand">
                    <line x1={C} y1={C} x2={C} y2={C - R_HAND} className="hand" />
                    <circle cx={C} cy={C - R_HAND} r="3.2" className="hand-tip" />
                </g>

                {/* 中心 + 当前时辰字 */}
                <circle cx={C} cy={C} r="15" className="clock-hub" />
                <text x={C} y={C} textAnchor="middle" dominantBaseline="central" className="hub-char">
                    {civil?.时辰 ?? ""}
                </text>
            </svg>

            <div className="clock-caption">
                <div className="clock-ke">{civil ? formatShichenKe(civil) : "——"}</div>
                <div className="clock-date">
                    {anchor?.纪年 ? `${anchor.纪年}${anchor.干支 ? ` · ${anchor.干支}` : ""}` : ""}
                </div>
                {statusText && <div className="clock-status">{statusText}</div>}
            </div>
        </div>
    );
}
