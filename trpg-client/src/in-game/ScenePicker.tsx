import { useEffect, useMemo, useState } from "react";
import backgroundImages from "../assets/背景_重构";
import { getBackgroundImage, sceneDir } from "./background";
import "../styles/ScenePicker.css";

// ------------------------------------------------------------
// 场景选择器（前端）
// ------------------------------------------------------------
// 数据源就是 `assets/背景_重构/<场景>/{白天,黄昏,黑夜}.png`——
// 目录名 = 地图 kind 名 = 后端发来的 `position`，三者是同一个词表。
// 这个面板把「前端拿得到图的场景」全部列出来，供预览 / 手动选景：
//   - 游戏内（☰ 菜单 → 场景选择）：点卡片 → onPick(场景) → GameController 换背景；
//   - 主菜单（环境设定 → 场景预览）：不传 onPick，纯看。
// 只列**至少有一张图**的目录，空目录（如尚未出图的「水域 / 笔坊」）自动排除。

/** 三时段；与 background.ts 的 convertTime 同一套词。 */
const PERIODS = ["白天", "黄昏", "黑夜"] as const;
type Period = (typeof PERIODS)[number];

/** 从 glob 键里剥出所有「有图的场景」目录名。 */
function sceneNamesFromGlob(): string[] {
    const names = new Set<string>();
    for (const key of Object.keys(backgroundImages)) {
        const m = /^\.\/(?:城内|城外|室内)\/([^/]+)\/(?:白天|黄昏|黑夜)\.png$/.exec(key);
        if (m) names.add(m[1]);
    }
    return Array.from(names).sort((a, b) => a.localeCompare(b, "zh-Hans-CN"));
}

/** 该场景实际有哪些时段图（用于角标 / 提示）。 */
function periodsOf(scene: string): Period[] {
    return PERIODS.filter((p) => backgroundImages[`${sceneDir(scene)}${p}.png`]);
}

export type ScenePickerProps = {
    /** 当前正在用的场景名（高亮） */
    current?: string;
    /** 面板打开时默认预览的时段 */
    period?: string;
    /** 给了就代表「可选」：点卡片 / 点选择按钮会回调；不给 = 纯预览 */
    onPick?: (scene: string) => void;
    onClose: () => void;
};

export default function ScenePicker({ current, period, onPick, onClose }: ScenePickerProps) {
    const scenes = useMemo(() => sceneNamesFromGlob(), []);

    // 预览时段：进来时用当前时辰对应的时段（没有就白天）
    const [view, setView] = useState<Period>(() => {
        const p = (period || "").trim() as Period;
        return (PERIODS as readonly string[]).includes(p) ? p : "白天";
    });
    const [query, setQuery] = useState("");
    // 玩家在本面板手选过就用手选的；否则跟随游戏当前场景（不再用 effect 同步）
    const [picked, setPicked] = useState<string>("");

    const filtered = useMemo(() => {
        const q = query.trim();
        return q ? scenes.filter((s) => s.includes(q)) : scenes;
    }, [scenes, query]);

    const selected = picked
        || (current && scenes.includes(current) ? current : "")
        || filtered[0]
        || scenes[0]
        || "";
    // 选中项不在过滤结果里时，预览仍显示它（只要还有图）
    const previewScene = selected && scenes.includes(selected) ? selected : (filtered[0] ?? "");

    function choose(scene: string) {
        setPicked(scene);
        onPick?.(scene);
    }

    // 键盘：Esc 关（不抢全局 Esc 栈——这个面板是单层的，直接监听即可）
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            if (e.key === "Escape") {
                e.stopPropagation();
                onClose();
            }
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [onClose]);

    return (
        <div className="scene-picker-overlay" onClick={onClose}>
            <div className="scene-picker" onClick={(e) => e.stopPropagation()}>
                <header className="sp-head">
                    <div className="sp-title">
                        场景选择
                        <span className="sp-count">{scenes.length} 处</span>
                    </div>

                    <div className="sp-periods">
                        {PERIODS.map((p) => (
                            <button
                                key={p}
                                className={"sp-period" + (view === p ? " active" : "")}
                                onClick={() => setView(p)}
                                title={`预览${p}`}
                            >
                                {p}
                            </button>
                        ))}
                    </div>

                    <input
                        className="sp-search"
                        placeholder="搜场景…"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                    />

                    <button className="sp-close" onClick={onClose}>返回</button>
                </header>

                <div className="sp-body">
                    <div className="scene-grid">
                        {filtered.map((scene) => {
                            const hers = periodsOf(scene);
                            const img = getBackgroundImage(scene, view);
                            const isCurrent = scene === current;
                            const isSelected = scene === previewScene;
                            return (
                                <button
                                    key={scene}
                                    className={
                                        "scene-card" +
                                        (isSelected ? " selected" : "") +
                                        (isCurrent ? " current" : "")
                                    }
                                    onClick={() => choose(scene)}
                                    title={`${scene}（${hers.join("/") || "无图"}）`}
                                >
                                    <img src={img} alt={scene} loading="lazy" draggable={false} />
                                    <span className="scene-card-name">{scene}</span>
                                    {isCurrent && <span className="scene-card-badge">当前</span>}
                                    {!hers.includes(view) && (
                                        <span className="scene-card-fallback">
                                            {fallbackNote(hers, view)}
                                        </span>
                                    )}
                                </button>
                            );
                        })}
                        {!filtered.length && (
                            <div className="scene-grid-empty">没有匹配「{query.trim()}」的场景</div>
                        )}
                    </div>

                    {previewScene && (
                        <aside className="scene-preview">
                            <div className="scene-preview-frame">
                                <img
                                    src={getBackgroundImage(previewScene, view)}
                                    alt={previewScene}
                                    draggable={false}
                                />
                            </div>
                            <div className="scene-preview-name">{previewScene}</div>
                            <div className="scene-preview-periods">
                                {PERIODS.map((p) => (
                                    <span
                                        key={p}
                                        className={"sp-chip" + (periodsOf(previewScene).includes(p) ? " on" : "")}
                                    >
                                        {p}
                                    </span>
                                ))}
                            </div>
                            {onPick && (
                                <button
                                    className="scene-apply"
                                    onClick={() => choose(previewScene)}
                                >
                                    {previewScene === current ? "正在使用" : "选择此景"}
                                </button>
                            )}
                        </aside>
                    )}
                </div>
            </div>
        </div>
    );
}

/** 缺图时的角标文案：`无黄昏·用白天` 之类。 */
function fallbackNote(hers: Period[], view: Period): string {
    if (hers.includes(view)) return "";
    if (hers.includes("白天")) return `无${view}·用白天`;
    return `无${view}`;
}
