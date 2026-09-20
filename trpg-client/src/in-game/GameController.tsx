import GameScene from "./GameScene";
import "../styles/GameController.css"
import "../styles/Background.css"
import { useEffect, useMemo, useRef, useState } from "react";
import type { instruction } from "../types/gametype";
import preloadImages from "./PreloadImages";
import GameMap from "./Map"
import WeatherLayer from "./WeatherLayer";
import { StaggeredMenu } from "./Staggered Menu";
import AccordionGallery, { type AccordionGalleryItem } from "./AccordionGallery";
import { 默认背景, getBackgroundImage, periodOfShichen } from "./background";
import { playMusic, popUiMusic, pushUiMusic, stopMusic } from "./music";
import BattleScene, { type BattleState } from "./battle";
import Clock from "./Clock";
import { fetchClock, requestClockSync, useWorldTime } from "./useGameClock";
import { MAP_ID } from "./mapId";
import { API } from "../api";
import { useEsc } from "../escStack";
import FacilityPanel, { type FacilityDetail } from "./FacilityPanel";
import SkillTree from "./SkillTree";

// 地图条目（GET /maps）：frame = [min_lon, min_lat, max_lon, max_lat]
type MapEntry = { id: string; name: string; frame: number[] | null };
// GET /search 的命中项（跨城市搜地点）
type SearchHit = {
    map_id: string; 地图: string; 名称: string; 类型: string;
    lon: number | null; lat: number | null;
};

/** 画框 → Leaflet maxBounds（注意 [lat, lon] 顺序） */
function frameBounds(frame?: number[] | null) {
    if (!frame || frame.length !== 4) return undefined;
    return [[frame[1], frame[0]], [frame[3], frame[2]]] as
        [[number, number], [number, number]];
}

/** 画框 → 中心点 */
function frameCenter(frame?: number[] | null): [number, number] | undefined {
    if (!frame || frame.length !== 4) return undefined;
    return [(frame[1] + frame[3]) / 2, (frame[0] + frame[2]) / 2];
}

// 游戏内步速（米/游戏秒）——真实速度 = 步速 × 时钟倍率，
// 这样「游戏内移动速度」与时间保持一致（时间快 15 倍 → 标记也快 15 倍地跑）。
//
// 1.4 是真实步行速度，但在这个地图尺度下显得捷（太拖）；
// 调到 2.2（快走），再配合 Shift 奔跑。
const BASE_WALK_MPS = 2.2;

// 按住 Shift 的速度倍数（跑）：2.6 × 2.2 ≈ 5.7 米/游戏秒，接近冲刺
const RUN_MULT = 2.6;

// ---- 「详细」设施背景：先把图加载好再开面板，避免先黑一下 / 先显旧背景 ----
/** 预加载单张图（带超时兜底）；加载失败/超时返回 false。 */
function preloadOne(url: string, timeoutMs = 4000): Promise<boolean> {
    return new Promise((resolve) => {
        const im = new Image();
        im.onload = () => resolve(true);
        im.onerror = () => resolve(false);
        setTimeout(() => resolve(false), timeoutMs);
        im.src = url;
    });
}

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
    // 移动参数（后端 移动.json 下发）：轻功→步速 / 奔跑倍率
    移动?: { 基础步速?: number; 轻功每点步速?: number; 奔跑倍率?: number };
};

type UiEvent = Extract<instruction, { type: "ui" }>;
type NarrativeLine = Extract<instruction, { type: "chat" } | { type: "narration" }>;
// 地点「回忆」结果
 type RecallInfo = {
    place: string;
    memories: { content: string; time?: string }[];
};

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
    const lastTurnBaseRef = useRef(0); // 上一轮叙事在 history 中的起点（驳回时替换用）
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
    const [showSkillTree, setShowSkillTree] = useState(false); // 技能树（银河 + 五星圆弧，零大模型）
    const [readingIndex, setReadingIndex] = useState<number | null>(null);
    const [playerState, setPlayerState] = useState<PlayerState | null>(null); // 玩家真实状态
    const [background, setBackground] = useState<string>(
        initialBg?.position ? getBackgroundImage(initialBg.position, initialBg.time ?? "") : 默认背景
    ); // 当前背景（由 UI 事件控制）
    // 当前背景图对应的**场景名**（如「城市大街」）。
    // 白天/黄昏/黑夜是**时间的函数**，所以只记场景，时段到了自己重算——
    // 否则「睡到早上但地点没变」时小模型按规则答「无」、不发 bg 事件，背景会一直停在夜里。
    const [bgPosition, setBgPosition] = useState<string>(initialBg?.position ?? "");
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
    const [recallInfo, setRecallInfo] = useState<RecallInfo | null>(null);   // 地点回忆面板
    const [facilityInfo, setFacilityInfo] = useState<{ place: string; detail: FacilityDetail } | null>(null);  // 基础设施「详细」界面
    const [facilityBusy, setFacilityBusy] = useState(false);       // 「详细」页已选活动、等主持人回应中
    const [facilityLeaving, setFacilityLeaving] = useState(false); // 回应到 → 淡出「详细」页、露出叙事
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
    const [saving, setSaving] = useState(false);                              // 存档进行中（蒸馏可能 1~3 分钟）
    const { isNight, shichen } = useWorldTime();                            // 昼夜 + 时辰：地图夜色 + 打烊不亮灯

    // 统一处理 /state 返回：更新状态
    function applyState(s: PlayerState | null) {
        if (!s) return;
        setPlayerState(s);
    }

    // 探索奔跑结算：把「超出步行的距离（米）」交给后端扣精力（返回新状态）
    async function handleRun(meters: number) {
        if (!(meters > 0)) return;
        try {
            const res = await fetch("http://localhost:5000/run", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ 奔跑米: meters }),
            });
            if (res.ok) applyState((await res.json()) as PlayerState);
        } catch { /* 后端没起：忽略 */ }
    }

    // UI 事件旁路：kind:"bg" 切背景；kind:"music" 切音乐；kind:"mode" 返回给调用方定模式
    function handleUiEvents(events: UiEvent[]): "explore" | "narrative" | null {
        let mode: "explore" | "narrative" | null = null;
        for (const ev of events) {
            if (ev.kind === "bg") {
                // 只认非空场景名：小模型「拿不准」时可能给空/无，
                // 那不该把背景重新打回主页图。
                const pos = String(ev.data.position ?? "");
                const tm = String(ev.data.time ?? "");
                if (pos) {
                    setBgPosition(pos);
                    setBackground(getBackgroundImage(pos, tm));
                }
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

    // 点击 POI 弹窗的动作：详细（设施界面）/ 观察（留探索）/ 回忆（RAG Top2）
    async function handlePlaceAction(place: string, act: string, kind?: string) {
        if (!place) return;
        if (act === "detail") {
            // 「详细」：**一次 fetch** 拿到选项 + 背景（后端确定性映射，不调模型）。
            const qs = `kind=${encodeURIComponent(kind || "")}&name=${encodeURIComponent(place)}`;
            let detail: FacilityDetail;
            try {
                const d = (await (await fetch(`${API}/facility?${qs}`)).json()) as FacilityDetail;
                detail = (d?.success && (d.选项?.length || 0) > 0) ? d : {
                    success: true, 名称: place,
                    选项: [{ 标签: "进入", 类型: "自由", 介绍: "进入此处看看。", 图标: "free", 意图: "" }],
                };
            } catch {
                detail = {
                    success: true, 名称: place,
                    选项: [{ 标签: "进入", 类型: "自由", 介绍: "进入此处看看。", 图标: "free", 意图: "" }],
                };
            }
            // 背景图先加载好再开面板（避免先黑 / 先显旧背景）；后端已给 `背景`，无需再问小模型。
            const bgUrl = detail.背景
                ? getBackgroundImage(detail.背景, periodOfShichen(shichen))
                : background;
            if (bgUrl) await preloadOne(bgUrl);
            setFacilityInfo({ place, detail });
        } else if (act === "observe") {
            sendAction(place, "observe", undefined, true);
        } else if (act === "recall") {
            try {
                const r = await fetch(`http://localhost:5000/recall?place=${encodeURIComponent(place)}`);
                const d = await r.json();
                setRecallInfo({ place, memories: d.memories || [] });
            } catch {
                setRecallInfo({ place, memories: [] });
            }
        }
    }

    // 离开游戏时停止背景音乐
    useEffect(() => () => stopMusic(), []);

    // 技能树 BGM：开面板换《技能树》，关掉后恢复原曲（之前没在放就停掉）
    useEffect(() => {
        if (showSkillTree) pushUiMusic("技能树");
        else popUiMusic();
    }, [showSkillTree]);

    // 存档：调用后端收尾管线（蒸馏→誊写→归档→重置），完成后返回主菜单
    async function triggerSave() {
        console.info("[save] 点击“存档游戏”，saving=", saving);
        if (saving) return;
        setSaving(true);
        try {
            const ctrl = new AbortController();
            const timer = setTimeout(() => ctrl.abort(), 300000);   // 5 分钟上限
            console.info("[save] → POST http://localhost:5000/save");
            const res = await fetch("http://localhost:5000/save", { method: "POST", signal: ctrl.signal });
            clearTimeout(timer);
            const data = await res.json().catch(() => ({}));
            console.info("[save] ← HTTP", res.status, data);
            if (!res.ok || data.success === false) {
                setSaving(false);
                window.alert("存档失败：" + (data.error || res.status) + "\n本局未清空，可稍后再点一次存档。");
                return;
            }
        } catch (e) {
            console.warn("[save] 失败/超时", e);
            setSaving(false);
            window.alert("存档超时/失败（后端可能仍在忙）。\n本局未清空，可稍后再点一次存档。");
            return;
        }
        setSaving(false);
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

    // 驳回上轮：后端回滚到本轮开始前、用同一输入重发 → 前端**替换**上一轮叙事（不是追加）
    async function handleReject() {
        if (sending) return;
        setSending(true);
        try {
            const res = await fetch("http://localhost:5000/reject", { method: "POST" });
            const response: instruction[] = await res.json();
            const narrative = response.filter(
                (item): item is NarrativeLine => item.type === "chat" || item.type === "narration"
            );
            const uiEvents = response.filter(
                (item): item is UiEvent => item.type === "ui"
            );
            handleUiEvents(uiEvents);
            const base = lastTurnBaseRef.current;
            setHistory(prev => [...prev.slice(0, base), ...narrative]);
            if (narrative.length) setSceneStart(base);
            const s = await getState();
            applyState(s);
            requestClockSync();
        } catch {
            // 后端没起 / 请求失败：静默
        } finally {
            setSending(false);
        }
    }

    // WASD 移动停下 → 同步快照 + 记轨迹
    // （**不能用点击瞬移**：玩家只能一步步走；点地图仍可看 POI 信息，但不移动玩家）
    function handleExploreStop(p: { lon: number; lat: number }) {
        // 探索模式的迷雾改成「玩家附近的气泡」（见 GameMap focus），不再累计足迹
        setCursor(p);
    }

    //与后端的接口，拿到LLM的数据
    // mode: "action"=角色行动（IC）｜"gm"=玩家对主持人的场外话（OOC）
    async function sendAction(content: string, mode: "action" | "say" | "gm" | "continue" | "observe", ke?: number, keepExplore = false) {
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
            lastTurnBaseRef.current = base;
            setHistory(prev => [...prev, ...narrative]);
            // 目标模式：主持人裁定（mode 事件）优先；否则探索中输入 → 叙事，叙事中 → 保持叙事
            // 硬约束：**探索模式下只有「行动 / 台词」能进入叙事**；
            // 场外话（gm）/「继续」/观察 都留在探索（回复走探索浮层）
            const switchesToNarrative = mode === "action" || mode === "say";
            const nextMode: "explore" | "narrative" = keepExplore
                ? "explore"
                : (uiMode ?? (wasExplore && !switchesToNarrative ? "explore" : "narrative"));
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

    // （城门已改为「点开→出城/入城」由大模型移动；行走不再穿门，故不再需要同步时辰）

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

    // 进游戏时的初始背景：若前情回顾没给，就按**玩家当前地点**取一个（不用等第一轮叙事）。
    // 后端 GET /scene 给场景名，时分由它一并返回的时辰决定（白天/黄昏/黑夜）。
    useEffect(() => {
        if (initialBg?.position) return;   // 前情回顾已经带了最后一幕
        (async () => {
            try {
                const d = await (await fetch(`${API}/scene`)).json();
                if (d?.场景) {
                    setBgPosition(d.场景);
                    setBackground(getBackgroundImage(d.场景, d.时辰 ?? ""));
                }
            } catch { /* 后端没起：继续用主页面 */ }
        })();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // 时段变化（白天/黄昏/黑夜）→ 用**当前场景名**重算背景。
    // 睡到早上、时间跳跃、跨时辰都由它接管，不依赖大/小模型发 bg 事件。
    const period = periodOfShichen(shichen);
    useEffect(() => {
        if (!bgPosition) return;
        setBackground(getBackgroundImage(bgPosition, period));
    }, [period, bgPosition]);

    // ---- 地图（多城市）----
    // playerCity 由**玩家坐标 + 各图画框现算**（与后端同一套规则）→ 探索地图用它；
    // viewCity   = 菜单里那张总览图在看哪座城 → 纯查看，可自由搜/切，零副作用。
    const [maps, setMaps] = useState<MapEntry[]>([]);
    const [mapsReady, setMapsReady] = useState(false);
    const [viewCity, setViewCity] = useState<string>(MAP_ID);
    const [flyTo, setFlyTo] = useState<{ lon: number; lat: number; key: number } | null>(null);
    useEffect(() => {
        (async () => {
            try {
                const d = await (await fetch(`${API}/maps`)).json();
                if (Array.isArray(d?.maps) && d.maps.length) setMaps(d.maps);
            } catch { /* 后端没起：用默认 */ }
            finally { setMapsReady(true); }
        })();
    }, []);

    const mapOf = (id: string) => maps.find((m) => m.id === id);

    // 玩家在哪张图里：坐标落在谁家画框内就是谁。
    // 这样跨城移动后探索地图会自动跟着换；否则会出现
    // 「地图中心在岳阳、maxBounds 还是扬州」→ 瓦片全白。
    const playerCity = useMemo(() => {
        if (cursor && maps.length) {
            for (const m of maps) {
                const f = m.frame;
                if (f && cursor.lon >= f[0] && cursor.lon <= f[2]
                    && cursor.lat >= f[1] && cursor.lat <= f[3]) {
                    return m.id;
                }
            }
        }
        return MAP_ID;
    }, [cursor, maps]);

    // 探索地图的活动范围（按玩家所在城，别让走动坐标被夹到别的城）
    const exploreBounds = useMemo(
        () => frameBounds(mapOf(playerCity)?.frame), [playerCity, maps]);

    // ---- 地图搜索（跨城市：搜地点名或城市名，命中即切图 + 飞过去）----
    const [searchQ, setSearchQ] = useState("");
    const [searchRes, setSearchRes] = useState<SearchHit[]>([]);
    const [searchBusy, setSearchBusy] = useState(false);
    const [searchDone, setSearchDone] = useState(false);

    async function 搜地点(qRaw: string): Promise<SearchHit[]> {
        const q = qRaw.trim();
        if (!q) { setSearchRes([]); setSearchDone(false); return []; }
        setSearchBusy(true);
        try {
            const d = await (await fetch(`${API}/search?q=${encodeURIComponent(q)}`)).json();
            const rs: SearchHit[] = Array.isArray(d?.results) ? d.results : [];
            setSearchRes(rs);
            setSearchDone(true);
            return rs;
        } catch {
            setSearchRes([]);
            setSearchDone(true);
            return [];
        } finally {
            setSearchBusy(false);
        }
    }

    // 打字防抖（回车时会立即再搜一次，不等这 180ms）
    useEffect(() => {
        if (!showMap) return;
        const q = searchQ.trim();
        if (!q) { setSearchRes([]); setSearchDone(false); return; }
        const t = setTimeout(() => { 搜地点(q); }, 180);
        return () => clearTimeout(t);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [searchQ, showMap]);

    function 跳转地图(r: SearchHit) {
        setViewCity(r.map_id);
        if (r.lon != null && r.lat != null) {
            setFlyTo({ lon: r.lon, lat: r.lat, key: Date.now() });
        }
        setSearchRes([]);
        setSearchDone(false);
        setSearchQ(r.名称);
    }

    /** 回车：有结果就跳第一条；还没搜（或结果为空）就立即搜一次再跳 */
    async function 回车跳转() {
        if (searchRes.length) { 跳转地图(searchRes[0]); return; }
        const rs = await 搜地点(searchQ);
        if (rs.length) 跳转地图(rs[0]);
    }

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

    // Esc：层级退栈（最后打开的先退，见 escStack.ts）——不再一次性全关
    useEsc(() => setShowHistory(false), showHistory);
    useEsc(() => setShowInputAct(false), showInputAct);
    useEsc(() => setshowInputGM(false), showInputGM);
    useEsc(() => setShowMap(false), showMap);
    useEsc(() => setShowGallery(false), showGallery);
    useEsc(() => setShowData(false), showData);
    useEsc(() => setShowInputSay(false), showInputSay);
    useEsc(() => setShowContinue(false), showContinue);
    useEsc(() => setRecallInfo(null), recallInfo !== null);
    useEsc(() => setReadingIndex(null), readingIndex !== null);

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
            sending || showHistory || showMap || showData || showGallery || showSkillTree ||
            readingIndex !== null || showInputGM || showInputAct || showInputSay;
        const 状态 = playerState?.状态 ?? {};        const 基础 = playerState?.属性?.基础属性 ?? {};
        const 物品 = playerState?.背包?.物品 ?? {};
        const 金钱 = playerState?.金钱?.金钱;
        // 天气（探索层动效用）：基本信息.天气.状况
        const 天气状况 = (((playerState?.基本信息 ?? {}) as Record<string, unknown>)["天气"] as { 状况?: string } | undefined)?.状况 ?? "";
        // 移动：轻功→步速、奔跑倍率（参数由后端 移动.json 下发）
        const 轻功 = Number(基础.轻功 ?? 0) || 0;
        const 移动 = playerState?.移动 ?? {};
        const 步速 = (移动.基础步速 ?? BASE_WALK_MPS) * (1 + 轻功 * (移动.轻功每点步速 ?? 0.005));
        const 奔跑倍率 = 移动.奔跑倍率 ?? RUN_MULT;

        const 金钱文本 = 金钱 == null ? "—" : `${金钱} 文`;
        const 背包文本 = Object.keys(物品).length
            ? Object.entries(物品)
                  .map(([名, item]) => `${名} ×${show(item.数量 ?? 1)}${item.类型 ? `（${item.类型}）` : ""}`)
                  .join(" · ")
            : "空";
        const 属性文本 = `体力 ${show(基础.体力)} · 内力 ${show(基础.内力)} · 剑法 ${show(基础.剑法)} · 轻功 ${show(基础.轻功)}`;
        const 状态文本 = `生命 ${show(状态.生命值)}/${show(状态.生命上限)} · 精力 ${show(状态.精力值)}/${show(状态.精力上限)} · 饥饿 ${show(状态.饥饿)}/100（${show(状态.饥饿挡位)}）`;

        return (
            <div className="background">
                {/* 叙事层：探索模式 / 打开总览图时 display:none；可见时用 `contents`，
                    让包装层**不产生盒子**（嵌套 .background 的 16:9 布局才不被多出的一层破坏） */}
                <div style={{ display: (gameMode === "explore" || showMap) ? "none" : "contents" }}>
                    <GameScene key="game" history={history} background={background} startIndex={sceneStart} />
                </div>

                {/* 探索层：整屏 zoom18 地图，光标代表玩家。
                    等 /maps 回来再挂载：否则首次挂载可能拿不到画框 → maxBounds 用扬州默认值，
                    而玩家在岳阳 → 视野被夹到扬州外，一片空。 */}
                {gameMode === "explore" && mapsReady && (
                    <div className="explore-map">
                        <GameMap
                            isNight={isNight}
                            shichen={shichen}
                            zoom={18}
                            lockZoom
                            mapId={playerCity}
                            bounds={exploreBounds}
                            center={frameCenter(mapOf(playerCity)?.frame)}
                            playerOverride={cursor}
                            focus={cursor}
                            wasd
                            posRef={cursorRef}
                            speedMps={步速 * clockRate}
                            runMult={奔跑倍率}
                            onRun={handleRun}
                            onPlaceAction={handlePlaceAction}
                            onPositionChange={handleExploreStop}
                        />
                        <WeatherLayer weather={天气状况} isNight={isNight} />
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
                <button className="map-button" onClick={() => {
                    if (!showMap) { setViewCity(playerCity); setSearchQ(""); setSearchRes([]); }
                    setShowMap(!showMap);
                }}>
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
                showMap && mapsReady && (
                    <div className="game-map">
                        {/* 菜单地图 = 总览图：**按已探索足迹启用迷雾**（只显示去过的区域，未探索的 POI 不可见/不可点）；
                            **不带进入/观察/回忆按钮**。它只是「看」，可以自由搜/切城市——不会动玩家坐标（游戏城市由坐标决定）。 */}
                        <GameMap isNight={isNight} shichen={shichen}
                            mapId={viewCity}
                            bounds={frameBounds(mapOf(viewCity)?.frame)}
                            center={frameCenter(mapOf(viewCity)?.frame)}
                            hidePlayer={viewCity !== playerCity}
                            flyTo={flyTo} />

                        {/* 搜索：搜城市或地点，回车/点击即切图并飞过去（多城市也只需这一处） */}
                        <div className="map-search">
                            <input
                                className="map-search-input"
                                value={searchQ}
                                placeholder="搜索地点 / 城市，回车跳转（如：锦香宫、岳阳楼）"
                                onChange={(e) => setSearchQ(e.target.value)}
                                onKeyDown={(e) => {
                                    if (e.key === "Enter") { e.preventDefault(); 回车跳转(); }
                                    if (e.key === "Escape") { e.stopPropagation(); setSearchRes([]); setSearchDone(false); }
                                }}
                            />
                            {searchRes.length > 0 && (
                                <div className="map-search-results">
                                    {searchRes.map((r, i) => (
                                        <button key={`${r.map_id}-${r.名称}-${i}`}
                                            className={"map-search-hit" + (i === 0 ? " first" : "")}
                                            onClick={() => 跳转地图(r)}>
                                            <span className="hit-name">{r.名称}</span>
                                            {r.类型 && <span className="hit-kind">{r.类型}</span>}
                                            <span className="hit-city">{r.地图}</span>
                                        </button>
                                    ))}
                                </div>
                            )}
                            {searchDone && !searchBusy && searchRes.length === 0 && searchQ.trim() && (
                                <div className="map-search-empty">没有找到「{searchQ.trim()}」</div>
                            )}
                        </div>

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

                {showSkillTree && <SkillTree onClose={() => setShowSkillTree(false)} />}

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
                    <div className="data-box">                        <section className="sm-stat-block">
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

                {recallInfo && (
                    <div className="recall-panel">
                        <div className="recall-title">回忆 · {recallInfo.place}</div>
                        <div className="recall-body">
                            {recallInfo.memories.map((m, i) => (
                                <div className="recall-item" key={`m${i}`}>
                                    {m.time && <span className="recall-time">{m.time}</span>}
                                    {m.content}
                                </div>
                            ))}
                            {!recallInfo.memories.length && (
                                <div className="recall-empty">（对此地毫无印象）</div>
                            )}
                        </div>
                        <button className="recall-close" onClick={() => setRecallInfo(null)}>关闭</button>
                    </div>
                )}

                {facilityInfo && (
                    <FacilityPanel
                        place={facilityInfo.place}
                        detail={facilityInfo.detail}
                        busy={facilityBusy}
                        leaving={facilityLeaving}
                        bgImage={facilityInfo.detail.背景
                            ? getBackgroundImage(facilityInfo.detail.背景, periodOfShichen(shichen))
                            : background}
                        onChoose={async (text) => {
                            // 保持「详细」页，等主持人回应再淡出 —— 不先跳回探索地图。
                            setFacilityBusy(true);
                            // 先把叙事背景沿用本页所选场景：淡出时下面已是同一张图，过渡无缝。
                            if (facilityInfo.detail.背景) {
                                setBgPosition(facilityInfo.detail.背景);
                                setBackground(getBackgroundImage(
                                    facilityInfo.detail.背景, periodOfShichen(shichen)));
                            }
                            await sendAction(text, "action");
                            setFacilityLeaving(true);          // 触发淡出（500ms，与 CSS 一致）
                            window.setTimeout(() => {
                                setFacilityInfo(null);
                                setFacilityLeaving(false);
                                setFacilityBusy(false);
                            }, 500);
                        }}
                        onClose={() => setFacilityInfo(null)}
                    />
                )}

                {saving && (
                    <div className="save-overlay">
                        <div className="save-box">
                            正在存档…
                            <small>把本局蒸馏进长期记忆（gm_memory / 档案 / 见闻 / 建筑结构），可能需 1~3 分钟，请勿关闭</small>
                        </div>
                    </div>
                )}

                <StaggeredMenu position="left" menuLabel="菜单" accentColor="#c0392b" closeOnContentClick>
                    <button className="sm-menu-item" onClick={triggerSave}>存档游戏</button>
                    <button className="sm-menu-item" onClick={handleAbandon}>放弃本轮</button>
                    <button className="sm-menu-item" onClick={handleReject}>驳回上轮</button>
                    <button className="sm-menu-item" onClick={() => setShowGallery(true)}>势力</button>
                    <button className="sm-menu-item" onClick={() => setShowSkillTree(true)}>技能树</button>
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