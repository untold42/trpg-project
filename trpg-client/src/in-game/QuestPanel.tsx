import "../styles/QuestPanel.css";

// ------------------------------------------------------------
// 任务页面内容（外壳的宣纸背景 / 揭幕动画由 StaggeredMenu 提供，与数据页面同款）
//   进行中：卡片 + 右上角「追踪」正方形勾选框（最多 3 个）
//   已了结：只读回望（含里程碑完成情况与结果）
// 关掉只靠 Esc（前端约定：不放返回按钮）。
// ------------------------------------------------------------

export type QuestMilestone = { 项: string; 状态: string };
export type Quest = {
    id: string;
    标题: string;
    状态: string;
    描述?: string;
    委托人?: string;
    里程碑?: QuestMilestone[];
    时限?: { 显示?: string; 游戏秒?: number; 文本?: string };
    结果?: string | null;
    创建于?: string;
    归档于?: string | null;
};
export type QuestsView = { 进行中: Quest[]; 已了结: Quest[] };

type Props = {
    quests: QuestsView | null;
    tracked: string[];
    maxTracked: number;
    onToggleTrack: (id: string) => void;
    onTaskify: () => void;
    busy: boolean;
};

function 状态类(q: Quest): string {
    if (q.状态 === "已完成") return "done";
    if (q.状态 === "已过期") return "expired";
    return "active";
}

function 里程碑列表({ ms, fold }: { ms?: QuestMilestone[]; fold?: boolean }) {
    const list = fold ? (ms ?? []).slice(0, 3) : (ms ?? []);
    if (!list.length) return null;
    return (
        <ul className="quest-ms">
            {list.map((m, i) => (
                <li key={i} className={m.状态 === "已完成" ? "is-done" : ""}>
                    <span className="ms-mark">{m.状态 === "已完成" ? "✓" : "○"}</span>
                    {m.项}
                </li>
            ))}
        </ul>
    );
}

export default function QuestPanel({ quests, tracked, maxTracked, onToggleTrack, onTaskify, busy }: Props) {
    const 进行中 = quests?.进行中 ?? [];
    const 已了结 = quests?.已了结 ?? [];
    const full = tracked.length >= maxTracked;

    return (
        <div className="quest-panel">
            <div className="quest-head">
                <h3 className="quest-title">任务</h3>
                <div className="quest-head-right">
                    <span className="quest-track-count">追踪 {tracked.length} / {maxTracked}</span>
                    <button className="quest-taskify" onClick={onTaskify} disabled={busy}
                        title="把最近答应 / 正在做的那件事做成任务（会请一次旁路大模型）">
                        {busy ? "任务化中…" : "任务化当前事件"}
                    </button>
                </div>
            </div>

            <div className="quest-body">
                <div className="quest-section-title">进行中</div>
                {进行中.length ? 进行中.map((q) => {
                    const on = tracked.includes(q.id);
                    const locked = full && !on;
                    return (
                        <div className={"quest-card " + 状态类(q)} key={q.id}>
                            <div className="quest-card-head">
                                <span className="quest-card-name">{q.标题}</span>
                                <label className={"quest-track" + (on ? " on" : "") + (locked ? " locked" : "")}
                                    title={locked ? `最多追踪 ${maxTracked} 个` : (on ? "取消追踪" : "追踪")}>
                                    <input type="checkbox" checked={on} disabled={locked}
                                        onChange={() => onToggleTrack(q.id)} />
                                    <span className="quest-box" aria-hidden />
                                </label>
                            </div>
                            {q.描述 ? <div className="quest-desc">{q.描述}</div> : null}
                            {q.时限?.显示 ? (
                                <div className="quest-ddl">
                                    限期：{q.时限.显示}{q.时限.文本 ? `（${q.时限.文本}）` : ""}
                                </div>
                            ) : null}
                            <里程碑列表 ms={q.里程碑} />
                        </div>
                    );
                }) : <div className="quest-empty">（暂无进行中的任务）</div>}

                {已了结.length > 0 && (
                    <>
                        <div className="quest-section-title">已了结</div>
                        {已了结.map((q) => (
                            <div className={"quest-card " + 状态类(q)} key={q.id}>
                                <div className="quest-card-head">
                                    <span className="quest-card-name">{q.标题}</span>
                                    <span className="quest-badge">{q.状态}</span>
                                </div>
                                {q.结果 ? <div className="quest-desc">{q.结果}</div> : null}
                                <里程碑列表 ms={q.里程碑} />
                            </div>
                        ))}
                    </>
                )}
            </div>
        </div>
    );
}
