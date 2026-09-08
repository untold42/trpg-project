import GameScene from "./GameScene";
import "../styles/GameController.css"
import "../styles/Background.css"
import { useEffect, useRef, useState } from "react";
import type { instruction } from "../types/gametype";
import { story_previous } from "../data/previous"
import preloadImages from "./PreloadImages";
import { historyLog } from "./GameScene";
import GameMap from "./Map"

//承接App.tsx
type GamingProps = {
    onBackMenu: () => void;
};

//预加载前端资源
const images = import.meta.glob(
    "../assets/**/*.{png,jpg,jpeg,webp}",
    {
        eager: true,
        query: "?url",
        import: "default"
    }
);

function Gaming({ onBackMenu }: GamingProps) {
    const [showInputGM, setshowInputGM] = useState(false); //展示主持人输入框
    const [showInputAct, setShowInputAct] = useState(false); //展示动作输入框
    const [input, setInput] = useState(""); //输入框输入的内容
    const [history, setHistory] = useState<instruction[]>(story_previous); //拿到llm的回复
    const [showHistory, setShowHistory] = useState(false) //展示历史记录
    const [loaded, setLoaded] = useState(false); //判断是否加载完成
    const historyBoxRef = useRef<HTMLDivElement>(null);//历史对话框的保持底部
    const [showMap, setShowMap] = useState(false);

    //与后端的接口，拿到LLM的数据
    async function sendAction(content: string, prefix: string) {
        const res = await fetch(
            "http://localhost:5000/action",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    input: prefix + content
                })
            }
        );

        const response = await res.json();
        historyLog.push(`${prefix} ${content}`)
        setHistory(prev => [...prev, ...response]);
    }

    // 加载所有美术资源
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

    //监听Esc键位关闭输入框或历史记录框
    useEffect(() => {
        const handleKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                setShowHistory(false);
                setShowInputAct(false);
                setshowInputGM(false);
                setShowMap(false)
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
                ]} />
            </div>
        );
    }

    else {
        return (
            <div className="background">
                <GameScene history={history} />

                <button className="back-button" onClick={onBackMenu}>
                    返回主菜单
                </button>

                <button className="history-button" onClick={() => setShowHistory(!showHistory)}>
                    历史记录
                </button>

                <button className="act-button" onClick={() => setShowInputAct(!showInputAct)}>
                    行动
                </button>

                <button className="chat-button" onClick={() => setshowInputGM(!showInputGM)}>
                    主持人
                </button>

                <button className="map-button" onClick={() => setShowMap(!showMap)}>
                    地图
                </button>

                {
                showMap && (
                    <div className="game-map">
                        <GameMap />
                    </div>
                )
                }

                {
                showInputAct &&
                <textarea
                    className="dialog-box"
                    autoFocus
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => {
                        if (e.key === "Enter") {
                            sendAction(input, "梁峰：");
                            setInput("");
                            setShowInputAct(!showInputAct)
                        }
                    }}

                />
                }

                {
                    showInputGM &&
                    <textarea
                        className="dialog-box"
                        autoFocus
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === "Enter") {
                                sendAction(input, "玩家的对主持人说的话：");
                                setInput("");
                                setshowInputGM(!showInputGM)
                            }
                        }}

                    />
                }

                {showHistory && (
                    <div className="history-box">
                        <div className="history-log-content" ref={historyBoxRef}>
                            {historyLog.map((item, index) => (
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