import type { JSX } from "react";
import type { BattleCombatant, BattleState } from "./battle";

// ============================================================
// BattleBoard —— 居中的「等轴测」战斗棋盘（SVG 2.5D）
//   实体系统：
//     人物实体 = 三角锥（底座）+ 球（头）  —— 象棋式棋子
//     地形实体 = 长方体（房屋=棕色 / 墙=灰色，河流=凹陷的蓝色长方体）
//   等轴测投影：sx=(x−y)·TW/2，sy=(x+y)·TH/2 − z
//   居中：按棋盘投影包围盒设 viewBox，SVG 自动 xMidYMid 居中缩放
// ============================================================

type Props = {
    战场: BattleState["战场"];
    action: string;
    selectedCell: [number, number] | null;
    target: string;
    移动力: number;
    技能?: { 射程?: number; 范围?: string };
    onCellClick: (x: number, y: number) => void;
    onTokenClick: (name: string) => void;
};

const TW = 60, TH = 30;          // 瓦片宽/高（2:1 等轴测）
const HOUSE_H = 30, WALL_H = 22, TREE_H = 26, RIVER_D = 9;
const CHAR_CONE_H = 20, CHAR_CONE_R = 13, CHAR_SPHERE_R = 9;

// 等轴测投影：视点在南（近端 x+y 小）；+x → 东北，+y → 西北
// 于是：友方（x 小）在西南，敌方（x 大）在东北
const iso = (x: number, y: number, z = 0): [number, number] =>
    [(x - y) * TW / 2, -(x + y) * TH / 2 - z];

const pts = (a: [number, number][]) =>
    a.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");

const tileQuad = (x: number, y: number, z = 0, s = 0.5): [number, number][] =>
    [iso(x - s, y - s, z), iso(x + s, y - s, z), iso(x + s, y + s, z), iso(x - s, y + s, z)];

const BLOCKING = new Set(["房屋", "墙"]);

const isAoeRange = (r?: string) => !!r && /^(区域|领域|扇形|直线|圆形)/.test(r);
const radiusOf = (r?: string) => { const m = /(\d+)/.exec(r ?? ""); return m ? parseInt(m[1]) : 1; };

// ---- 地形配色 ----
const COLORS: Record<string, { top: string; east: string; south: string; line: string }> = {
    房屋: { top: "#b07a52", east: "#835837", south: "#5f3f27", line: "#3d2a1a" },
    墙: { top: "#a7adb4", east: "#787e85", south: "#5b6066", line: "#3a3e42" },
};

// ------------------------------------------------------------
// 长方体（房屋 / 墙）
// ------------------------------------------------------------
function Cuboid({ x, y, h, kind }: { x: number; y: number; h: number; kind: string }) {
    const c = COLORS[kind] ?? COLORS.房屋;
    const s = 0.34, xp = x + s, yp = y + s, xm = x - s, ym = y - s;
    const top = [iso(xm, ym, h), iso(xp, ym, h), iso(xp, yp, h), iso(xm, yp, h)];
    // 可见侧面＝近端（x−s / y−s）两面
    const faceX = [iso(xm, ym, 0), iso(xm, yp, 0), iso(xm, yp, h), iso(xm, ym, h)];
    const faceY = [iso(xm, ym, 0), iso(xp, ym, 0), iso(xp, ym, h), iso(xm, ym, h)];
    return (
        <g>
            <polygon points={pts(faceX)} fill={c.east} stroke={c.line} strokeWidth={1} />
            <polygon points={pts(faceY)} fill={c.south} stroke={c.line} strokeWidth={1} />
            <polygon points={pts(top)} fill={c.top} stroke={c.line} strokeWidth={1} />
        </g>
    );
}

// ------------------------------------------------------------
// 凹陷的河流（地面下沉：远壁 + 河底）
// ------------------------------------------------------------
function River({ x, y }: { x: number; y: number }) {
    const o = 0.5, i = 0.42, d = RIVER_D;
    const bottom = [iso(x - i, y - i, -d), iso(x + i, y - i, -d),
                    iso(x + i, y + i, -d), iso(x - i, y + i, -d)];
    // 凹陷：远端两面内壁可见（x+o / y+o）+ 河底
    const wallX = [iso(x + o, y - o, 0), iso(x + o, y + o, 0),
                   iso(x + i, y + i, -d), iso(x + i, y - i, -d)];
    const wallY = [iso(x - o, y + o, 0), iso(x + o, y + o, 0),
                   iso(x + i, y + i, -d), iso(x - i, y + i, -d)];
    return (
        <g>
            <polygon points={pts(wallX)} fill="#24568a" stroke="#16324f" strokeWidth={1} />
            <polygon points={pts(wallY)} fill="#1e4a75" stroke="#16324f" strokeWidth={1} />
            <polygon points={pts(bottom)} fill="url(#water)" stroke="#16324f" strokeWidth={1} />
        </g>
    );
}

// ------------------------------------------------------------
// 树（棕色树干 + 绿色三角锥）
// ------------------------------------------------------------
function Tree({ x, y }: { x: number; y: number }) {
    const [bx, by] = iso(x, y, 0);
    const trunkH = 8, r = 11, apexY = by - TREE_H;
    return (
        <g>
            <ellipse cx={bx} cy={by} rx={9} ry={4} fill="#000" opacity={0.18} />
            <rect x={bx - 2.5} y={by - trunkH} width={5} height={trunkH} fill="#6b4a2a" />
            <polygon points={`${bx - r},${by - trunkH} ${bx + r},${by - trunkH} ${bx},${apexY}`}
                fill="#3f7a3a" stroke="#2c5a2a" strokeWidth={1} />
        </g>
    );
}

// ------------------------------------------------------------
// 人物实体：三角锥（底座）+ 球（头）
// ------------------------------------------------------------
function Piece({ c, selected, isTarget, onClick }: {
    c: BattleCombatant; selected: boolean; isTarget: boolean; onClick: () => void;
}) {
    const [bx, by] = iso(c.格[0], c.格[1], 0);
    const apexY = by - CHAR_CONE_H;
    const scy = apexY - CHAR_SPHERE_R + 3;
    const ally = c.阵营 === "友方";
    const cone = ally ? "#2f6ea3" : "#a83b30";
    const edge = selected || isTarget ? "#ffd75e" : (ally ? "#7fc0ea" : "#e59387");
    const hpPct = Math.max(0, Math.min(1, c.生命 / Math.max(1, c.生命上限)));
    const tpPct = Math.max(0, Math.min(1, c.内力 / Math.max(1, c.内力上限)));
    const label = c.名字 + (c.防守 ? "·守" : "");
    const buffs = (c.buff ?? []).map((b) => b.名称 + ((b.层数 ?? 1) > 1 ? `×${b.层数}` : "")).join(" ");
    return (
        <g onClick={(e) => { e.stopPropagation(); onClick(); }} style={{ cursor: "pointer" }}>
            <ellipse cx={bx} cy={by} rx={CHAR_CONE_R} ry={CHAR_CONE_R * 0.45} fill="#000" opacity={0.22} />
            {/* 三角锥底座 */}
            <polygon points={`${bx - CHAR_CONE_R},${by} ${bx + CHAR_CONE_R},${by} ${bx},${apexY}`}
                fill={cone} stroke={edge} strokeWidth={selected || isTarget ? 2.5 : 1.2} />
            <ellipse cx={bx} cy={by} rx={CHAR_CONE_R} ry={CHAR_CONE_R * 0.45}
                fill={ally ? "#3f82bb" : "#c14a3d"} stroke={edge} strokeWidth={selected || isTarget ? 2 : 1} />
            {/* 球 */}
            <circle cx={bx} cy={scy} r={CHAR_SPHERE_R}
                fill={ally ? "url(#allyBall)" : "url(#enemyBall)"} stroke={edge}
                strokeWidth={selected || isTarget ? 2.5 : 1} />
            {c.是玩家 && <circle cx={bx} cy={scy} r={CHAR_SPHERE_R + 3} fill="none" stroke="#ffd75e" strokeWidth={1.5} />}
            {/* 名牌 + 血/内力条 */}
            <g>
                <rect x={bx - 26} y={scy - CHAR_SPHERE_R - 26} width={52} height={12} rx={2}
                    fill="#0d0906" opacity={0.75} />
                <text x={bx} y={scy - CHAR_SPHERE_R - 17} textAnchor="middle"
                    fontSize={10} fill="#f5e6c8">{label}</text>
                <rect x={bx - 24} y={scy - CHAR_SPHERE_R - 11} width={48} height={4} fill="#00000088" />
                <rect x={bx - 24} y={scy - CHAR_SPHERE_R - 11} width={48 * hpPct} height={4} fill="#4ad06a" />
                <rect x={bx - 24} y={scy - CHAR_SPHERE_R - 6} width={48} height={3} fill="#00000088" />
                <rect x={bx - 24} y={scy - CHAR_SPHERE_R - 6} width={48 * tpPct} height={3} fill="#4a9fd0" />
                {buffs && (
                    <text x={bx} y={scy + CHAR_SPHERE_R + 12} textAnchor="middle" fontSize={9} fill="#e6c98a">
                        {buffs}
                    </text>
                )}
            </g>
        </g>
    );
}

// ------------------------------------------------------------
// 棋盘
// ------------------------------------------------------------
export default function BattleBoard({
    战场, action, selectedCell, target, 移动力, 技能, onCellClick, onTokenClick,
}: Props) {
    const W = 战场.宽度, H = 战场.高度;
    const alive = 战场.参战者.filter((c) => c.存活 && !c.已撤离);
    const byCell: Record<string, BattleCombatant> = {};
    for (const c of alive) byCell[`${c.格[0]},${c.格[1]}`] = c;
    const terrain: Record<string, string> = {};
    for (const t of (战场.地形 ?? []) as { 格: [number, number]; 类型: string }[]) {
        terrain[`${t.格[0]},${t.格[1]}`] = t.类型;
    }

    // 可达格（选「移动」时高亮）
    const player = alive.find((c) => c.是玩家);
    const reachable = new Set<string>();
    if (player && action === "移动") {
        const [px, py] = player.格;
        for (let dy = -移动力; dy <= 移动力; dy++) {
            for (let dx = -移动力; dx <= 移动力; dx++) {
                if (!dx && !dy) continue;
                const x = px + dx, y = py + dy;
                if (x < 0 || x >= W || y < 0 || y >= H) continue;
                const k = `${x},${y}`;
                if (byCell[k] || BLOCKING.has(terrain[k])) continue;
                reachable.add(k);
            }
        }
    }

    // AOE 技能：高亮可选中心格（射程内）+ 预览范围（半径）
    const aoe = action === "技能" && isAoeRange(技能?.范围);
    const aoeCenters = new Set<string>();
    const areaCells = new Set<string>();
    if (aoe && player) {
        const r = 技能?.射程 ?? 0;
        const [px, py] = player.格;
        for (let dy = -r; dy <= r; dy++) {
            for (let dx = -r; dx <= r; dx++) {
                const x = px + dx, y = py + dy;
                if (x >= 0 && x < W && y >= 0 && y < H) aoeCenters.add(`${x},${y}`);
            }
        }
        if (selectedCell) {
            const rad = radiusOf(技能?.范围);
            for (let dy = -rad; dy <= rad; dy++) {
                for (let dx = -rad; dx <= rad; dx++) {
                    const x = selectedCell[0] + dx, y = selectedCell[1] + dy;
                    if (x >= 0 && x < W && y >= 0 && y < H) areaCells.add(`${x},${y}`);
                }
            }
        }
    }

    // 居中：按投影包围盒设 viewBox
    const xs: number[] = [], ys: number[] = [];
    for (const [gx, gy] of [[-0.6, -0.6], [W - 0.4, -0.6], [W - 0.4, H - 0.4], [-0.6, H - 0.4]]) {
        for (const z of [-14, 52]) {
            const [sx, sy] = iso(gx, gy, z);
            xs.push(sx); ys.push(sy);
        }
    }
    const pad = 46;
    const minX = Math.min(...xs) - pad, minY = Math.min(...ys) - pad;
    const vb = `${minX} ${minY} ${Math.max(...xs) + pad - minX} ${Math.max(...ys) + pad - minY}`;

    // 深度排序（x+y 越大越靠前；人物在同格地形之后）
    type Obj = { depth: number; node: JSX.Element };
    const objects: Obj[] = [];
    for (let y = 0; y < H; y++) {
        for (let x = 0; x < W; x++) {
            const k = `${x},${y}`;
            const t = terrain[k];
            if (!t) continue;
            if (t === "房屋" || t === "墙") {
                objects.push({ depth: x + y, node: <Cuboid key={`t${k}`} x={x} y={y} h={t === "房屋" ? HOUSE_H : WALL_H} kind={t} /> });
            } else if (t === "河流") {
                objects.push({ depth: x + y + 0.1, node: <River key={`t${k}`} x={x} y={y} /> });
            } else if (t === "树") {
                objects.push({ depth: x + y, node: <Tree key={`t${k}`} x={x} y={y} /> });
            }
        }
    }
    for (const c of alive) {
        objects.push({
            depth: c.格[0] + c.格[1] + 0.5,
            node: <Piece key={`c${c.名字}`} c={c} selected={!!c.是玩家}
                isTarget={target === c.名字} onClick={() => onTokenClick(c.名字)} />,
        });
    }
    objects.sort((a, b) => b.depth - a.depth);   // x+y 越大越远 → 远的先画

    return (
        <svg className="bb-svg" viewBox={vb} preserveAspectRatio="xMidYMid meet">
            <defs>
                <radialGradient id="allyBall" cx="35%" cy="30%" r="75%">
                    <stop offset="0%" stopColor="#dff1ff" />
                    <stop offset="45%" stopColor="#69aede" />
                    <stop offset="100%" stopColor="#2f6ea3" />
                </radialGradient>
                <radialGradient id="enemyBall" cx="35%" cy="30%" r="75%">
                    <stop offset="0%" stopColor="#ffded8" />
                    <stop offset="45%" stopColor="#e0776a" />
                    <stop offset="100%" stopColor="#a83b30" />
                </radialGradient>
                <linearGradient id="water" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#3b86cc" />
                    <stop offset="100%" stopColor="#1f5a92" />
                </linearGradient>
            </defs>

            {/* 地面瓦片（棋盘底色） */}
            {Array.from({ length: H }).map((_, y) =>
                Array.from({ length: W }).map((__, x) => {
                    const k = `${x},${y}`;
                    const isSel = selectedCell?.[0] === x && selectedCell?.[1] === y;
                    const isReach = reachable.has(k);
                    const base = (x + y) % 2 ? "#2b2118" : "#332a1e";
                    let fill = base;
                    if (isReach) fill = "#6b5a2a";
                    if (aoeCenters.has(k)) fill = "#33456b";        // 可选中心格（蓝）
                    if (areaCells.has(k)) fill = "#c2601f";         // 将命中区域（橙，盖在中心格之上）
                    if (isSel) fill = "#e8c86a";                      // 已选中心（金）
                    return (
                        <polygon key={`g${k}`} points={pts(tileQuad(x, y))}
                            fill={fill} stroke="#5b4a2c" strokeWidth={0.8}
                            onClick={() => onCellClick(x, y)} style={{ cursor: "pointer" }} />
                    );
                })
            )}

            {/* 地形 + 人物（按深度） */}
            {objects.map((o, i) => <g key={i}>{o.node}</g>)}
        </svg>
    );
}
