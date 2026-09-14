import Menu, { type StartData } from "./out-game/Menu";
import Gaming from "./in-game/GameController";
// gaming和menu是兄弟关系

import "./styles/App.css";
import { useState } from "react";

function App() {

  const [inGame, setInGame] = useState(false);
  const [startData, setStartData] = useState<StartData>(null); // 前情回顾带出来的 bg/音乐

  return (
    <div className="app">
      {
        inGame
        ?
        <Gaming
          onBackMenu={() => setInGame(false)}
          initialBg={startData?.bg}
          initialMusic={startData?.music}
          initialRecap={startData?.segments}
        />
        :
        <Menu onStartGame={(start) => { setStartData(start ?? null); setInGame(true); }} />
      }
    </div>
  );
}

export default App;
