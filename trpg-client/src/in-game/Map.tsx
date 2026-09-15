import { useEffect, useRef, useState } from "react";
import type { MutableRefObject } from "react";
import { MapContainer, TileLayer, Marker, useMap, useMapEvents } from "react-leaflet";
import type { LatLngBoundsExpression } from "leaflet";
import * as L from "leaflet";
import "leaflet/dist/leaflet.css";

import ClickableLayer from "./ClickableLayer";

// 地图可活动范围 = 瓦片实际覆盖的经纬度矩形（西南角 → 东北角）
const SW_CORNER: [number, number] = [32.174886, 118.884015]; // [lat, lon]
const NE_CORNER: [number, number] = [32.683653, 119.9556];   // [lat, lon]
const MAP_BOUNDS: LatLngBoundsExpression = [SW_CORNER, NE_CORNER];

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

/** 点击地图回调（可选）。**探索模式不传** → 点地图只看 POI 信息，不移动玩家 */
function ClickToMove({ onMove }: { onMove?: (p: { lon: number; lat: number }) => void }) {
  useMapEvents({
    click(e) {
      onMove?.({ lon: e.latlng.lng, lat: e.latlng.lat });
    },
  });
  return null;
}

/**
 * WASD 连续移动（命令式：**不触发 React 重渲染**）。
 * - 位置真相在 `posRef`（每帧读写）；玩家标记用原生 L.marker，逐帧 setLatLng + 相机跟随；
 * - 输入框聚焦时不拦截 WASD（打字不移动）；
 * - 松开按键时回调 `onStop(pos)`，把位置同步给父组件（迷雾轨迹 / 行动坐标）。
 */
function ExploreControls({
  posRef, speedMps, onStop,
}: {
  posRef: MutableRefObject<{ lon: number; lat: number } | null>;
  speedMps: number;
  onStop: (p: { lon: number; lat: number }) => void;
}) {
  const map = useMap();
  const markerRef = useRef<L.Marker | null>(null);
  const keysRef = useRef<Record<string, boolean>>({});
  const stopRef = useRef(onStop);
  stopRef.current = onStop;

  // 键盘
  useEffect(() => {
    const isTyping = (t: EventTarget | null) => {
      const el = t as HTMLElement | null;
      return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (isTyping(e.target)) return;
      const k = e.key.toLowerCase();
      if (k === "w" || k === "a" || k === "s" || k === "d") {
        keysRef.current[k] = true;
        e.preventDefault();
      }
    };
    const onKeyUp = (e: KeyboardEvent) => {
      const k = e.key.toLowerCase();
      if (k === "w" || k === "a" || k === "s" || k === "d") {
        keysRef.current[k] = false;
        const p = posRef.current;
        if (p) stopRef.current(p);
      }
    };
    const onBlur = () => { keysRef.current = {}; };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    window.addEventListener("blur", onBlur);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
      window.removeEventListener("blur", onBlur);
    };
  }, [posRef]);

  // 移动循环
  useEffect(() => {
    let raf = 0;
    let last = performance.now();
    const M_PER_DEG_LAT = 111320;
    const SW = SW_CORNER;
    const NE = NE_CORNER;
    const loop = (now: number) => {
      const dt = Math.min(0.05, Math.max(0, (now - last) / 1000));
      last = now;
      const p = posRef.current;
      if (p) {
        if (!markerRef.current) {
          markerRef.current = L.marker([p.lat, p.lon], { icon: playerIcon, title: "当前位置" }).addTo(map);
          map.setView([p.lat, p.lon], map.getZoom(), { animate: false });
        }
        const k = keysRef.current;
        let dx = 0, dy = 0;
        if (k["w"]) dy += 1;
        if (k["s"]) dy -= 1;
        if (k["a"]) dx -= 1;
        if (k["d"]) dx += 1;
        if (dx || dy) {
          const len = Math.hypot(dx, dy);
          const dist = speedMps * dt;
          const mPerDegLon = M_PER_DEG_LAT * Math.cos((p.lat * Math.PI) / 180) || M_PER_DEG_LAT;
          let lat = p.lat + ((dy / len) * dist) / M_PER_DEG_LAT;
          let lon = p.lon + ((dx / len) * dist) / mPerDegLon;
          lat = Math.max(SW[0], Math.min(NE[0], lat));
          lon = Math.max(SW[1], Math.min(NE[1], lon));
          posRef.current = { lon, lat };
        }
        const cur = posRef.current!;
        const ll = markerRef.current.getLatLng();
        if (ll.lat !== cur.lat || ll.lng !== cur.lon) {
          markerRef.current.setLatLng([cur.lat, cur.lon]);
        }
        // 相机：**死区跟随**——只在玩家逼近视口边缘（外圈 20%）时才平移。
        // 每帧 panTo 会每帧触发 moveend → 图标层重建 + 画布重绘 2200 个要素，卡。
        const b = map.getBounds();
        const padLat = (b.getNorth() - b.getSouth()) * 0.2;
        const padLon = (b.getEast() - b.getWest()) * 0.2;
        if (cur.lat > b.getNorth() - padLat || cur.lat < b.getSouth() + padLat ||
            cur.lon > b.getEast() - padLon || cur.lon < b.getWest() + padLon) {
          map.panTo([cur.lat, cur.lon], { animate: false });
        }
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(raf);
      markerRef.current?.remove();
      markerRef.current = null;
    };
  }, [map, posRef, speedMps]);

  return null;
}

export type GameMapProps = {
  /** 初始缩放（探索模式用 18；菜单里的地图用 16） */
  zoom?: number;
  /** 覆盖玩家显示位置（非 WASD 模式；探索模式改用 posRef） */
  playerOverride?: { lon: number; lat: number } | null;
  /** 点击地图回调（预留；探索模式**不传**，避免点击瞬移） */
  onMove?: (p: { lon: number; lat: number }) => void;
  /** 追加的足迹点（探索模式：光标走过的路径，用于即时揭示迷雾） */
  extraFootprints?: { lon: number; lat: number }[];
  /** WASD 连续移动 */
  wasd?: boolean;
  /** WASD 模式下的玩家位置（每帧由移动循环读写；不触发 React 重渲染） */
  posRef?: MutableRefObject<{ lon: number; lat: number } | null>;
  /** 真实移动速度（米 / 真实秒） */
  speedMps?: number;
  /** WASD 移动停下时的回调（同步给父组件） */
  onPositionChange?: (p: { lon: number; lat: number }) => void;
};

function GameMap({
  zoom = 16, playerOverride, onMove, extraFootprints,
  wasd, posRef, speedMps = 20, onPositionChange,
}: GameMapProps = {}) {
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

  const shownPlayer: PlayerPos | null = playerOverride
    ? { lat: playerOverride.lat, lon: playerOverride.lon, name: "当前位置" }
    : player;
  const shownFootprints = extraFootprints && extraFootprints.length
    ? [...(footprints ?? []), ...extraFootprints]
    : footprints;

  return (
    <MapContainer
      center={shownPlayer ? [shownPlayer.lat, shownPlayer.lon] : DEFAULT_CENTER}
      zoom={zoom}
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

      <ClickToMove onMove={onMove} />
      <ClickableLayer footprints={shownFootprints} radiusKm={radiusKm} />

      {wasd && posRef ? (
        <ExploreControls
          posRef={posRef}
          speedMps={speedMps}
          onStop={onPositionChange ?? (() => { })}
        />
      ) : (
        shownPlayer && <PlayerMarker player={shownPlayer} />
      )}
    </MapContainer>
  );
}

export default GameMap;
