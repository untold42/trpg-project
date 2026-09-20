import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Galaxy from "./Galaxy";
import { API } from "../api";
import { useEsc } from "../escStack";
import "../styles/SkillTree.css";

/* =========================================================================
 * 技能树（前端，零大模型）
 * 第一幕：银河 + 五神圆弧（一条左下→右下的穹顶弧，五等分，顶边+弧围成 5 片区域）
 * 第二幕：点神 → 淡入该行技能树（白链条 + 节点）
 * 数据：GET /skilltree；点亮：POST /skilltree/learn
 * ========================================================================= */

/** 星空参数（想调银河就改这里；改完刷新） */
const GALAXY = {
    hueShift: 0,
    density: 2.5,
    starSpeed: 0.1,
    speed: 0.1,
    glowIntensity: 0.2,
    saturation: 0,
    twinkleIntensity: 0.3,
    rotationSpeed: 0,
};

/** 圆弧「拱顶」高度（占屏高比例）：越大弧越平、神像区越高 */
const APEX_RATIO = 0.78;

/** 五神 2D 左右倾：每往外一尊多倾多少度（后土 = 0，最外侧 = ±2× 即 ±TILT_STEP×2） */
const TILT_STEP = 3;

/** 神名水平外移：非中间神（后土）的名字远离画面中心，每档多少像素 */
const NAME_OUT = 50;

/** 技能树舞台：固定 16:9（对齐游戏 1920×1080），随画布缩放 */
const STAGE = { w: 1920, h: 1080 };

type SkillNode = {
    名称: string; 五行: string; 花费: number;
    前置: string[]; 要求: Record<string, number>;
    状态: "已学" | "可学" | "锁定"; 原因: string;
    内力: number; 射程: number; 范围: string; 威力: number; 连击: number;
    效果: string[]; 描述: string;
};
type SkillView = {
    success: boolean; 技能点: number;
    五行熟练度: Record<string, number>;
    基础属性: Record<string, number>;
    节点: SkillNode[];
};

/** 五神（按相生序：木→火→土→金→水，从左上到右下铺开）；`上移` = 该神像额外抬高（像素，可选） */
type God = { 行: string; 神: string; 色: string; 悬停色?: string; 上移?: number };
const GODS: God[] = [
    { 行: "木", 神: "句芒", 色: "#6fbf7a" },
    { 行: "火", 神: "祝融", 色: "#ff4d1a", 上移: 40 },
    { 行: "土", 神: "后土", 色: "#c19a5b" },
    { 行: "金", 神: "蓐收", 色: "#e6d18a", 悬停色: "#ffd83b", 上移: 40 },
    { 行: "水", 神: "玄冥", 色: "#5aa0e0" },
];

/** 神像：`src/assets/神明/<行>.png`（3:9 竖版）。缺图则占位。 */
const GOD_IMAGES = import.meta.glob("../assets/神明/*.png", {
    eager: true, query: "?url", import: "default",
}) as Record<string, string>;
function godImg(行: string) {
    return GOD_IMAGES[`../assets/神明/${行}.png`];
}

/* ---------------- 圆弧几何（屏幕像素坐标，y 向下） ---------------- */
type ArcGeo = { cx: number; cy: number; R: number; aL: number; aR: number };

function arcGeometry(W: number, H: number): ArcGeo {
    const cx = W / 2;
    const apexY = H * APEX_RATIO;
    // 圆心在下方；圆过两底角 (0,H)/(W,H)，拱顶 (W/2, apexY)
    // 2k(H-apexY) = W²/4 + H² - apexY²
    const cy = (W * W / 4 + H * H - apexY * apexY) / (2 * (H - apexY));
    const R = cy - apexY;
    return { cx, cy, R, aL: Math.atan2(H - cy, 0 - cx), aR: Math.atan2(H - cy, W - cx) };
}
function arcPoint(g: ArcGeo, a: number): [number, number] {
    return [g.cx + g.R * Math.cos(a), g.cy + g.R * Math.sin(a)];
}
function panelPath(g: ArcGeo, a0: number, a1: number): string {
    const [x0, y0] = arcPoint(g, a0);
    const [x1, y1] = arcPoint(g, a1);
    const sweep = 1;   // 角度递增 = 顺时针（SVG y 向下）
    return `M ${x0} ${y0} A ${g.R} ${g.R} 0 0 ${sweep} ${x1} ${y1} L ${x1} 0 L ${x0} 0 Z`;
}

/* ---------------- 技能树布局（按前置层级） ---------------- */
function useLayout(nodes: SkillNode[]) {
    return useMemo(() => {
        const byName = new Map(nodes.map((n) => [n.名称, n] as const));
        const depth = new Map<string, number>();
        const calc = (n: SkillNode): number => {
            const c = depth.get(n.名称);
            if (c !== undefined) return c;
            let d = 0;
            for (const p of n.前置) {
                const pn = byName.get(p);
                if (pn) d = Math.max(d, calc(pn) + 1);
            }
            depth.set(n.名称, d);
            return d;
        };
        for (const n of nodes) calc(n);
        const levels = new Map<number, SkillNode[]>();
        for (const n of nodes) {
            const d = depth.get(n.名称) ?? 0;
            if (!levels.has(d)) levels.set(d, []);
            levels.get(d)!.push(n);
        }
        const pos = new Map<string, { x: number; y: number }>();
        const X0 = 600, Y0 = 84, DY = 168, DX = 300;
        for (const [d, list] of levels) {
            list.forEach((n, i) => {
                pos.set(n.名称, { x: X0 + (i - (list.length - 1) / 2) * DX, y: Y0 + d * DY });
            });
        }
        const edges: { from: string; to: string }[] = [];
        for (const n of nodes) for (const p of n.前置) if (byName.has(p)) edges.push({ from: p, to: n.名称 });
        return { pos, edges };
    }, [nodes]);
}

/* ---------------- 技能树视野（自动取景 + 滚轮滚动） ---------------- */
/** 节点外接框 + 边距 → viewBox。再深的链也不会被裁掉。 */
const PAD_X = 120, PAD_Y = 90;
function useFitView(pos: Map<string, { x: number; y: number }>) {
    return useMemo(() => {
        if (pos.size === 0) return { x: 0, y: 0, w: 1200, h: 820 };
        let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
        for (const p of pos.values()) {
            minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x);
            minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y);
        }
        return {
            x: minX - PAD_X, y: minY - PAD_Y,
            w: (maxX - minX) + PAD_X * 2, h: (maxY - minY) + PAD_Y * 2,
        };
    }, [pos]);
}

/** 缩放：放得下就放大到占满，放不下就用原尺寸（画布比视口大 → 外层滚轮滚动） */
function useTreeScale(fit: { w: number; h: number }, wrapRef: React.RefObject<HTMLDivElement | null>) {
    const [scale, setScale] = useState(1);
    useEffect(() => {
        const el = wrapRef.current;
        if (!el) return;
        const measure = () => {
            const w = el.clientWidth, h = el.clientHeight;
            if (!w || !h) return;
            setScale(Math.max(1, Math.min(w / fit.w, h / fit.h)));
        };
        measure();
        const ro = new ResizeObserver(measure);
        ro.observe(el);
        return () => ro.disconnect();
    }, [fit.w, fit.h, wrapRef]);
    return scale;
}

/* ======================================================================== */

export default function SkillTree({ onClose }: { onClose: () => void }) {
    const [view, setView] = useState<SkillView | null>(null);
    const [row, setRow] = useState<string | null>(null);   // null = 五神圆弧
    const [sel, setSel] = useState<SkillNode | null>(null);
    const [busy, setBusy] = useState(false);
    const [msg, setMsg] = useState("");

    const reload = useCallback(async () => {
        try {
            const d = await (await fetch(`${API}/skilltree`)).json();
            if (d?.success) setView(d as SkillView);
        } catch { /* 后端没起 */ }
    }, []);
    useEffect(() => { reload(); }, [reload]);

    // Esc：层级栈里自己这一层（详情卡 → 某一行 → 关闭）
    useEsc(() => {
        if (sel) { setSel(null); return; }
        if (row) { setRow(null); return; }
        onClose();
    });

    const rowNodes = useMemo(
        () => (view?.节点 ?? []).filter((n) => n.五行 === row),
        [view, row],
    );
    const { pos, edges } = useLayout(rowNodes);
    const fit = useFitView(pos);
    const treeWrapRef = useRef<HTMLDivElement>(null);
    const treeScale = useTreeScale(fit, treeWrapRef);
    const god = GODS.find((g) => g.行 === row) ?? null;
    const geo = useMemo(() => arcGeometry(STAGE.w, STAGE.h), []);

    async function doLearn(n: SkillNode) {
        if (busy || n.状态 !== "可学") return;
        setBusy(true); setMsg("");
        try {
            const res = await fetch(`${API}/skilltree/learn`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name: n.名称 }),
            });
            const d = await res.json();
            if (d?.success) {
                setMsg(`已点亮「${n.名称}」（余 ${d.剩余技能点} 点）`);
                await reload();
                setSel(null);
            } else {
                setMsg(d?.error || "点亮失败");
            }
        } catch {
            setMsg("点亮失败：后端没起？");
        } finally {
            setBusy(false);
        }
    }

    return (
        <div className="skilltree">
            <div className="st-frame">
            <Galaxy transparent mouseInteraction={false} mouseRepulsion={false} {...GALAXY} />
            {god && <div className="st-tint" style={{ background: god.色 }} />}

            <div className="st-top" onClick={(e) => e.stopPropagation()}>
                {row && <button className="st-back" onClick={() => { setRow(null); setSel(null); }}>◀ 五神</button>}
            </div>

            {!view && <div className="st-loading">…</div>}

            {/* ---- 第一幕：五神圆弧（左下 → 右下） ---- */}
            {view && !row && (
                <svg className="st-arc" viewBox={`0 0 ${STAGE.w} ${STAGE.h}`}
                    onClick={(e) => e.stopPropagation()}>
                    {GODS.map((g, i) => {
                        const span = (geo.aR - geo.aL) / 5;
                        const a0 = geo.aL + i * span;
                        const a1 = a0 + span;
                        const aMid = (a0 + a1) / 2;
                        const [mx, my] = arcPoint(geo, aMid);
                        // 2D 左右倾：中间神（后土）为 0°，每往外一尊多倾 TILT_STEP 度
                        const tilt = (i - 2) * TILT_STEP;
                        const lift = g.上移 ?? 0;   // 该神像额外抬高
                        // 神像尺寸/位置：尽量大，但「含倾斜的包围盒」不越出画布；相邻允许最多重叠 ~25%
                        const ART = 0.62;                                  // 图 宽:高
                        const rad = (tilt * Math.PI) / 180;
                        const ca = Math.abs(Math.cos(rad)), sa = Math.abs(Math.sin(rad));
                        let imgW = Math.min((STAGE.w / 5) * 0.93, STAGE.w - 40) / (ca + sa / ART);
                        let imgH = imgW / ART;
                        const maxH = my - 64;
                        if (imgH > maxH) { imgH = maxH; imgW = imgH * ART; }
                        // 旋转包围盒（相对轴心＝图底边中心）
                        let bbMinX = 1e9, bbMaxX = -1e9;
                        for (const [cx0, cy0] of [[-imgW / 2, -imgH], [imgW / 2, -imgH], [imgW / 2, 0], [-imgW / 2, 0]]) {
                            const rx0 = cx0 * Math.cos(rad) - cy0 * Math.sin(rad);
                            if (rx0 < bbMinX) bbMinX = rx0;
                            if (rx0 > bbMaxX) bbMaxX = rx0;
                        }
                        let px = mx;
                        if (px + bbMinX < 8) px = 8 - bbMinX;
                        if (px + bbMaxX > STAGE.w - 8) px = STAGE.w - 8 - bbMaxX;
                        const nameX = px + (i - 2) * NAME_OUT;   // 名字远离中心（后土 = 0）
                        const src = godImg(g.行);
                        return (
                            <g key={g.行} className="st-panel-hit" onClick={() => setRow(g.行)}
                                style={{ ["--god" as string]: g.色, ["--god-hover" as string]: (g.悬停色 ?? g.色) }}>
                                <path className="st-panel" d={panelPath(geo, a0, a1)}
                                    style={{ ["--god" as string]: g.色 }} />
                                {src ? (
                                    <image href={src} x={px - imgW / 2} y={my - imgH - 6 - lift}
                                        width={imgW} height={imgH} preserveAspectRatio="xMidYMid meet"
                                        transform={`rotate(${tilt} ${px} ${my - 6 - lift})`}
                                        pointerEvents="none" />
                                ) : (
                                    <g className="st-imgbox" pointerEvents="none"
                                        style={{ color: g.色 }}
                                        transform={`translate(${px - imgW / 2}, ${my - imgH - 6 - lift}) rotate(${tilt}, ${imgW / 2}, ${imgH})`}>
                                        <rect width={imgW} height={imgH} rx={10} />
                                        <text x={imgW / 2} y={imgH / 2} textAnchor="middle" dominantBaseline="middle">
                                            3:9
                                        </text>
                                    </g>
                                )}
                                {/* 神名：与神像同一倾斜角，绕自身锚点转 */}
                                <text className="st-god" x={nameX} y={my - imgH - 30} textAnchor="middle"
                                    transform={`rotate(${tilt} ${nameX} ${my - imgH - 30})`}
                                    style={{ fill: g.色 }}>
                                    {g.神}
                                </text>
                            </g>
                        );
                    })}
                </svg>
            )}

            {/* ---- 第二幕：某一行技能树 ---- */}
            {view && row && (
                <div className="st-tree-wrap" ref={treeWrapRef}>
                <svg className="st-tree"
                    width={fit.w * treeScale} height={fit.h * treeScale}
                    viewBox={`${fit.x} ${fit.y} ${fit.w} ${fit.h}`}
                    preserveAspectRatio="xMidYMid meet"
                    onClick={(e) => e.stopPropagation()}>
                    {edges.map(({ from, to }, i) => {
                        const a = pos.get(from), b = pos.get(to);
                        if (!a || !b) return null;
                        const d = `M ${a.x} ${a.y + 34} C ${a.x} ${a.y + 90}, ${b.x} ${b.y - 90}, ${b.x} ${b.y - 34}`;
                        return (
                            <g key={i}>
                                <path className="st-chain-glow" d={d} />
                                <path className="st-chain" d={d} />
                            </g>
                        );
                    })}
                    {rowNodes.map((n) => {
                        const p = pos.get(n.名称);
                        if (!p) return null;
                        const cls = n.状态 === "已学" ? "learned" : n.状态 === "可学" ? "available" : "locked";
                        return (
                            <g key={n.名称} className={`st-node ${cls}${sel?.名称 === n.名称 ? " sel" : ""}`}
                                transform={`translate(${p.x}, ${p.y})`}
                                style={{ ["--god" as string]: god?.色 }}
                                onClick={() => setSel(n)}>
                                <rect className="st-box" x={-100} y={-34} width={200} height={68} rx={12} />
                                <text className="st-name" y={-2} textAnchor="middle">{n.名称}</text>
                                <text className="st-cost" y={22} textAnchor="middle">
                                    {n.状态 === "已学" ? "已学" : `${n.花费} 点`}
                                </text>
                            </g>
                        );
                    })}
                </svg>
                </div>
            )}

            {msg && <div className="st-msg" onClick={(e) => e.stopPropagation()}>{msg}</div>}

            {/* ---- 详情卡 ---- */}
            {sel && (
                <div className="st-card" onClick={(e) => e.stopPropagation()}>
                    <div className="st-card-h">
                        <span className="st-card-name" style={{ color: god?.色 }}>{sel.名称}</span>
                        <span className={`st-tag ${sel.状态 === "已学" ? "ok" : sel.状态 === "可学" ? "can" : "no"}`}>
                            {sel.状态}{sel.状态 !== "已学" && ` · ${sel.花费} 点`}
                        </span>
                        <button className="st-card-x" onClick={() => setSel(null)}>✕</button>
                    </div>
                    <div className="st-card-body">
                        <p className="st-desc">{sel.描述}</p>
                        <div className="st-stats">
                            <span>内力 {sel.内力}</span><span>射程 {sel.射程}</span>
                            <span>范围 {sel.范围}</span><span>威力 {sel.威力}</span>
                            <span>连击 {sel.连击}</span>
                            {sel.效果.length > 0 && <span>效果 {sel.效果.join("、")}</span>}
                        </div>
                        <div className="st-req">
                            <span className="st-req-t">要求</span>
                            {Object.entries(sel.要求).length === 0
                                ? <span>无</span>
                                : Object.entries(sel.要求).map(([k, v]) => {
                                    const label = k === "熟练度" ? `${sel.五行}熟练度` : k;
                                    const cur = k === "熟练度"
                                        ? (view?.五行熟练度?.[sel.五行] ?? 0)
                                        : (view?.基础属性?.[k] ?? 0);
                                    const met = Number(cur) >= Number(v);
                                    return <span key={k} className={met ? "met" : "unmet"}>{label} {cur}/{v}</span>;
                                })}
                        </div>
                        {sel.前置.length > 0 && (
                            <div className="st-req"><span className="st-req-t">前置</span>
                                {sel.前置.map((x) => <span key={x}>{x}</span>)}
                            </div>
                        )}
                        {sel.状态 === "锁定" && <p className="st-why">✕ {sel.原因}</p>}
                    </div>
                    {sel.状态 === "可学" && (
                        <button className="st-learn" disabled={busy} onClick={() => doLearn(sel)}>
                            {busy ? "…" : `点亮（花 ${sel.花费} 点）`}
                        </button>
                    )}
                </div>
            )}
            </div>
        </div>
    );
}
