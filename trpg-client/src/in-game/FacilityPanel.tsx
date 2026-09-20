import { useState } from "react";
import { useEsc } from "../escStack";
import "../styles/FacilityPanel.css";

export type FacilityOption = {
    标签: string;
    意图?: string;
    类型?: string;   // 养成 | 自由
    效果类型?: string;   // 点数 | buff（点数才有时长选择）
    介绍?: string;
    图标?: string;
};

export type FacilityDetail = {
    success?: boolean;
    名称?: string;
    kind?: string;
    选项?: FacilityOption[];
    耗时刻?: number;
    背景?: string;
    error?: string;
};

//: 修行时长可选（刻）：1 时辰 = 8 刻
const KE_CHOICES: { v: number; t: string }[] = [
    { v: 2, t: "2刻（约半小时）" },
    { v: 4, t: "4刻（半个时辰）" },
    { v: 8, t: "8刻（一个时辰）" },
    { v: 16, t: "16刻（两个时辰）" },
];

function keLabel(ke: number): string {
    const hit = KE_CHOICES.find((c) => c.v === ke);
    return hit ? hit.t.replace(/^\d+刻（|）$/g, "") : `${ke}刻`;
}

/**
 * 基础设施「详细」界面：菱形事件图 + 类型（养成/自由）+ 活动名 + 固定介绍。
 * 版式对齐 `assets/ui/基础设施活动未选中按钮.png`（左菱形图标槽 / 右文本区）。
 * 选中某项 → 回传「进入〈名称〉，想要〈意图〉」，由 GameController 发给主持人。
 */
export default function FacilityPanel({
    place, detail, bgImage, busy = false, leaving = false, onChoose, onClose,
}: {
    place: string;
    detail: FacilityDetail;
    bgImage?: string;
    busy?: boolean;      // 已选项、等主持人回应中（保持本页，不切回探索地图）
    leaving?: boolean;   // 回应到、淡出中
    onChoose: (text: string) => void;
    onClose: () => void;
}) {
    const [otherMode, setOtherMode] = useState(false);
    // 修行时长（刻）：仅「点数」类选项生效；默认 8 刻＝1 个时辰
    const [ke, setKe] = useState(8);
    const [text, setText] = useState("");
    const name = detail.名称 || place;
    const options = detail.选项 || [];

    // Esc：层级栈里自己这一层（忙碌 / 淡出中不响应）
    useEsc(() => { if (!busy && !leaving) onClose(); });
    function pick(o: FacilityOption) {
        if (busy || leaving) return;
        if (o.标签 === "其他") { setOtherMode(true); return; }
        const dur = o.效果类型 === "点数" ? `（修行${ke}刻＝${keLabel(ke)}）` : "";
        if (o.意图) onChoose(`进入${name}，想要${o.意图}${dur}`);
        else onChoose(`进入「${name}」${dur}`);
    }
    function submitOther() {
        if (busy || leaving) return;
        const t = text.trim();
        if (!t) return;
        onChoose(`进入${name}，${t}`);
    }

    return (
        <div
            className={`facility-overlay${busy ? " busy" : ""}${leaving ? " leaving" : ""}`}
            onClick={busy || leaving ? undefined : onClose}
        >
            {bgImage && (
                <div className="facility-bg"><img src={bgImage} alt="" /></div>
            )}
            <div className="facility-panel" onClick={(e) => e.stopPropagation()}>
                <div className={`facility-list n${Math.min(options.length, 4) || 1}${busy || leaving ? " disabled" : ""}`}>
                    {options.map((o, i) => {
                        const grow = (o.类型 || "养成") !== "自由";
                        return (
                            <button
                                className="facility-row"
                                key={`${o.标签}-${i}`}
                                onClick={() => pick(o)}
                            >
                                <span className="facility-icon">
                                    {o.图标 ? (
                                        <img
                                            src={`/eventicons/${o.图标}.png`}
                                            alt=""
                                            onError={(e) => {
                                                (e.currentTarget as HTMLImageElement).style.visibility = "hidden";
                                            }}
                                        />
                                    ) : null}
                                </span>
                                <span className="facility-text">
                                    <span className={`facility-type ${grow ? "grow" : "free"}`}>
                                        {grow ? "养成" : "自由"}
                                    </span>
                                    <span className="facility-opt">{o.标签}</span>
                                    <span className="facility-desc">{o.介绍 || ""}</span>
                                </span>
                            </button>
                        );
                    })}
                    {!options.length && (
                        <div className="facility-empty">（此地无明显活动，可用「其他」自行说明）</div>
                    )}
                </div>

                {busy && <div className="facility-hint">……</div>}

                {options.some((o) => o.效果类型 === "点数") && !busy && !leaving && (
                    <div className="facility-time">
                        <span className="ft-label">修行时长</span>
                        {KE_CHOICES.map((c) => (
                            <button
                                key={c.v}
                                className={`ft-btn${ke === c.v ? " on" : ""}`}
                                onClick={(e) => { e.stopPropagation(); setKe(c.v); }}
                            >
                                {c.t}
                            </button>
                        ))}
                    </div>
                )}

                {otherMode && (
                    <div className="facility-other">
                        <input
                            autoFocus
                            value={text}
                            placeholder="想做什么…"
                            onChange={(e) => setText(e.target.value)}
                            onKeyDown={(e) => { if (e.key === "Enter") submitOther(); }}
                        />
                        <button onClick={submitOther}>确定</button>
                    </div>
                )}
            </div>
        </div>
    );
}
