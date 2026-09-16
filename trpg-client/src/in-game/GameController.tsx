import GameScene from "./GameScene";
import "../styles/GameController.css"
import "../styles/Background.css"
import { useEffect, useMemo, useRef, useState } from "react";
import type { instruction } from "../types/gametype";
import preloadImages from "./PreloadImages";
import GameMap from "./Map"
import { StaggeredMenu } from "./Staggered Menu";
import AccordionGallery, { type AccordionGalleryItem } from "./AccordionGallery";
import { 默认背景, getBackgroundImage } from "./background";
import { playMusic, stopMusic } from "./music";
import BattleScene, { type BattleState } from "./battle";
import Clock from "./Clock";
import { fetchClock, requestClockSync, useWorldTime } from "./useGameClock";

// 游戏内步速（米/游戏秒）——真实速度 = 步速 × 时钟倍率，
// 这样「游戏内移动速度」与时间保持一致（时间快 15 倍 → 标记也快 15 倍地跑）。
//
// 1.4 是真实步行速度，但在这个地图尺度下显得捷（太拖）；
// 调到 2.2（快走），再配合 Shift 奔跑。
const BASE_WALK_MPS = 2.2;

// 按住 Shift 的速度倍数（跑）：2.6 × 2.2 ≈ 5.7 米/游戏秒，接近冲刺
const RUN_MULT = 2.6;

// 承接App.tsx
type GamingProps = {
    onBackMenu: () => void;
    // 前情回顾选定的「最后一幕」bg/音乐（无缝衔接）；无则用默认
    initialBg?: { position?: string; time?: string } | null;
    initialMusic?: string | null;
    // 前情回顾段落（≤10 段 narration）：进入游戏后先放这个，点击推进完才进入正常游戏
    initialRecap?: instruction[] | null;
};

//预加载前端资源
const images = import.meta.glob(
    [
        "../assets/**/*.{png,jpg,jpeg,webp}",
        // 画廊图较大（10 张约 20MB），不进预加载，打开画廊时按需加载
        "!../assets/画廊/**"
    ],
    {
        eager: true,
        query: "?url",
        import: "default"
    }
);

// 江湖势力画廊：自动取 assets/画廊 下的图，介绍来自后端 GET /factions（trpg-world/势力介绍.json）
const galleryRawImages = import.meta.glob(
    "../assets/画廊/*.{png,jpg,jpeg,webp}",
    {
        eager: true,
        query: "?url",
        import: "default"
    }
);

// 优化版（压缩过的 jpg，体积约为原图 1/6），放 画廊/web/ 下
const galleryWebImages = import.meta.glob(
    "../assets/画廊/web/*.{png,jpg,jpeg,webp}",
    {
        eager: true,
        query: "?url",
        import: "default"
    }
);

// 图片按文件名建索引：帮派名 -> 图片 url
const galleryUrlByName: Record<string, string> = {};
for (const [path, url] of Object.entries(galleryRawImages)) {
    const name = path.split("/").pop()!.replace(/\.(png|jpe?g|webp)$/i, "");
    galleryUrlByName[name] = url as string;
}
// web/ 下的优化版覆盖原图（没有优化版就自动用原图）
for (const [path, url] of Object.entries(galleryWebImages)) {
    const name = path.split("/").pop()!.replace(/\.(png|jpe?g|webp)$/i, "");
    galleryUrlByName[name] = url as string;
}

// 每行放几个帮派
const GALLERY_ROW_SIZE = 5;

// 画廊条目 = 组件需要的字段 + 全屏阅读用的 detail
type 画廊条目 = AccordionGalleryItem & { detail: string };

// 势力条目：**从后端 GET /factions 取**（数据源 trpg-world/势力介绍.json）
type FactionEntry = { name: string; desc: string; detail: string };

async function fetchFactions(): Promise<FactionEntry[]> {
    try {
        const res = await fetch("http://localhost:5000/factions");
        if (!res.ok) return [];
        const data = await res.json();
        return Array.isArray(data) ? data : [];
    } catch {
        return [];
    }
}

// ---- 玩家状态（GET /state）----
type PlayerState = {
    金钱?: { 金钱?: number };
    状态?: Record<string, unknown>;
    背包?: { 物品?: Record<string, { 类型?: string; 数量?: number }> };
    属性?: { 基础属性?: Record<string, unknown> };
    基本信息?: Record<string, unknown>;
};

type UiEvent = Extract<instruction, { type: "ui" }>;
type NarrativeLine = Extract<instruction, { type: "chat" } | { type: "narration" }>;

// 把 unknown 安全地转成可显示文本
function show(v: unknown): string | number {
    if (v === null || v === undefined || v === "") return "—";
    if (typeof v === "string" || typeof v === "number") return v;
    return String(v);
}

// 读取玩家状态（GET /state）；后端没起时返回 null
async function getState(): Promise<PlayerState | null> {
    try {
        const res = await fetch("http://localhost:5000/state");
        if (!res.ok) return null;
        return await res.json();
    } catch {
        return null;
    }
}

// 读取当前本局历史（current.jsonl 是唯一真相源）
type HistoryView = { active: boolean; lines: string[]; tail: instruction[] };

async function fetchHistory(): Promise<HistoryView | null> {
    try {
        const res = await fetch("http://localhost:5000/history");
        if (!res.ok) return null;
        return await res.json();
    } catch {
        return null;
    }
}

function Gaming({ onBackMenu, initialBg, initialMusic, initialRecap }: GamingProps) {
    const [showInputGM, setshowInputGM] = useState(false); //展示主持人输入框
    const [showInputAct, setShowInputAct] = useState(false); //展示行动输入框
    const [showInputSay, setShowInputSay] = useState(false); //展示台词输入框
    const [input, setInput] = useState(""); //输入框输入的内容
    const [history, setHistory] = useState<instruction[]>([]); //拿到llm的回复
    const historyRef = useRef<instruction[]>([]); // 同步 history 长度（探索→叙事断点用）
    historyRef.current = history;
    // 叙事层对话框的起始句下标：探索→叙事时跳到**本轮叙事的第一句**
    const [sceneStart, setSceneStart] = useState(0);
    // 前情回顾（进入游戏后先播，点击推进完才进正常游戏；null = 无回顾）
    const [recap, setRecap] = useState<instruction[] | null>(
        initialRecap && initialRecap.length ? initialRecap : null
    );
    const [showHistory, setShowHistory] = useState(false) //展示历史记录
    const [loaded, setLoaded] = useState(false); //判断是否加载完成
    const historyBoxRef = useRef<HTMLDivElement>(null);//历史对话框的保持底部
    const [showMap, setShowMap] = useState(false);//展示地图
    const [showGallery, setShowGallery] = useState(false);//展示势力画廊
    const [showData, setShowData] = useState(false); // 数据面板（金钱/背包/属性/状态）
    const [readingIndex, setReadingIndex] = useState<number | null>(null);
    const [playerState, setPlayerState] = useState<PlayerState | null>(null); // 玩家真实状态
    const [background, setBackground] = useState<string>(
        initialBg?.position ? getBackgroundImage(initialBg.position, initialBg.time ?? "") : 默认背景
    ); // 当前背景（由 UI 事件控制）
    const [historyLines, setHistoryLines] = useState<string[]>([]); // 历史面板（读后端）
    const [factions, setFactions] = useState<FactionEntry[]>([]); // 势力画廊（GET /factions）

    // 画廊条目：顺序由后端 /factions 数组决定；没有对应图片的自动跳过
    const galleryItems: 画廊条目[] = useMemo(
        () => factions
            .filter((s) => galleryUrlByName[s.name])
            .map((s) => ({
                image: galleryUrlByName[s.name],
                label: s.name,
                description: s.desc,
                detail: s.detail || s.desc,
            })),
        [factions]
    );
    const galleryRows: 画廊条目[][] = useMemo(() => {
        const rows: 画廊条目[][] = [];
        for (let i = 0; i < galleryItems.length; i += GALLERY_ROW_SIZE) {
            rows.push(galleryItems.slice(i, i + GALLERY_ROW_SIZE));
        }
        return rows;
    }, [galleryItems]);
    const [showContinue, setShowContinue] = useState(false); // 「继续」的刻数选项
    const [battleState, setBattleState] = useState<BattleState | null>(null); // 战斗界面（可阻塞）
    // 探索模式的叙事浮层（#3）：从叙事切回探索时，本轮 GM 的话在地图上看不见
    const [exploreLines, setExploreLines] = useState<NarrativeLine[]>([]);
    const [exploreIdx, setExploreIdx] = useState(0);

    // ---- 状态机：explore（整屏地图）/ narrative（对话+立绘+时钟）/ battle（战棋）----
    // 进入叙事由玩家输入发动；退出叙事由主持人裁定（工具 resume_exploration → kind:"mode"）
    const [gameMode, setGameMode] = useState<"explore" | "narrative" | "battle">("explore");
    // 光标位置：cursorRef = 实时真相（WASD 每帧写）；cursor = 停下来时的快照（用于迷雾轨迹）
    const [cursor, setCursor] = useState<{ lon: number; lat: number } | null>(null);
    const cursorRef = useRef<{ lon: number; lat: number } | null>(null);
    const prevCursorRef = useRef<{ lon: number; lat: number } | null>(null); // 上一次「输入」时的位置
    const [clockRate, setClockRate] = useState(15);                           // 时钟倍率（移动速度随它缩放）
    const [sending, setSending] = useState(false);                            // LLM 请求进行中（时钟冻结）
    const { isNight, shichen } = useWorldTime();                            // 昼夜 + 时辰：地图夜色 + 打烊不亮灯

    // 统一处理 /state 返回：更新状态
    function applyState(s: PlayerState | null) {
        if (!s) return;
        setPlayerState(s);
    }

    // UI 事件旁路：kind:"bg" 切背景；kind:"music" 切音乐；kind:"mode" 返回给调用方定模式
    function handleUiEvents(events: UiEvent[]): "explore" | "narrative" | null {
        let mode: "explore" | "narrative" | null = null;
        for (const ev of events) {
            if (ev.kind === "bg") {
                setBackground(getBackgroundImage(
                    String(ev.data.position ?? ""),
                    String(ev.data.time ?? "")
                ));
            } else if (ev.kind === "music") {
                playMusic(String(ev.data.track ?? ""));
            } else if (ev.kind === "battle") {
                // 战斗界面（可阻塞）：data 即 /battle/state 的结构
                setBattleState(ev.data as unknown as BattleState);
            } else if (ev.kind === "mode") {
                // 模式切换（主持人裁定）：回探索 / 进叙事
                const m = String(ev.data.mode ?? "");
                if (m === "explore" || m === "narrative") {
                    mode = m;
                    setGameMode(m);
                }
            } else {
                console.debug("[ui]", ev.kind, ev.data);
            }
        }
        return mode;
    }

    // 离开游戏时停止背景音乐
    useEffect(() => () => stopMusic(), []);

    // 存档：调用后端收尾管线（蒸馏→誊写→归档→重置），完成后返回主菜单
    async function triggerSave() {
        try {
            const res = await fetch("http://localhost:5000/save", { method: "POST" });
            console.debug("[save]", await res.json());
        } catch {
            // 后端没起：忽略
        }
        onBackMenu();
    }

    // 放弃本轮：后端回滚玩家状态到本局开始 + 丢弃本局日志，然后回主菜单
    async function handleAbandon() {
        if (!window.confirm("放弃本轮？\n本局进度将被丢弃，玩家状态回滚到本局开始。")) return;
        try {
            await fetch("http://localhost:5000/abandon", { method: "POST" });
        } catch {
            // 后端没起：忽略
        }
        onBackMenu();
    }

    // WASD 移动停下 → 同步快照 + 记轨迹
    // （**不能用点击瞬移**：玩家只能一步步走；点地图仍可看 POI 信息，但不移动玩家）
    function handleExploreStop(p: { lon: number; lat: number }) {
        // 探索模式的迷雾改成「玩家附近的气泡」（见 GameMap focus），不再累计足迹
        setCursor(p);
    }

    //与后端的接口，拿到LLM的数据
    // mode: "action"=角色行动（IC）｜"gm"=玩家对主持人的场外话（OOC）
    async function sendAction(content: string, mode: "action" | "say" | "gm" | "continue", ke?: number) {
        const wasExplore = gameMode === "explore";
        const body: Record<string, unknown> =
            ke === undefined ? { input: content, mode } : { input: content, mode, ke };
        // 探索模式：带上光标坐标（当前 + 上一次）→ 后端更新位置并告知主持人「从哪到哪」
        const cur = cursorRef.current;
        if (wasExplore && cur) {
            body.坐标 = { lon: cur.lon, lat: cur.lat };
            const prev = prevCursorRef.current;
            if (prev) body.上一坐标 = { lon: prev.lon, lat: prev.lat };
            prevCursorRef.current = cur;
        }
        // 发请求前先冻住古钟（连网/等回复这段时间不计入游戏时间）
        setSending(true);
        try {
            const res = await fetch(
                "http://localhost:5000/action",
                {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify(body)
                }
            );

            const response: instruction[] = await res.json();

            // 统一事件流：大模型叙事（chat/narration）进对话，UI 事件走旁路
            const narrative = response.filter(
                (item): item is NarrativeLine => item.type === "chat" || item.type === "narration"
            );
            const uiEvents = response.filter(
                (item): item is UiEvent => item.type === "ui"
            );
            const uiMode = handleUiEvents(uiEvents);
            const base = historyRef.current.length;   // 本轮新增叙事在 history 中的起点
            setHistory(prev => [...prev, ...narrative]);
            // 目标模式：主持人裁定（mode 事件）优先；否则探索中输入 → 叙事，叙事中 → 保持叙事
            const nextMode: "explore" | "narrative" = uiMode ?? "narrative";
            setGameMode(nextMode);
            // 探索→叙事：让对话框直接跳到本轮叙事的第一句（而不是留在探索前的旧位置）
            if (nextMode === "narrative" && wasExplore && narrative.length) {
                setSceneStart(base);
            }
            // 回到探索时，本轮 GM 的叙事在地图上看不见 → 用浮层显示（#3）
            if (nextMode === "explore" && narrative.length) {
                setExploreLines(narrative);
                setExploreIdx(0);
            } else if (nextMode === "narrative") {
                setExploreLines([]);
                setExploreIdx(0);
            }

            // 行动会改状态，刷新菜单数值
            const s = await getState();
            applyState(s);
            // 「LLM 请求窗口」期间后端暂停了时钟 → 重新校准古钟插值，避免多算
            requestClockSync();
        } catch {
            // 后端没起 / 请求失败：静默
        } finally {
            setSending(false);
        }
    }

    // 开局拉一次状态
    useEffect(() => {
        const load = async () => {
            const s = await getState();
            applyState(s);
        };
        load();
    }, []);

    // 时钟倍率（移动速度随它缩放）
    useEffect(() => {
        fetchClock().then((a) => { if (a?.倍率) setClockRate(a.倍率); }).catch(() => { });
    }, []);

    // 进入探索模式：光标对齐后端已存的玩家位置
    useEffect(() => {
        if (gameMode !== "explore") return;
        let alive = true;
        fetch("http://localhost:5000/location")
            .then((r) => r.json())
            .then((d) => {
                if (!alive) return;
                if (typeof d.lon === "number" && typeof d.lat === "number") {
                    const p = { lon: d.lon, lat: d.lat };
                    cursorRef.current = p;
                    setCursor(p);
                    prevCursorRef.current = p;
                }
            })
            .catch(() => { /* 后端没起：忽略 */ });
        return () => { alive = false; };
    }, [gameMode]);

    // 拉势力画廊（GET /factions）；进入游戏时播放前情回顾选定的音乐
    useEffect(() => {
        fetchFactions().then(setFactions);
        if (initialMusic) playMusic(initialMusic);
    }, []);

    // 进入游戏：若本局未结束，续上（显示最后一幕），并载入历史面板
    useEffect(() => {
        const load = async () => {
            const h = await fetchHistory();
            if (!h) return;
            setHistoryLines(h.lines);
            if (h.active && h.tail.length > 0) {
                setHistory(h.tail);
                setGameMode("narrative");   // 续玩：先回到上一幕（叙事），而不是直接丢到地图
            }
        };
        load();
    }, []);

    // 预加载所有美术资源
    useEffect(() => {
        const load = async () => {
            await preloadImages(
                Object.values(images) as string[]
            );
            // 所有图片加载完成
            setLoaded(true);
        };
        load();
    }, []);

    //默认历史记录滚到最底部
    useEffect(() => {
        if (showHistory && historyBoxRef.current) {
            historyBoxRef.current.scrollTop = historyBoxRef.current.scrollHeight;
        }
    }, [showHistory]);

    //监听Esc键位从而关闭
    useEffect(() => {
        const handleKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                setShowHistory(false);
                setShowInputAct(false);
                setshowInputGM(false);
                setShowMap(false)
                setShowGallery(false)
                setShowData(false)
                setShowInputSay(false)
                setShowContinue(false)
                setReadingIndex(null)
            }
        };

        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, []);

    //判断是否预加载完成
    if (!loaded) {
        return (
            <div className="background">
                <GameScene history={[
                    {
                        type: "narration",
                        content: "请等待资源加载"
                    }
                ]} background={background} />
            </div>
        );
    }

    // 前情回顾：进入游戏后先放这段（主题曲已停，响起回顾选定的音乐）；点击推进，播完才进正常游戏
    if (recap && recap.length) {
        return (
            <div className="background">
                <GameScene
                    key="recap"
                    history={recap}
                    background={background}
                    onFinish={() => setRecap(null)}
                />
            </div>
        );
    }

    else {
        // 探索浮层当前要显示的一句（#3）
        const enLine = gameMode === "explore" && exploreLines.length
            ? exploreLines[Math.min(exploreIdx, exploreLines.length - 1)]
            : null;
        // 时钟暂停条件：打字（输入框）/ 看历史·地图·数据·势力·详情 / 等 LLM 回复
        const clockPaused =
            sending || showHistory || showMap || showData || showGallery ||
            readingIndex !== null || showInputGM || showInputAct || showInputSay;
        const 状态 = playerState?.状态 ?? {};        const 基础 = playerState?.属性?.基础属性 ?? {};
        const 物品 = playerState?.背包?.物品 ?? {};
        const 金钱 = playerState?.金钱?.金钱;

        const 金钱文本 = 金钱 == null ? "—" : `${金钱} 文`;
        const 背包文本 = Object.keys(物品).length
            ? Object.entries(物品)
                  .map(([名, item]) => `${名} ×${show(item.数量 ?? 1)}${item.类型 ? `（${item.类型}）` : ""}`)
                  .join(" · ")
            : "空";
        const 属性文本 = `体力 ${show(基础.体力)} · 内力 ${show(基础.内力)} · 剑法 ${show(基础.剑法)} · 轻功 ${show(基础.轻功)}`;
        const 状态文本 = `生命 ${show(状态.生命值)}/${show(状态.生命上限)} · 精力 ${show(状态.精力值)}/${show(状态.精力上限)} · 饥饿 ${show(状态.饥饿)} · 伤势 ${show(状态.伤势)}`;

        return (
            <div className="background">
                {/* 叙事层：探索模式 / 打开总览图时 display:none；可见时用 `contents`，
                    让包装层**不产生盒子**（嵌套 .background 的 16:9 布局才不被多出的一层破坏） */}
                <div style={{ display: (gameMode === "explore" || showMap) ? "none" : "contents" }}>
                    <GameScene key="game" history={history} background={background} startIndex={sceneStart} />
                </div>

                {/* 探索层：整屏 zoom18 地图，光标代表玩家 */}
                {gameMode === "explore" && (
                    <div className="explore-map">
                        <GameMap
                            isNight={isNight}
                            shichen={shichen}
                            zoom={18}
                            lockZoom
                            playerOverride={cursor}
                            focus={cursor}
                            wasd
                            posRef={cursorRef}
                            speedMps={BASE_WALK_MPS * clockRate}
                            runMult={RUN_MULT}
                            onPositionChange={handleExploreStop}
                        />
                    </div>
                )}

                <Clock paused={clockPaused} />

                {/* 探索模式的叙事浮层（#3）：GM 在「切回探索」时说的话也看得见 */}
                {enLine && (
                    <div
                        className="explore-narration"
                        onClick={() => {
                            if (exploreIdx < exploreLines.length - 1) setExploreIdx(exploreIdx + 1);
                            else { setExploreLines([]); setExploreIdx(0); }
                        }}
                    >
                        {enLine.type === "chat" && (
                            <div className="en-speaker">{enLine.speaker}</div>
                        )}
                        <div className="en-content">{enLine.content}</div>
                        <div className="en-hint">
                            {exploreIdx < exploreLines.length - 1
                                ? `▼ 点击继续（${exploreIdx + 1}/${exploreLines.length}）`
                                : "▼ 点击关闭"}
                        </div>
                    </div>
                )}

                {battleState && (
                    <BattleScene
                        initial={battleState}
                        onExit={() => { setBattleState(null); sendAction("", "continue", 0); }}
                    />
                )}

                {/* 地图（总览图）——常用，从菜单里拿出来常驻。再点一次可关闭 */}
                <button className="map-button" onClick={() => setShowMap(!showMap)}>
                    {showMap ? "关闭地图" : "地图"}
                </button>

                {gameMode === "narrative" && (
                    <button className="explore-button" onClick={() => sendAction("进入探索，请求GM同意", "gm")}>
                        探索
                    </button>
                )}

                <button className="chat-button" onClick={() => { setshowInputGM(!showInputGM); setShowInputAct(false); setShowInputSay(false); }}>
                    主持人
                </button>

                <button className="act-button" onClick={() => { setShowInputAct(!showInputAct); setshowInputGM(false); setShowInputSay(false); }}>
                    行动
                </button>

                <button className="say-button" onClick={() => { setShowInputSay(!showInputSay); setShowInputAct(false); setshowInputGM(false); }}>
                    说话
                </button>

                <button className="continue-button" onClick={() => setShowContinue(!showContinue)}>
                    继续
                </button>

                {showContinue && (
                    <div className="continue-panel">
                        {[0, 1, 2, 3, 4].map((k) => (
                            <button
                                key={k}
                                className="continue-opt"
                                title={k === 0 ? "不推进时间，只看更多场景信息" : `推进 ${k} 刻（约 ${k * 15} 分钟）`}
                                onClick={() => { sendAction("", "continue", k); setShowContinue(false); }}
                            >
                                {k === 0 ? "0刻" : `${k}刻`}
                            </button>
                        ))}
                    </div>
                )}

                <button className="history-button" onClick={async () => {
                    if (!showHistory) {
                        const h = await fetchHistory();
                        if (h) setHistoryLines(h.lines);
                    }
                    setShowHistory(!showHistory);
                }}>
                    历史记录
                </button>

                <button className="data-button" onClick={() => setShowData(!showData)}>
                    数据
                </button>

                {
                showMap && (
                    <div className="game-map">
                        {/* 菜单地图 = 总览图：不启用探索迷雾，全部 POI 都画出来 */}
                        <GameMap isNight={isNight} shichen={shichen} showAllIcons />
                        <button className="map-close" onClick={() => setShowMap(false)}>返回</button>
                    </div>
                )
                }

                {
                showGallery && (
                    <div className="gallery-overlay">
                        <div className="gallery-rows">
                            {galleryRows.map((row, ri) => (
                                <AccordionGallery
                                    key={ri}
                                    items={row}
                                    defaultIndex={0}
                                    accentColor="#d8b45a"
                                    overlayColor="#1a0f08"
                                    textColor="#f5efe0"
                                    trigger="hover"
                                    tilt={4}
                                    parallax={0.3}
                                    onItemClick={(i) => setReadingIndex(ri * GALLERY_ROW_SIZE + i)}
                                />
                            ))}
                        </div>
                    </div>
                )
                }

                {
                readingIndex !== null && (
                    <div className="gallery-reader">
                        <img
                            className="reader-bg"
                            src={galleryItems[readingIndex].image}
                            alt=""
                            draggable={false}
                        />
                        <div className="reader-scrim" />
                        <div className="reader-inner">
                            <h2 className="reader-title">{galleryItems[readingIndex].label}</h2>
                            <div className="reader-text">
                                {galleryItems[readingIndex].detail || galleryItems[readingIndex].description}
                            </div>
                        </div>
                        <button className="gallery-close" onClick={() => setReadingIndex(null)}>
                            返回
                        </button>
                    </div>
                )
                }

                {
                showData && (
                    <div className="data-box">
                        <section className="sm-stat-block">
                            <h3 className="sm-stat-title">金钱</h3>
                            <div className="sm-stat-body">{金钱文本}</div>
                        </section>
                        <section className="sm-stat-block">
                            <h3 className="sm-stat-title">背包</h3>
                            <div className="sm-stat-body">{背包文本}</div>
                        </section>
                        <section className="sm-stat-block">
                            <h3 className="sm-stat-title">属性</h3>
                            <div className="sm-stat-body">{属性文本}</div>
                        </section>
                        <section className="sm-stat-block">
                            <h3 className="sm-stat-title">状态</h3>
                            <div className="sm-stat-body">{状态文本}</div>
                        </section>
                    </div>
                )
                }

                <StaggeredMenu position="left" menuLabel="菜单" accentColor="#c0392b" closeOnContentClick>
                    <button className="sm-menu-item" onClick={triggerSave}>存档游戏</button>
                    <button className="sm-menu-item" onClick={handleAbandon}>放弃本轮</button>
                    <button className="sm-menu-item" onClick={() => setShowGallery(true)}>势力</button>
                    <button className="sm-menu-item" onClick={onBackMenu}>返回主菜单</button>
                </StaggeredMenu>

                {
                showInputAct &&
                <textarea
                    className="dialog-box"
                    placeholder="行动：梁峰要做什么…"
                    autoFocus
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => {
                        if (e.key === "Enter") {
                            sendAction(input, "action");
                            setInput("");
                            setShowInputAct(!showInputAct)
                        }
                    }}

                />
                }

                {
                    showInputSay &&
                    <textarea
                        className="dialog-box"
                        placeholder="梁峰对在场的人说…（台词；NPC 会回应）"
                        autoFocus
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === "Enter") {
                                sendAction(input, "say");
                                setInput("");
                                setShowInputSay(false);
                            }
                        }}
                    />
                }

                {
                    showInputGM &&
                    <textarea
                        className="dialog-box"
                        placeholder="对主持人说（场外）…"
                        autoFocus
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === "Enter") {
                                sendAction(input, "gm");
                                setInput("");
                                setshowInputGM(!showInputGM)
                            }
                        }}

                    />
                }

                {showHistory && (
                    <div className="history-box">
                        <div className="history-log-content" ref={historyBoxRef}>
                            {historyLines.map((item, index) => (
                                <div key={index}>
                                    <span className="log-name">
                                        {item.slice(0, item.indexOf("：") + 1)}
                                    </span>
                                    {item.slice(item.indexOf("：") + 1)}
                                </div>
                            ))}
                        </div>
                    </div>
                )}
            </div>
        );
    }

}

export default Gaming;