import { Component, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { MutableRefObject } from "react";
import { MapContainer, TileLayer, Marker, useMap, useMapEvents } from "react-leaflet";
import type { LatLngBoundsExpression } from "leaflet";
import * as L from "leaflet";
import "leaflet/dist/leaflet.css";

import ClickableLayer from "./ClickableLayer";
import { mapStats } from "./mapStats";

// 地图可活动范围 = 瓦片实际覆盖的经纬度矩形（西南角 → 东北角）
// 与 trpg-map/城市.py 的 frame_bbox("扬州") 一致（画框 100.7×56.6 km）
const SW_CORNER: [number, number] = [32.153865, 118.881749]; // [lat, lon]
const NE_CORNER: [number, number] = [32.666135, 119.953251]; // [lat, lon]
const MAP_BOUNDS: LatLngBoundsExpression = [SW_CORNER, NE_CORNER];

// 后端没起来 / 没经纬度时的兜底中心
const DEFAULT_CENTER: [number, number] = [32.4040133, 119.4207185];

// 玩家位置 + 足迹（探索迷雾）：后端从 游戏数据/基本信息.json 读经纬度并记录足迹
const EXPLORED_URL = "http://localhost:5000/explored";

type PlayerPos = { lat: number; lon: number; name?: string };
export type Footprint = { lon: number; lat: number; 地点?: string };

const playerIcon = L.divIcon({
  className: "player-marker",
  // 圆圈包围的「梁」字棋子（样式在 styles/GameController.css 的 .player-token）
  html: '<div class="player-token">梁</div>',
  iconSize: [34, 34],
  iconAnchor: [17, 17],
  popupAnchor: [0, -18],
});

/** 调试 HUD：**暂时硬编码为开**（诊断完改回 URL 开关） */
const DEBUG_HUD = true;

/**
 * 地图错误边界。
 *
 * 没有它的话，地图里任何一个未捕获异常都会让 React 卸掉整棵子树，
 * 表现就是“一片黑，只剩古钟”，根本无法定位。
 * 有了它至少能把错误文本显示在屏幕上。
 */
class MapErrorBoundary extends Component<{ children: ReactNode }, { err: Error | null }> {
  state: { err: Error | null } = { err: null };

  static getDerivedStateFromError(err: Error) {
    return { err };
  }

  componentDidCatch(err: Error) {
    console.error("[地图崩溃]", err);
  }

  render() {
    if (this.state.err) {
      return (
        <div className="map-error">
          <b>地图出错</b>
          <pre>{String(this.state.err?.stack || this.state.err?.message || this.state.err)}</pre>
        </div>
      );
    }
    return this.props.children;
  }
}

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
  posRef, speedMps, runMult, onStop, radiusKm,
}: {
  posRef: MutableRefObject<{ lon: number; lat: number } | null>;
  speedMps: number;
  runMult: number;
  onStop: (p: { lon: number; lat: number }) => void;
  radiusKm: number;
}) {
  const map = useMap();
  const markerRef = useRef<L.Marker | null>(null);
  const keysRef = useRef<Record<string, boolean>>({});
  const stopRef = useRef(onStop);
  stopRef.current = onStop;

  // 相机同步节流用
  const lastSyncRef = useRef(0);
  const movedRef = useRef(false);

  // 相机平移的**小数余量**：每帧取整平移（与 Leaflet 自己的拖拽一致），
  // 余量累积到下一帧 —— 既保证整数像素（廉价），又不丢精度。
  const panAccRef = useRef({ x: 0, y: 0 });

  // 上一次上报给父组件的位置（迷雾气泡跟随用）
  const lastCommitRef = useRef<{ lon: number; lat: number } | null>(null);

  // 最近 500ms 内的最差帧耗时（ms）——用于看“尖峰”有多大
  const worstRef = useRef(0);

  // 键盘
  useEffect(() => {
    const isTyping = (t: EventTarget | null) => {
      const el = t as HTMLElement | null;
      return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (isTyping(e.target)) return;
      const k = e.key.toLowerCase();
      if (k === "shift") {
        keysRef.current["shift"] = true;
        return;
      }
      if (k === "w" || k === "a" || k === "s" || k === "d") {
        keysRef.current[k] = true;
        e.preventDefault();
      }
    };
    const onKeyUp = (e: KeyboardEvent) => {
      const k = e.key.toLowerCase();
      if (k === "shift") {
        keysRef.current["shift"] = false;
        return;
      }
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

    // 调试 HUD（硬编码开）：直接改 DOM，不 setState。
    // ⚠️ 必须挂到 document.body：.leaflet-container 只有 overflow:hidden、
    //    没有 position:relative，而且 .explore-map 的 z-index 层叠上下文会把
    //    HUD 压在按钮下面 —— 挂 body + fixed 才能保证看得见。
    let hud: HTMLDivElement | null = null;
    let frames = 0;
    let fpsAt = performance.now();
    if (DEBUG_HUD) {
      hud = document.createElement("div");
      hud.className = "map-debug-hud";
      hud.textContent = "HUD 启动中…";
      document.body.appendChild(hud);
    }
    const loop = (now: number) => {
      const frameMs = now - last;
      const dt = Math.min(0.05, Math.max(0, frameMs / 1000));
      last = now;
      if (frameMs > worstRef.current) worstRef.current = frameMs;
      const p = posRef.current;
      let runningNow = false;
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
        const running = !!k["shift"] && (dx !== 0 || dy !== 0);
        runningNow = running;
        if (dx || dy) {
          const len = Math.hypot(dx, dy);
          const dist = speedMps * (running ? runMult : 1) * dt;
          const mPerDegLon = M_PER_DEG_LAT * Math.cos((p.lat * Math.PI) / 180) || M_PER_DEG_LAT;
          let lat = p.lat + ((dy / len) * dist) / M_PER_DEG_LAT;
          let lon = p.lon + ((dx / len) * dist) / mPerDegLon;
          lat = Math.max(SW[0], Math.min(NE[0], lat));
          lon = Math.max(SW[1], Math.min(NE[1], lon));
          posRef.current = { lon, lat };
        }
        const cur = posRef.current!;

        // 迷雾气泡跟随：走过一定距离才上报一次（**不要每帧**，否则每帧 re-render）
        const rc = lastCommitRef.current;
        const step = Math.max(150, radiusKm * 400); // 米
        if (!rc) {
          lastCommitRef.current = { ...cur };
          stopRef.current(cur);
        } else {
          const dLat = (cur.lat - rc.lat) * 111320;
          const dLon = (cur.lon - rc.lon) * 111320 * Math.cos((cur.lat * Math.PI) / 180);
          if (Math.hypot(dLat, dLon) >= step) {
            lastCommitRef.current = { ...cur };
            stopRef.current(cur);
          }
        }
        const ll = markerRef.current.getLatLng();
        if (ll.lat !== cur.lat || ll.lng !== cur.lon) {
          markerRef.current.setLatLng([cur.lat, cur.lon]);
        }

        // 奔跑的视觉反馈（棋子描边变色）
        const el = markerRef.current.getElement();
        if (el) el.classList.toggle("is-running", running);

        // 相机：把玩家保持在视口**内圈（30% 边距）**以内。
        //
        // 性能关键：**不能每帧调 panBy**。
        // panBy 会 fire('move') + fire('moveend')，而 Canvas 矢量层（命中层）
        // 监听的是 moveend → 每帧都会 _redraw 全部图层（2000+ 个），必卡。
        //
        // Leaflet 自己的拖拽就是这么做的：每步只 _rawPanBy + fire('move')，
        // moveend 只在**松手时**发一次。这里照抄这个节奏。
        //
        // panBy(offset) 的语义：中心点 + offset，
        // 故某固定 latlng 的屏幕位置 = oldX - offset.x；拉回边界 mx 即 offset.x = cpt.x - mx。
        const size = map.getSize();
        const cpt = map.latLngToContainerPoint(L.latLng(cur.lat, cur.lon));
        const mx = size.x * 0.30;
        const my = size.y * 0.30;
        let panX = 0, panY = 0;
        if (cpt.x < mx) panX = cpt.x - mx;
        else if (cpt.x > size.x - mx) panX = cpt.x - (size.x - mx);
        if (cpt.y < my) panY = cpt.y - my;
        else if (cpt.y > size.y - my) panY = cpt.y - (size.y - my);

        // 已顶到地图边界就别再硬推（否则会和 maxBounds 的钳制每帧打架）
        const mb = map.getBounds();
        const EPS = 1e-6;
        if (mb.getSouth() <= SW[0] + EPS && panY > 0) panY = 0;
        if (mb.getNorth() >= NE[0] - EPS && panY < 0) panY = 0;
        if (mb.getWest() <= SW[1] + EPS && panX < 0) panX = 0;
        if (mb.getEast() >= NE[1] - EPS && panX > 0) panX = 0;

        if (panX || panY) {
          // ⚠️ 必须取整！
          // Leaflet 自己的拖拽是整数像素（鼠标坐标本来就是整数）；
          // 亚像素（translate3d 1.37px）会逼合成器每帧对**整个地图图层**做重采样，
          // 这是探索模式与“鼠标拖动菜单地图”最大的差异。
          // 小数余量累积到下一帧，不丢精度。
          const acc = panAccRef.current;
          acc.x += panX;
          acc.y += panY;
          const ix = Math.round(acc.x);
          const iy = Math.round(acc.y);
          acc.x -= ix;
          acc.y -= iy;

          if (ix || iy) {
            // 只动像素、不发事件 —— 极廉价，且与 Leaflet 拖拽内部一致。
            // （_rawPanBy 是 Leaflet 私有 API，但正是它自己的拖拽在用的；
            //   类型定义里没有，故强转一次）
            (map as unknown as { _rawPanBy: (o: L.Point) => void })
              ._rawPanBy(L.point(ix, iy));
            movedRef.current = true;
          }

          // move 节流（让瓦片/其他监听者跟上，但不要每帧）
          if (now - lastSyncRef.current > 100) {
            lastSyncRef.current = now;
            map.fire("move");
          }
        } else if (movedRef.current) {
          // 刚停下来：同步一次，并让依赖 moveend 的图层（Canvas 矢量层）重绘
          movedRef.current = false;
          map.fire("move");
          map.fire("moveend");
        }
      }

      // HUD 更新放在 if (p) **之外**：即使还没拿到位置也要显示 FPS
      if (hud) {
        frames++;
        if (now - fpsAt >= 500) {
          const fps = (frames * 1000) / (now - fpsAt);
          frames = 0;
          fpsAt = now;
          const q = posRef.current;
          const worst = worstRef.current;
          worstRef.current = 0;
          hud.textContent =
            `FPS ${fps.toFixed(0)}   最差帧 ${worst.toFixed(0)}ms   z${map.getZoom()}   跑:${runningNow ? "是" : "否"}\n` +
            `玩家 ${q ? q.lat.toFixed(5) + ", " + q.lon.toFixed(5) : "（未定位）"}\n` +
            `图标 ${mapStats.icons}  命中 ${mapStats.hits}  可见 ${mapStats.visible}\n` +
            `命中重绘 ${mapStats.hitMs.toFixed(1)}ms  图标重绘 ${mapStats.iconMs.toFixed(1)}ms`;
        }
      }

      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(raf);
      hud?.remove();
      markerRef.current?.remove();
      markerRef.current = null;
    };
  }, [map, posRef, speedMps, runMult]);

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
  /** 足迹版本号：extraFootprints 是**原地 push** 的（引用不变），靠它触发重算 */
  footprintVersion?: number;
  /** 单点迷雾气泡中心（探索模式）：只绘制这个点 ± radiusKm 内的要素 */
  focus?: { lon: number; lat: number } | null;
  /** 锁定缩放（探索模式锁 z18） */
  lockZoom?: boolean;
  /** WASD 连续移动 */
  wasd?: boolean;
  /** WASD 模式下的玩家位置（每帧由移动循环读写；不触发 React 重渲染） */
  posRef?: MutableRefObject<{ lon: number; lat: number } | null>;
  /** 真实移动速度（米 / 真实秒） */
  speedMps?: number;
  /** 按住 Shift 时的速度倍数 */
  runMult?: number;
  /** WASD 移动停下时的回调（同步给父组件） */
  onPositionChange?: (p: { lon: number; lat: number }) => void;
  /** 是否夜晚（由游戏时钟裁决）：决定图标取 <键>/night.png 还是 <键>/day.png */
  isNight?: boolean;
  /** 总览模式：**不启用探索迷雾**，全部 POI 都画（菜单里的地图用） */
  showAllIcons?: boolean;
};

function GameMap({
  zoom = 16, playerOverride, onMove, extraFootprints, footprintVersion, focus,
  lockZoom = false,
  wasd, posRef, speedMps = 20, runMult = 2.5, onPositionChange,
  isNight = false, showAllIcons = false,
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

  // 合并「后端足迹 + 本次行走轨迹」。
  // ⚠️ cursorTrail 是**原地 push** 的（数组引用不变），所以必须靠 footprintVersion
  //    触发重算；否则这里的 useMemo 永远不会更新，迷雾就不会揭开。
  //
  // ⚠️ Hooks 必须在任何 early return **之前**调用（否则会
  //    “Rendered more hooks than during the previous render” → 白屏）。
  const shownFootprints = useMemo(() => {
    void footprintVersion;
    if (extraFootprints && extraFootprints.length) {
      return [...(footprints ?? []), ...extraFootprints];
    }
    return footprints;
  }, [footprints, extraFootprints, footprintVersion]);

  // 等定位结果回来再渲染地图，保证初始中心就在玩家位置
  if (!ready) {
    return null;
  }

  const shownPlayer: PlayerPos | null = playerOverride
    ? { lat: playerOverride.lat, lon: playerOverride.lon, name: "当前位置" }
    : player;

  return (
    <MapErrorBoundary>
      <MapContainer
      center={shownPlayer ? [shownPlayer.lat, shownPlayer.lon] : DEFAULT_CENTER}
      zoom={zoom}
      minZoom={lockZoom ? zoom : 12}
      maxZoom={zoom}
      maxBounds={MAP_BOUNDS}
      maxBoundsViscosity={1.0}
      zoomControl={!lockZoom}
      scrollWheelZoom={!lockZoom}
      doubleClickZoom={!lockZoom}
      touchZoom={!lockZoom}
      boxZoom={!lockZoom}
      keyboard={!lockZoom}
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
      <ClickableLayer
        footprints={shownFootprints}
        focus={focus}
        radiusKm={radiusKm}
        isNight={isNight}
        noFog={showAllIcons}
      />

      {wasd && posRef ? (
        <ExploreControls
          posRef={posRef}
          speedMps={speedMps}
          runMult={runMult}
          radiusKm={radiusKm}
          onStop={onPositionChange ?? (() => { })}
        />
      ) : (
        shownPlayer && <PlayerMarker player={shownPlayer} />
      )}
      </MapContainer>
    </MapErrorBoundary>
  );
}

export default GameMap;
