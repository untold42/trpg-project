import { useState } from "react";
import "../styles/ToolLogPanel.css";

// ------------------------------------------------------------
// 工具执行日志（工具GM 的落地记录）：放在**任务追踪条下面**，同一条右侧栏。
//   - **默认折叠**成一个小标签（不碍眼），点一下展开；
//   - 只有**真的有工具调用**的轮次才显示（无操作的后端已过滤）；
//   - 处理中时小标签上有个呼吸小点。
// ------------------------------------------------------------

export type ToolLogEntry = {
    ts?: string;
    game_time?: string;
    mode?: string;
    叙事?: string;
    calls?: { tool: string; args?: Record<string, unknown>; result?: unknown }[];
    status?: string;
    摘要?: string;
};

export default function ToolLogPanel({ entries, pending = 0 }: { entries: ToolLogEntry[]; pending?: number }) {
    const [open, setOpen] = useState(false);
    const list = entries ?? [];
    if (list.length === 0 && !pending) return null;

    return (
        <div className="tool-log">
            <button className={"tl-toggle" + (open ? " open" : "")}
                onClick={() => setOpen((o) => !o)}
                title="工具GM 的落地记录（点击展开/收起）">
                <span className="tl-label">执行日志</span>
                {pending > 0 && <span className="tl-dot" title="工具GM 处理中" />}
                {list.length > 0 && <span className="tl-count">{list.length}</span>}
                <span className="tl-caret">{open ? "▾" : "▸"}</span>
            </button>

            {open && (
                <div className="tl-list">
                    {[...list].reverse().map((e, i) => (
                        <div className="tl-entry" key={i}>
                            <div className="tl-head">
                                <span className="tl-time">{e.game_time || e.ts || ""}</span>
                                <span className={"tl-status " + (e.status === "已完成" ? "ok" : "warn")}>
                                    {e.status || ""}
                                </span>
                            </div>
                            {e.叙事 ? (
                                <div className="tl-intent">
                                    {e.叙事}{e.叙事.length >= 200 ? "…" : ""}
                                </div>
                            ) : null}
                            {(e.calls ?? []).length > 0 && (
                                <div className="tl-calls">
                                    {(e.calls ?? []).map((c) => c.tool).join(" / ")}
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}
