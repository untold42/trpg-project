import { Component, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { MutableRefObject } from "react";
import { MapContainer, TileLayer, Marker, useMap, useMapEvents } from "react-leaflet";
import type { LatLngBoundsExpression } from "leaflet";
import * as L from "leaflet";
import "leaflet/dist/leaflet.css";

import ClickableLayer from "./ClickableLayer";
import { mapStats } from "./mapStats";
import { loadWalkable, isWalkable, terrainAt } from "./walkable";
import { MAP_ID, tileUrlFor } from "./mapId";

// 地图可活动范围 = 瓦片实际覆盖的经纬度矩形（西南角 → 东北角）
// 与 trpg-map/城市.py 的 frame_bbox("扬州") 一致（画框 100.7×56.6 km）
const SW_CORNER: [number, number] = [32.153865, 118.881749]; // [lat, lon]
const NE_CORNER: [number, number] = [32.666135, 119.953251]; // [lat, lon]
const MAP_BOUNDS: LatLngBoundsExpression = [SW_CORNER, NE_CORNER];

// 后端没起来 / 没经纬度时的兜底中心
const DEFAULT_CENTER: [number, number] = [32.4040133, 119.4207185];

/** 搜索跳转用：key 变化即飞到目标点（同城跳转不会重挂地图，靠它） */
function FlyTo({ target }: { target: { lon: number; lat: number; key: number } | null }) {
  const map = useMap();
  const key = target?.key;
  useEffect(() => {
    if (!target) return;
    map.flyTo([target.lat, target.lon], Math.max(map.getZoom(), 16), { duration: 0.6 });
    // 只按 key 触发（同一目标重复点也要能重新飞）
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  return null;
}

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
 * 逐层开关（诊断用，见 `README.md` §13.4）。
 * 一次只关一层，最快定位卡顿来源：
 *   ?noicons=1  关掉图标层（DOM marker）
 *   ?nohit=1    关掉命中层（Canvas 矢量层）
 *   ?nopan=1    关掉相机跟随（玩家仍会移动，只是镜头不动）
 *   ?nofog=1    关掉迷雾（全部要素可见）
 * 例： http://localhost:5173/?noicons=1
 */
const _Q = new URLSearchParams(typeof window !== "undefined" ? window.location.search : "");
const NO_ICONS = _Q.has("noicons");
const NO_HIT = _Q.has("nohit");
const NO_PAN = _Q.has("nopan");
const NO_FOG = _Q.has("nofog");
/** ?nowalk=1：关掉体积碰撞（调试用） */
const NO_WALK = _Q.has("nowalk");
/** ?nonight=1：关掉黑夜滤镜 / 图标发光 */
const NO_NIGHT = _Q.has("nonight");

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
 * 黑夜滤镜：把瓦片染成深蓝。
 *
 * 用 **CSS filter 直接作用在瓦片层**（`.leaflet-tile-pane`）—— 不依赖
 * mix-blend-mode 的层叠上下文（实测在 Leaflet 的 pane 里不生效）。
 * 滤镜链：去色 → 压暗 → 染蓝 → 加饱和度。
 * 配方在 `GameController.css` 的 `.leaflet-container.is-night .leaflet-tile-pane`。
 *
 * 图标 / 棋子在 markerPane，不受影响，继续发光。
 */

/**
 * WASD 连续移动（命令式：**不触发 React 重渲染**）。
 * - 位置真相在 `posRef`（每帧读写）；玩家标记用原生 L.marker，逐帧 setLatLng + 相机跟随；
 * - 输入框聚焦时不拦截 WASD（打字不移动）；
 * - 松开按键时回调 `onStop(pos)`，把位置同步给父组件（迷雾轨迹 / 行动坐标）。
 */
function ExploreControls({
  posRef, speedMps, runMult, onStop, onRun, radiusKm, noPan = false, walkable, area,
}: {
  posRef: MutableRefObject<{ lon: number; lat: number } | null>;
  speedMps: number;
  runMult: number;
  onStop: (p: { lon: number; lat: number }) => void;
  /** 奔跑额外距离（米）上报（用于后端扣精力） */
  onRun?: (extraMeters: number) => void;
  radiusKm: number;
  /** 只移动玩家、不移动镜头（?nopan=1） */
  noPan?: boolean;
  /** 可走判定（返回 false 则被挡）；不传 = 不做碰撞 */
  walkable?: (lon: number, lat: number) => boolean;
  /** 活动范围 [[minLat,minLon],[maxLat,maxLon]]——**按地图传**，别写死扬州 */
  area: [[number, number], [number, number]];
}) {
  const map = useMap();
  const markerRef = useRef<L.Marker | null>(null);
  const keysRef = useRef<Record<string, boolean>>({});
  const stopRef = useRef(onStop);
  stopRef.current = onStop;
  const onRunRef = useRef(onRun);
  onRunRef.current = onRun;
  const runAccumRef = useRef(0);      // 累计「奔跑超出步行」的米数
  const wasRunningRef = useRef(false);

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
    const SW = area[0];
    const NE = area[1];

    // 调试 HUD（硬编码开）：直接改 DOM，不 setState。
    // ⚠️ 必须挂到 document.body：.leaflet-container 只有 overflow:hidden、
    //    没有 position:relative，而且 .explore-map 的 z-index 层叠上下文会把
    //    HUD 压在按钮下面 —— 挂 body + fixed 才能保证看得见。
    let hud: HTMLDivElement | null = null;
    // 地形步速提示（常显；只在文字变化时写 DOM，避免每帧重排）
    let badge: HTMLDivElement | null = null;
    let badgeText = "";
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
      let blockedNow = false;
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
          // 地形步速倍率：路 → 路倍率；否则取最重地形（林地/山地）；平地 1.0
          const tinfo = terrainAt(p.lon, p.lat);
          const dist = speedMps * tinfo.mult * (running ? runMult : 1) * dt;
          const mPerDegLon = M_PER_DEG_LAT * Math.cos((p.lat * Math.PI) / 180) || M_PER_DEG_LAT;
          let lat = p.lat + ((dy / len) * dist) / M_PER_DEG_LAT;
          let lon = p.lon + ((dx / len) * dist) / mPerDegLon;
          lat = Math.max(SW[0], Math.min(NE[0], lat));
          lon = Math.max(SW[1], Math.min(NE[1], lon));
          // 体积碰撞（水域 / 城墙）：不能走就沿障碍滑动（先试只动 x，再试只动 y）
          const tryMove = (tlon: number, tlat: number) => {
            if (!walkable || walkable(tlon, tlat)) {
              posRef.current = { lon: tlon, lat: tlat };
              return true;
            }
            return false;
          };
          const moved = tryMove(lon, lat) || tryMove(lon, p.lat) || tryMove(p.lon, lat);
          blockedNow = !moved && !!walkable;
        }
        const cur = posRef.current!;

        // 奔跑额外出力：只累计「超出步行的那部分距离」（碰撞未动则不计），
        // 累积到 200 米 或 停止奔跑 时上报后端扣精力（时间流逝已在扣，避免双重计费）
        const movedM = Math.hypot(
          (cur.lat - p.lat) * M_PER_DEG_LAT,
          (cur.lon - p.lon) * M_PER_DEG_LAT * Math.cos((cur.lat * Math.PI) / 180),
        );
        if (running) runAccumRef.current += movedM * (1 - 1 / runMult);
        if ((wasRunningRef.current && !running) || runAccumRef.current >= 200) {
          const m = runAccumRef.current;
          runAccumRef.current = 0;
          if (m > 1) onRunRef.current?.(m);
        }
        wasRunningRef.current = running;

        // 地形步速提示（常显；变化时才写 DOM）
        const tm = terrainAt(cur.lon, cur.lat);
        if (tm.mult !== 1) {
          const txt = `${tm.kind || "地形"} ×${tm.mult.toFixed(2)}`;
          if (txt !== badgeText) {
            badgeText = txt;
            if (!badge) {
              badge = document.createElement("div");
              badge.className = "map-terrain-badge";
              document.body.appendChild(badge);
            }
            badge.textContent = txt;
            badge.style.display = "block";
          }
        } else if (badgeText) {
          badgeText = "";
          if (badge) badge.style.display = "none";
        }

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

        // 奔跑 / 被挡 的视觉反馈（棋子描边变色）
        const el = markerRef.current.getElement();
        if (el) {
          el.classList.toggle("is-running", running);
          el.classList.toggle("is-blocked", blockedNow);
        }

        // 相机：玩家**始终居中**（镜头随人走，不给拖动）。
        //
        // 性能关键：**不能每帧调 panBy**。
        // panBy 会 fire('move') + fire('moveend')，而 Canvas 矢量层（命中层）
        // 监听的是 moveend → 每帧都会 _redraw 全部图层（2000+ 个），必卡。
        //
        // Leaflet 自己的拖拽就是这么做的：每步只 _rawPanBy + fire('move')，
        // moveend 只在**松手时**发一次。这里照抄这个节奏。
        //
        // panBy(offset) 的语义：中心点 + offset，
        // 故某固定 latlng 的屏幕位置 = oldX - offset.x；拉回正中即 offset = cpt - 视口中心。
        const size = map.getSize();
        const cpt = map.latLngToContainerPoint(L.latLng(cur.lat, cur.lon));
        let panX = cpt.x - size.x / 2;
        let panY = cpt.y - size.y / 2;
        // 死区：已贴中心（<1px）就不 pan。
        // 否则 _rawPanBy 的整数取整会留下 ±0.5px 残差，静止时也会反复微调 →
        // 每 100ms fire("move") → Canvas 命中层白重绘。
        if (Math.abs(panX) < 1) panX = 0;
        if (Math.abs(panY) < 1) panY = 0;

        // 已顶到地图边界就别再硬推（否则会和 maxBounds 的钳制每帧打架）
        const mb = map.getBounds();
        const EPS = 1e-6;
        if (mb.getSouth() <= SW[0] + EPS && panY > 0) panY = 0;
        if (mb.getNorth() >= NE[0] - EPS && panY < 0) panY = 0;
        if (mb.getWest() <= SW[1] + EPS && panX < 0) panX = 0;
        if (mb.getEast() >= NE[1] - EPS && panX > 0) panX = 0;

        // ?nopan=1：只走人、不动镜头（用于区分「卡在相机」还是「卡在渲染」）
        if (noPan) { panX = 0; panY = 0; }

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
            `命中重绘 ${mapStats.hitMs.toFixed(1)}ms  图标重绘 ${mapStats.iconMs.toFixed(1)}ms\n` +
            `关:${[NO_ICONS && "图标", NO_HIT && "命中", NO_PAN && "相机", NO_FOG && "迷雾"].filter(Boolean).join("/") || "无"}`;
        }
      }

      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(raf);
      hud?.remove();
      badge?.remove();
      markerRef.current?.remove();
      markerRef.current = null;
    };
  }, [map, posRef, speedMps, runMult, noPan, walkable, area]);

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
  /** 奔跑「超出步行」的距离（米）——累积到一定量或松手时上报，用于扣精力 */
  onRun?: (extraMeters: number) => void;
  /** WASD 移动停下时的回调（同步给父组件） */
  onPositionChange?: (p: { lon: number; lat: number }) => void;
  /** 是否夜晚（由游戏时钟裁决）：决定图标取 <键>/night.png 还是 <键>/day.png */
  isNight?: boolean;
  /** 当前时辰索引（0=子…11=亥）：决定打烊的地点夜里不亮灯 */
  shichen?: number;
  /** 点击 POI 弹窗里的动作（进入 / 观察 / 回忆） */
  onPlaceAction?: (place: string, act: string) => void;
  /** 看哪张地图（默认 `?map=`）。探索地图应传**玩家所在城市** */
  mapId?: string;
  /** 该地图的画框（maxBounds）；不传则用扬州默认值 */
  bounds?: LatLngBoundsExpression;
  /** 没有玩家坐标时的初始中心（不传则用扬州默认值） */
  center?: [number, number];
  /** 玩家不在本图时隐藏玩家标记（例如在看别的地图） */
  hidePlayer?: boolean;
  /** 搜索跳转：key 变化即飞到该点 */
  flyTo?: { lon: number; lat: number; key: number } | null;
};

function GameMap({
  zoom = 16, playerOverride, onMove, extraFootprints, footprintVersion, focus,
  lockZoom = false,
  wasd, posRef, speedMps = 0, runMult = 1, onPositionChange, onRun,
  isNight = false, shichen = -1, onPlaceAction,
  mapId = MAP_ID, bounds, center, hidePlayer = false, flyTo = null,
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

  // 体积碰撞数据（水域 / 城墙 / 城门 / 桥 / 路 / 地形）——**只有 WASD 探索才需要**。
  // 总览图（只看不走到）不要加载：walkable 的索引是模块级单例，
  // 加载别的地图会把 `IDX` 换成那一张，探索时碰撞就全错了。
  useEffect(() => {
    if (!wasd) return;
    loadWalkable(mapId);
  }, [mapId, wasd]);

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

  // 活动范围（夹住走动坐标）——按地图算，否则玩家会被夹到另一座城的边界上。
  // ⚠️ 必须放在 `if (!ready) return null` **之前**（Hooks 不能在任何 early return 之后）。
  const areaKey = bounds ? JSON.stringify(bounds) : "";
  const area = useMemo<[[number, number], [number, number]]>(() => {
    const b = bounds as [[number, number], [number, number]] | undefined;
    if (Array.isArray(b) && b.length === 2 && Array.isArray(b[0])) return b;
    return [SW_CORNER, NE_CORNER];
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [areaKey]);

  // 等定位结果回来再渲染地图，保证初始中心就在玩家位置
  if (!ready) {
    return null;
  }

  const shownPlayer: PlayerPos | null = hidePlayer
    ? null
    : playerOverride
      ? { lat: playerOverride.lat, lon: playerOverride.lon, name: "当前位置" }
      : player;

  return (
    <MapErrorBoundary>
      <MapContainer
      key={mapId}
      className={isNight && !NO_NIGHT ? "is-night" : undefined}
      center={shownPlayer ? [shownPlayer.lat, shownPlayer.lon]
                          : (center ?? DEFAULT_CENTER)}
      zoom={zoom}
      minZoom={lockZoom ? zoom : 12}
      maxZoom={zoom}
      maxBounds={bounds ?? MAP_BOUNDS}
      maxBoundsViscosity={1.0}
      zoomControl={!lockZoom}
      scrollWheelZoom={!lockZoom}
      doubleClickZoom={!lockZoom}
      touchZoom={!lockZoom}
      boxZoom={!lockZoom}
      keyboard={!lockZoom}
      dragging={!lockZoom}
      style={{ width: "100%", height: "100%" }}
    >
      <TileLayer
        url={tileUrlFor(mapId)}
        minZoom={12}
        maxZoom={18}
        maxNativeZoom={16}
        noWrap
      />

      <ClickToMove onMove={onMove} />
      <FlyTo target={flyTo} />
      <ClickableLayer
        mapId={mapId}
        footprints={shownFootprints}
        focus={focus}
        radiusKm={radiusKm}
        isNight={isNight}
        shichen={shichen}
        noFog={NO_FOG}
        hideIcons={NO_ICONS}
        hideHit={NO_HIT}
        onPlaceAction={onPlaceAction}
        showActions={!!onPlaceAction}
      />

      {wasd && posRef ? (
        <ExploreControls
          posRef={posRef}
          speedMps={speedMps}
          runMult={runMult}
          radiusKm={radiusKm}
          noPan={NO_PAN}
          area={area}
          walkable={NO_WALK ? undefined : isWalkable}
          onStop={onPositionChange ?? (() => { })}
          onRun={onRun}
        />
      ) : (
        shownPlayer && <PlayerMarker player={shownPlayer} />
      )}
      </MapContainer>
    </MapErrorBoundary>
  );
}

export default GameMap;
