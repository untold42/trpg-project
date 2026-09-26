import "../styles/DataPanel.css";
import type { PlayerState } from "./GameController";

// ------------------------------------------------------------
// 数据面板（全屏宣纸，复用菜单的美术资源 + 揭幕动画）
// ------------------------------------------------------------
// 3 个竖直区域（列），全量渲染：
//   属性.json            六维图（基础属性）+ 五维图（五行）+ 学识进度条 + 五行详情
//   状态.json / 基本信息.json   进度条（生命 / 精力 / 饥饿 / 健康）+ 基本信息分组
//   背包.json            物品列表（滚轮看 overflow 文字）+ 金钱
// 关掉只靠 Esc（前端约定：不放返回按钮）。组件只画内容；
// 外壳（面板背景 / clip 揭幕 / 开关）由 StaggeredMenu 提供。

type Dict = Record<string, unknown>;

function num(v: unknown): number {
    const n = Number(v);
    return Number.isFinite(n) ? n : 0;
}
function str(v: unknown): string {
    if (v === null || v === undefined || v === "") return "—";
    if (typeof v === "object") return JSON.stringify(v);
    return String(v);
}

/* ===== 雷达图（六维 / 五维共用） ===== */
type RadarPoint = { label: string; value: number };

function RadarChart({ title, points }: { title: string; points: RadarPoint[] }) {
    const size = 240;
    const cx = size / 2;
    const cy = size / 2;
    // 留出四周给轴标签的边距（r 越小，标签越不容易和数据/彼此重叠）
    const r = size / 2 - 58;
    const n = Math.max(3, points.length);
    // 归一到 100 起（无上限属性超 100 时自动放大基准），保证图不塌也不溢出
    const max = Math.max(100, ...points.map((p) => p.value));
    const ang = (i: number) => -Math.PI / 2 + (i * 2 * Math.PI) / n;
    const pt = (i: number, rad: number): [number, number] =>
        [cx + rad * Math.cos(ang(i)), cy + rad * Math.sin(ang(i))];
    const ring = (f: number) => points.map((_, i) => pt(i, r * f).join(",")).join(" ");
    const area = points.map((p, i) => pt(i, r * Math.min(1, p.value / max)).join(",")).join(" ");

    return (
        <div className="radar">
            <div className="radar-title">{title}</div>
            <svg className="radar-svg" viewBox={`0 0 ${size} ${size}`} role="img">
                {[0.25, 0.5, 0.75, 1].map((f) => (
                    <polygon key={f} className="radar-ring" points={ring(f)} />
                ))}
                {points.map((_, i) => {
                    const [x, y] = pt(i, r);
                    return <line key={i} className="radar-axis" x1={cx} y1={cy} x2={x} y2={y} />;
                })}
                <polygon className="radar-area" points={area} />
                {points.map((p, i) => {
                    const [x, y] = pt(i, Math.min(1, p.value / max) * r);
                    return <circle key={i} className="radar-dot" cx={x} cy={y} r={3} />;
                })}
                {points.map((p, i) => {
                    // 标签与数值**合成一行**放在环外，避免两个字块错位重叠
                    const [lx, ly] = pt(i, r + 21);
                    return (
                        <text key={i} className="radar-label" x={lx} y={ly} textAnchor="middle" dominantBaseline="middle">
                            {p.label} {p.value}
                        </text>
                    );
                })}
            </svg>
        </div>
    );
}

/* ===== 进度条 ===== */
function Bar({ label, value, max }: { label: string; value: number; max: number }) {
    const pct = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
    return (
        <div className="bar">
            <div className="bar-head">
                <span className="bar-label">{label}</span>
                <span className="bar-val">{value} / {max}</span>
            </div>
            <div className="bar-track">
                <div className="bar-fill" style={{ width: `${pct}%` }} />
            </div>
        </div>
    );
}

/* ===== 六维 / 五维 轴定义（顺序固定，与策划一致） ===== */
const 六维键 = ["体力", "内力", "剑法", "拳掌", "暗器", "轻功"] as const;
const 五行键 = ["火", "金", "木", "土", "水"] as const;
const 学识键 = ["口舌", "知识"] as const;

export default function DataPanel({ state }: { state: PlayerState | null }) {
    const 属性 = (state?.属性 ?? {}) as Dict;
    const 基础 = (属性.基础属性 ?? {}) as Dict;
    const 五行 = (属性.五行 ?? {}) as Dict;
    const 学识 = (属性.学识 ?? {}) as Dict;
    const 状态 = (state?.状态 ?? {}) as Dict;
    const 基本信息 = (state?.基本信息 ?? {}) as Dict;
    const 物品 = ((state?.背包 ?? {}) as Dict).物品 as Dict | undefined;
    const 金钱 = (state?.金钱 ?? {}) as Dict | undefined;

    const 六维: RadarPoint[] = 六维键.map((k) => ({ label: k, value: num(基础[k]) }));
    const 五维: RadarPoint[] = 五行键.map((k) => ({ label: k, value: num((五行[k] as Dict)?.熟练度) }));
    const 背包条目 = Object.entries(物品 ?? {}) as [string, Dict][];

    return (
        <div className="data-cols">
            {/* ---- 属性.json ---- */}
            <section className="data-col">
                <h3 className="data-col-title">属性</h3>
                <div className="data-col-body">
                    <RadarChart title="基础属性" points={六维} />
                    <RadarChart title="五行" points={五维} />

                    <div className="sub-title">学识</div>
                    {学识键.map((k) => (
                        <Bar key={k} label={k} value={num(学识[k])} max={100} />
                    ))}

                    <div className="sub-title">五行详情</div>
                    {五行键.map((k) => {
                        const o = (五行[k] ?? {}) as Dict;
                        return (
                            <div className="wuxing" key={k}>
                                <div className="wuxing-head">
                                    <span className="wuxing-name">{k}</span>
                                    <span className="wuxing-lv">{str(o.层次)}</span>
                                    <span className="wuxing-pct">{num(o.熟练度)}</span>
                                    {String(o.主修) === "是" && <span className="wuxing-main">主修</span>}
                                </div>
                                <div className="wuxing-desc">{str(o.描述)}</div>
                            </div>
                        );
                    })}
                </div>
            </section>

            {/* ---- 状态.json + 基本信息.json（合并一个矩形区域） ---- */}
            <section className="data-col">
                <h3 className="data-col-title">状态 · 基本信息</h3>
                <div className="data-col-body">
                    <Bar label="生命" value={num(状态.生命值)} max={num(状态.生命上限)} />
                    <Bar label="精力" value={num(状态.精力值)} max={num(状态.精力上限)} />
                    <Bar label="饥饿" value={num(状态.饥饿)} max={100} />
                    <Bar label="健康" value={num(状态.健康)} max={100} />

                    {Object.entries(基本信息).map(([group, val]) => (
                        <div className={"data-group" + (group === "天气" ? " is-weather" : "")} key={group}>
                            <div className="data-group-title">{group}</div>
                            {val && typeof val === "object" ? (
                                <dl className="data-fields">
                                    {Object.entries(val as Dict).map(([k, v]) => (
                                        <div className="data-field" key={k}>
                                            <dt>{k}</dt>
                                            <dd>{str(v)}</dd>
                                        </div>
                                    ))}
                                </dl>
                            ) : (
                                <div className="data-field"><dd>{str(val)}</dd></div>
                            )}
                        </div>
                    ))}
                </div>
            </section>

            {/* ---- 背包.json ---- */}
            <section className="data-col">
                <h3 className="data-col-title">背包</h3>
                <div className="data-col-body">
                    <div className="money-line">金钱 · {金钱?.金钱 == null ? "—" : `${str(金钱.金钱)} 文`}</div>
                    {背包条目.length ? 背包条目.map(([name, it]) => (
                        <div className="bag-item" key={name}>
                            <div className="bag-head">
                                <span className="bag-name">{name}</span>
                                <span className="bag-qty">×{str(it.数量 ?? 1)}</span>
                            </div>
                            <div className="bag-meta">
                                {it.类型 ? <span className="bag-tag">{str(it.类型)}</span> : null}
                                {it.随身携带 ? <span className="bag-tag">随身</span> : null}
                            </div>
                            {it.描述 ? <div className="bag-desc">{str(it.描述)}</div> : null}
                        </div>
                    )) : <div className="data-empty">（空空如也）</div>}
                </div>
            </section>
        </div>
    );
}
