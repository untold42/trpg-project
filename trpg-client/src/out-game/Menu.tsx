import { useEffect, useRef, useState } from "react";
import Ziye_Jijunshu from "../assets/音乐/子夜寄君书.mp3";
import "../styles/menu.css";
import bg from "../assets/背景/主页面.png";
import "../styles/Background.css";
import GooseAnimation from "./GooseAnimation";
import MoveLogo from "./Logo";


type MenuProps = {
    onStartGame: () => void;
};

function Menu({ onStartGame }: MenuProps) {
    //音乐预处理
    const [showSetting, setshowSetting] = useState(false);
    const audioRef = useRef<HTMLAudioElement>(null);
    useEffect(() => {
        audioRef.current?.play();
    }, []);

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
                    <button onClick={onStartGame}>
                        <span>继续旅途</span>
                    </button>

                    <button onClick={() => setshowSetting(true)}>
                        <span>环境设定</span>
                    </button>

                    <button>
                        <span>归隐山林</span>
                    </button>
                </div>

                {
                    showSetting &&(
                        <div className="Setting">
                            我日了
                        </div>
                    )
                    
                }
            </div>

            <div className="intro-mask"></div>
        </>
    );
}

export default Menu;