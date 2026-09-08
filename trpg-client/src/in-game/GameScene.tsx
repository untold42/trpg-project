import { useEffect, useState } from "react";
import DialogueBox from "./DialogueBox";
import Character from "./Character";
import BackgroundTransition from "./BackgroundTransition";
import backgroundImages from "../assets/背景";
import "../styles/Background.css";
import type { instruction } from "../types/gametype";

let historyLog: string[] = [];
export { historyLog };

//将llm返回的十二时辰映射为白天，黄昏和黑夜
function convert_time(specific_time: string) {
  if (specific_time == "卯时" || specific_time == "辰时" || specific_time == "巳时" || specific_time == "午时"
    || specific_time == "未时" || specific_time == "申时") { return "白天" }
  else if (specific_time == "酉时") { return "黄昏" }
  else if (specific_time == "戌时" || specific_time == "亥时" || specific_time == "子时" || specific_time == "丑时" || specific_time == "寅时") {return "黑夜"}
  else { return "白天" }
}

//获取特定的背景图
function getBackgroundImage(position: string, time: string) {
  const path = `./${position}/${time}.png`;
  const p_and_t = backgroundImages[path] as string | undefined;
  if (p_and_t) {
    return p_and_t;
  }
  const just_p =
    backgroundImages[`./${position}/白天.png`] as string | undefined;
  if (just_p) {
    return just_p;
  }
  return backgroundImages[`./主页面.png`] as string;
}

type GameSceneProps = {
  history: instruction[];
};

function GameScene({ history }: GameSceneProps) {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [BG, setBG] = useState(backgroundImages[`./主页面.png`] as string);

  const currentLine = history[currentIndex];

  function nextLine() {
    if (currentIndex < history.length - 1) {
      if (history[currentIndex].type == 'bg') {
        historyLog.push(`背景切换至 ${history[currentIndex].position}`)
      } else if (history[currentIndex].type == 'narration') {
        historyLog.push(` 旁白：${history[currentIndex].content}`)
      } else {
        historyLog.push(`${history[currentIndex].speaker}：${history[currentIndex].content}`)
      }
      setCurrentIndex(currentIndex + 1);
    }
  }

  // 专门处理背景指令
  useEffect(() => {
    if (currentLine.type === "bg") {
      setBG(getBackgroundImage(currentLine.position, convert_time(currentLine.time)));

      // 自动跳到下一条
      nextLine()
    }
  }, [currentLine]);

  return (
    <div className="background">
      <BackgroundTransition image={BG} />
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