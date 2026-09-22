import { useEffect, useRef, useState } from "react";
import Ziye_Jijunshu from "../assets/音乐/固定/子夜寄君书.mp3";
import "../styles/menu.css";
import bg from "../assets/背景_重构/主页面.png";
import "../styles/Background.css";
import GooseAnimation from "./GooseAnimation";
import MoveLogo from "./Logo";
import type { instruction } from "../types/gametype";
import BattleScene, { type BattleState } from "../in-game/battle";
import { MAP_ID, rememberMap } from "../in-game/mapId";
import { useEsc } from "../escStack";
import { API } from "../api";

// 模拟战斗可选名单条目
type Roster = { 名字: string; 梯度: string };

// 进游戏时一并带进去的数据（前情回顾段落 + 最后一幕 bg/音乐）
export type StartData = {
    segments?: instruction[];
    bg?: { position?: string; time?: string } | null;
    music?: string | null;
} | null;

type MenuProps = {
    onStartGame: (start?: StartData) => void;
};

function Menu({ onStartGame }: MenuProps) {
    //音乐预处理
    const [showSetting, setshowSetting] = useState(false);
    const audioRef = useRef<HTMLAudioElement>(null);
    useEffect(() => {
        audioRef.current?.play();
    }, []);

    // 点“继续旅途”：主页面加载（主题曲继续放）→ 拉前情回顾；拿到后直接进游戏
    // （前情提要在 in game 里播放，不在这里渲染）
    const [loading, setLoading] = useState(false);

    async function 继续旅途() {
        setLoading(true);
        try {
            const res = await fetch(`${API}/recap`);
            const data = await res.json();
            if (data?.has_recap && data.segments?.length) {
                onStartGame({ segments: data.segments, bg: data.bg, music: data.music });
            } else {
                onStartGame(null); // 无存档：跳过回顾，直接进游戏
            }
        } catch {
            onStartGame(null); // 后端没起/出错：不阻断，直接进游戏
        }
    }

    // ---- 环境设定：难度（存 游戏数据/设置.json，每轮发给 LLM）----
    const [difficulty, setDifficulty] = useState("普通");
    const [difficultyOptions, setDifficultyOptions] = useState<string[]>(["轻松", "普通", "困难", "硬核"]);

    useEffect(() => {
        if (!showSetting) return;
        (async () => {
            try {
                const s = await (await fetch(`${API}/settings`)).json();
                if (s?.难度) setDifficulty(s.难度);
                if (Array.isArray(s?.可选难度) && s.可选难度.length) setDifficultyOptions(s.可选难度);
            } catch { /* 后端没起：用默认 */ }
        })();
    }, [showSetting]);

    async function 选难度(d: string) {
        setDifficulty(d);
        try {
            await fetch(`${API}/settings`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ 难度: d }),
            });
        } catch { /* 后端没起：忽略 */ }
    }

    // ---- 环境设定：地图（多城市；写后端 游戏数据/地图设置.json，然后带 ?map= 重载）----
    const [maps, setMaps] = useState<{ id: string; name: string }[]>([]);
    const [curMap, setCurMap] = useState<string>(MAP_ID);

    useEffect(() => {
        if (!showSetting) return;
        (async () => {
            try {
                const d = await (await fetch(`${API}/maps`)).json();
                if (Array.isArray(d?.maps) && d.maps.length) setMaps(d.maps);
                if (d?.current) setCurMap(d.current);
            } catch { /* 后端没起：忽略 */ }
        })();
    }, [showSetting]);

    async function 选地图(id: string) {
        if (id === curMap) return;
        // 换的只是“看哪张图”（瓦片/点击层），**不会动玩家坐标**——
        // 游戏城市由玩家坐标决定（后端 map_settings.get_map），所以无需确认。
        setCurMap(id);
        rememberMap(id);
        try {
            await fetch(`${API}/map`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ 地图: id }),
            });
        } catch { /* 后端没起：至少前端本地切了 */ }
        // 换整张地图 → 重载页面（瓦片/点击层/碰撞层都按 ?map= 取）
        const q = new URLSearchParams(window.location.search);
        q.set("map", id);
        window.location.replace(`${window.location.pathname}?${q.toString()}`);
    }

    // ---- 环境设定：模拟战斗（直接测战斗系统，不动真实存档）----
    const [roster, setRoster] = useState<Roster[]>([]);
    const [sim友, setSim友] = useState<string[]>([]);
    const [sim敌, setSim敌] = useState<string[]>([]);
    const [simState, setSimState] = useState<BattleState | null>(null);
    const [simBusy, setSimBusy] = useState(false);

    useEffect(() => {
        if (!showSetting || roster.length) return;
        (async () => {
            try {
                const d = await (await fetch(`${API}/battle/roster`)).json();
                if (Array.isArray(d?.角色)) setRoster(d.角色);
            } catch { /* 后端没起：忽略 */ }
        })();
    }, [showSetting, roster.length]);

    function 切换参战(side: "友" | "敌", name: string) {
        if (side === "友") {
            setSim友((p) => p.includes(name) ? p.filter((x) => x !== name) : [...p, name]);
            setSim敌((p) => p.filter((x) => x !== name));
        } else {
            setSim敌((p) => p.includes(name) ? p.filter((x) => x !== name) : [...p, name]);
            setSim友((p) => p.filter((x) => x !== name));
        }
    }

    async function 开始模拟() {
        if (simBusy || !sim敌.length) return;
        setSimBusy(true);
        try {
            const st = await (await fetch(`${API}/battle/sim`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ 友方: sim友, 敌人: sim敌, 缘由: "模拟战斗" }),
            })).json();
            if (st?.active) {
                audioRef.current?.pause();   // 暂停主页面主题曲
                setSimState(st);
                setshowSetting(false);
            }
        } catch { /* 后端没起：忽略 */ } finally { setSimBusy(false); }
    }

    function 退出模拟() {
        setSimState(null);
        audioRef.current?.play();        // 恢复主页面主题曲
        fetch(`${API}/battle/abort`, { method: "POST" }).catch(() => { });
    }

    // ---- 归隐山林：直接退出 ----
    const [quit, setQuit] = useState(false);
    function 归隐山林() {
        audioRef.current?.pause();
        window.close();      // 脚本打开的窗口会真关闭
        setQuit(true);       // 否则（普通标签页）显示退出屏
    }

    // Esc：层级栈一层（设置面板）
    useEsc(() => setshowSetting(false), showSetting);


    return (
        <>
            <div className="background">
                <audio ref={audioRef} src={Ziye_Jijunshu} loop />
                <img className="background-image" src={bg} />

                <div>
                    <MoveLogo />
                </div>

                <GooseAnimation specific="goose_one" />
                <GooseAnimation specific="goose_two" />

                <div className="menu">
                    <button onClick={继续旅途} disabled={loading}>
                        <span>继续旅途</span>
                    </button>

                    <button onClick={() => setshowSetting(true)}>
                        <span>环境设定</span>
                    </button>

                    <button onClick={归隐山林}>
                        <span>归隐山林</span>
                    </button>
                </div>

                {
                    showSetting && (
                        <div className="Setting">
                            <div className="setting-inner">
                                <h2 className="setting-title">环境设定</h2>

                                <div className="setting-row">
                                    <span className="setting-label">地图</span>
                                    <div className="setting-options">
                                        {maps.map((m) => (
                                            <button
                                                key={m.id}
                                                className={"setting-option" + (m.id === curMap ? " active" : "")}
                                                onClick={() => 选地图(m.id)}
                                            >
                                                {m.name}
                                            </button>
                                        ))}
                                        {!maps.length && (
                                            <span className="sim-empty">（后端未启动，读不到地图列表）</span>
                                        )}
                                    </div>
                                </div>

                                <div className="setting-row">
                                    <span className="setting-label">难度</span>
                                    <div className="setting-options">
                                        {difficultyOptions.map((d) => (
                                            <button
                                                key={d}
                                                className={"setting-option" + (d === difficulty ? " active" : "")}
                                                onClick={() => 选难度(d)}
                                            >
                                                {d}
                                            </button>
                                        ))}
                                    </div>
                                </div>

                                <div className="setting-row sim-row">
                                    <span className="setting-label">模拟战斗</span>
                                    <div className="sim-wrap">
                                        {!roster.length && (
                                            <div className="sim-empty">（后端未启动，读不到名单）</div>
                                        )}
                                        {roster.length > 0 && (
                                            <div className="sim-cols">
                                                <div className="sim-col">
                                                    <div className="sim-col-title">友军 {sim友.length}</div>
                                                    <div className="sim-chips">
                                                        {roster.map((c) => (
                                                            <button key={c.名字}
                                                                className={"sim-chip ally" + (sim友.includes(c.名字) ? " active" : "")}
                                                                onClick={() => 切换参战("友", c.名字)}>
                                                                {c.名字}<i>{c.梯度}</i>
                                                            </button>
                                                        ))}
                                                    </div>
                                                </div>
                                                <div className="sim-col">
                                                    <div className="sim-col-title">敌人 {sim敌.length}</div>
                                                    <div className="sim-chips">
                                                        {roster.map((c) => (
                                                            <button key={c.名字}
                                                                className={"sim-chip enemy" + (sim敌.includes(c.名字) ? " active" : "")}
                                                                onClick={() => 切换参战("敌", c.名字)}>
                                                                {c.名字}<i>{c.梯度}</i>
                                                            </button>
                                                        ))}
                                                    </div>
                                                </div>
                                            </div>
                                        )}
                                        <button className="sim-start"
                                            disabled={!sim敌.length || simBusy}
                                            onClick={开始模拟}>
                                            {simBusy ? "开局中…" : "开始模拟战斗（梁峰固定参战）"}
                                        </button>
                                    </div>
                                </div>
                            </div>
                        </div>
                    )
                }
            </div>

            <div className="intro-mask"></div>

            {/* 加载中：仍在主页面，主题曲继续放；加载完直接进游戏 */}
            {loading && (
                <div className="recap-loading">
                    <span>正在回顾前情……</span>
                </div>
            )}

            {/* 归隐山林：退出屏（window.close 无效时兜底） */}
            {quit && (
                <div className="quit-screen">
                    <span>雾锁山门，已归隐山林</span>
                </div>
            )}

            {simState && <BattleScene initial={simState} onExit={退出模拟} />}
        </>
    );
}

export default Menu;
