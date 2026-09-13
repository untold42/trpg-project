import { useState } from "react";
import DialogueBox from "./DialogueBox";
import Character from "./Character";
import BackgroundTransition from "./BackgroundTransition";
import "../styles/Background.css";
import type { instruction } from "../types/gametype";

type GameSceneProps = {
  history: instruction[];
  // 背景由 GameController 经 UI 事件（kind:"bg"）控制后传入；本组件不再自己处理背景
  background: string;
};

function GameScene({ history, background }: GameSceneProps) {
  const [currentIndex, setCurrentIndex] = useState(0);

  const currentLine = history[currentIndex];

  function nextLine() {
    if (currentIndex < history.length - 1) {
      setCurrentIndex(currentIndex + 1);
    }
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
