import Menu from "./out-game/Menu";
import Gaming from "./in-game/GameController";
// gaming和menu是兄弟关系

import "./styles/App.css";
import { useState } from "react";

function App() {

  const [inGame, setInGame] = useState(false);

  return (
    <div className="app">
      {
        inGame
        ?
        <Gaming onBackMenu={() => setInGame(false)} />
        :
        <Menu onStartGame={() => setInGame(true)} />
      }
    </div>
  );
}

export default App;
