import "../styles/QuestTracker.css";
import type { Quest, QuestMilestone, QuestsView } from "./QuestPanel";

// ------------------------------------------------------------
// 追踪中的任务 HUD：游戏页面右上角，与古钟（左上）平齐。
//   任务名（字号大）+ 最多 3 条里程碑（已完成打勾/灰掉）。
//   点击打开任务页面。没追踪任何任务时整块不渲染。
// ------------------------------------------------------------

const HUD_MS_MAX = 3;

// HUD 只放 ≤3 条，且**未完成优先**：
// 若按原顺序取前 3 条，里程碑一完成就只剩打勾的旧项，看不到当下该做什么。
// （任务全完成时会轮换到已完成项，但那时任务本就快从「进行中」消失。）
function 摘要里程碑(ms?: QuestMilestone[]): QuestMilestone[] {
    const list = ms ?? [];
    const 未完成 = list.filter((m) => m.状态 !== "已完成");
    const 已完成 = list.filter((m) => m.状态 === "已完成");
    return [...未完成, ...已完成].slice(0, HUD_MS_MAX);
}

type Props = {
    quests: QuestsView | null;
    tracked: string[];
    onOpen: () => void;
};

export default function QuestTracker({ quests, tracked, onOpen }: Props) {
    if (!quests || tracked.length === 0) return null;
    const items = tracked
        .map((id) => quests.进行中.find((q) => q.id === id))
        .filter((q): q is Quest => Boolean(q));
    if (items.length === 0) return null;

    return (
        <div className="quest-tracker" role="button" tabIndex={0}
            title="追踪中的任务（点击打开任务）"
            onClick={onOpen}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") onOpen(); }}>
            {items.map((q) => {
                const 全部 = q.里程碑 ?? [];
                const 显示 = 摘要里程碑(全部);
                return (
                    <div className="qt-task" key={q.id}>
                        <div className="qt-name">{q.标题}</div>
                        <ul className="qt-ms">
                            {显示.map((m, i) => (
                                <li key={i} className={m.状态 === "已完成" ? "is-done" : ""}>{m.项}</li>
                            ))}
                        </ul>
                        {全部.length > HUD_MS_MAX && (
                            <div className="qt-more">共 {全部.length} 项 · 点击查看全部</div>
                        )}
                    </div>
                );
            })}
        </div>
    );
}
