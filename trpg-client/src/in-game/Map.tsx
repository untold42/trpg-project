import { useEffect, useState } from "react";
import { MapContainer, TileLayer, Marker } from "react-leaflet";
import type { LatLngBoundsExpression } from "leaflet";
import * as L from "leaflet";
import "leaflet/dist/leaflet.css";

import ClickableLayer from "./ClickableLayer";

// 地图可活动范围 = 瓦片实际覆盖的经纬度矩形（西南角 → 东北角）
const MAP_BOUNDS: LatLngBoundsExpression = [
  [32.174886, 118.884015],   // 西南角
  [32.683653, 119.9556],     // 东北角
];

// 后端没起来 / 没经纬度时的兜底中心
const DEFAULT_CENTER: [number, number] = [32.4040133, 119.4207185];

// 玩家位置 + 足迹（探索迷雾）：后端从 游戏数据/基本信息.json 读经纬度并记录足迹
const EXPLORED_URL = "http://localhost:5000/explored";

type PlayerPos = { lat: number; lon: number; name?: string };
export type Footprint = { lon: number; lat: number; 地点?: string };

const playerIcon = L.divIcon({
  className: "player-marker",
  html: '<div style="width:18px;height:18px;background:#d32f2f;border:2px solid #fff;border-radius:50%;box-shadow:0 0 8px rgba(0,0,0,.6)"></div>',
  iconSize: [18, 18],
  iconAnchor: [9, 9],
  popupAnchor: [0, -16],
});

function PlayerMarker({ player }: { player: PlayerPos }) {
  return (
    <Marker
      position={[player.lat, player.lon]}
      icon={playerIcon}
      title={player.name || "当前位置"}
    />
  );
}

function GameMap() {
  const [player, setPlayer] = useState<PlayerPos | null>(null);
  const [footprints, setFootprints] = useState<Footprint[] | null>(null);
  const [radiusKm, setRadiusKm] = useState(0.5);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let alive = true;
    fetch(EXPLORED_URL)
      .then((res) => res.json())
      .then((data) => {
        if (!alive) return;
        if (typeof data.lat === "number" && typeof data.lon === "number") {
          setPlayer({ lat: data.lat, lon: data.lon, name: data["地点"] });
        }
        if (Array.isArray(data.footprints)) {
          setFootprints(data.footprints as Footprint[]);
        }
        if (typeof data.radius_km === "number") {
          setRadiusKm(data.radius_km);
        }
      })
      .catch(() => {
        // 后端未启动：footprints 保持 null → 不启用迷雾，显示全部 POI（旧行为）
      })
      .finally(() => {
        if (alive) setReady(true);
      });
    return () => {
      alive = false;
    };
  }, []);

  // 等定位结果回来再渲染地图，保证初始中心就在玩家位置
  if (!ready) {
    return null;
  }

  return (
    <MapContainer
      center={player ? [player.lat, player.lon] : DEFAULT_CENTER}
      zoom={16}
      minZoom={12}
      maxZoom={18}
      maxBounds={MAP_BOUNDS}
      maxBoundsViscosity={1.0}
      style={{ width: "100%", height: "100%" }}
    >
      <TileLayer
        url="/tiles/{z}/{x}/{y}.png"
        minZoom={12}
        maxZoom={18}
        maxNativeZoom={16}
        noWrap
      />

      <ClickableLayer footprints={footprints} radiusKm={radiusKm} />

      {player && <PlayerMarker player={player} />}
    </MapContainer>
  );
}

export default GameMap;
