import { useEffect, useState } from "react";
import "../styles/FacilityPanel.css";

export type FacilityOption = {
    标签: string;
    意图?: string;
    类型?: string;   // 养成 | 自由
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
    const [text, setText] = useState("");
    const name = detail.名称 || place;
    const options = detail.选项 || [];

    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            if (e.key === "Escape" && !busy && !leaving) onClose();
        };
        document.addEventListener("keydown", onKey);
        return () => document.removeEventListener("keydown", onKey);
    }, [onClose, busy, leaving]);

    function pick(o: FacilityOption) {
        if (busy || leaving) return;
        if (o.标签 === "其他") { setOtherMode(true); return; }
        if (o.意图) onChoose(`进入${name}，想要${o.意图}`);
        else onChoose(`进入「${name}」`);
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
