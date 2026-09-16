import { useEffect, useState } from "react";
import DialogueBox from "./DialogueBox";
import Character from "./Character";
import BackgroundTransition from "./BackgroundTransition";
import "../styles/Background.css";
import type { instruction } from "../types/gametype";

type GameSceneProps = {
  history: instruction[];
  // 背景由 GameController 经 UI 事件（kind:"bg"）控制后传入；本组件不再自己处理背景
  background: string;
  // 点完最后一段后回调（前情回顾用它进入游戏；游戏内不传）
  onFinish?: () => void;
  // 外部指定起始句（探索→叙事时跳到**本轮叙事的第一句**，而不是上次读到的位置）
  startIndex?: number;
};

function GameScene({ history, background, onFinish, startIndex }: GameSceneProps) {
  const [currentIndex, setCurrentIndex] = useState(startIndex ?? 0);

  // 探索切回叙事：history 变了但当前句仍停在旧位置 → 显式跳到新起点
  useEffect(() => {
    if (typeof startIndex === "number") setCurrentIndex(startIndex);
  }, [startIndex]);

  const currentLine = history[currentIndex];

  function nextLine() {
    if (currentIndex < history.length - 1) {
      setCurrentIndex(currentIndex + 1);
    } else {
      onFinish?.();
    }
  }

  // 空历史（如新开局）时只显示背景
  if (!currentLine) {
    return (
      <div className="background">
        <BackgroundTransition image={background} />
      </div>
    );
  }

  return (
    <div className="background">
      <BackgroundTransition image={background} />
      {currentLine.type === "chat" && (
        <>
          <Character
            type="chat"
            speaker={currentLine.speaker}
            expression={currentLine.expression}
            content=""
          />

          <DialogueBox
            type="chat"
            speaker={currentLine.speaker}
            expression=""
            content={currentLine.content}
            onAdvance={nextLine}
          />
        </>
      )}

      {currentLine.type === "narration" && (
        <DialogueBox
          type="narration"
          content={currentLine.content}
          onAdvance={nextLine}
        />
      )}
    </div>
  );
}

export default GameScene;
