import { useEffect, useRef, useState } from "react";
import Ziye_Jijunshu from "../assets/音乐/子夜寄君书.mp3";
import "../styles/menu.css";
import bg from "../assets/背景/主页面.png";
import "../styles/Background.css";
import GooseAnimation from "./GooseAnimation";
import MoveLogo from "./Logo";
import type { instruction } from "../types/gametype";

// 进游戏时一并带进去的数据（前情回顾段落 + 最后一幕 bg/音乐）
export type StartData = {
    segments?: instruction[];
    bg?: { position?: string; time?: string } | null;
    music?: string | null;
} | null;

type MenuProps = {
    onStartGame: (start?: StartData) => void;
};

const API = "http://localhost:5000";

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

    // ---- 归隐山林：直接退出 ----
    const [quit, setQuit] = useState(false);
    function 归隐山林() {
        audioRef.current?.pause();
        window.close();      // 脚本打开的窗口会真关闭
        setQuit(true);       // 否则（普通标签页）显示退出屏
    }

    //按Esc退出环境设定
    useEffect(() => {
        const handleKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                setshowSetting(false)
            }
        };

        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, []);


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
        </>
    );
}

export default Menu;
