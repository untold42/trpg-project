import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { useMap } from "react-leaflet";
import { useEsc } from "../escStack";
import * as L from "leaflet";
import type { Feature, FeatureCollection, GeoJsonObject } from "geojson";
import { mapStats } from "./mapStats";
import { SHICHEN } from "./useGameClock";

/** 该地点此刻是否营业（hours 为「卯-酉」等时辰区间；全天/异常 → 开） */
function isOpenNow(hours: string | undefined, shichen: number): boolean {
  if (!hours || hours === "全天" || shichen < 0) return true;
  const parts = hours.split("-");
  if (parts.length !== 2) return true;
  const s = SHICHEN.indexOf(parts[0].trim());
  const e = SHICHEN.indexOf(parts[1].trim());
  if (s < 0 || e < 0) return true;
  return s <= e ? (shichen >= s && shichen <= e) : (shichen >= s || shichen <= e);
}

import { MAP_ID, dataUrlFor } from "./mapId";

const ICON_DIR = "/mapicons";
const MIN_ICON_ZOOM = 15;

/* 本地缓存：clickable.geojson 存 IndexedDB，二次打开免下载、免解析。
   每张地图一个库（`<map_id>-map-cache`），互不污染。 */
const CACHE_STORE = "kv";
const GEO_CACHE_KEY = "clickable-geojson";
const GEO_VERSION = "v3"; // 重新导出 clickable.geojson 后，若想强制前端刷新，bump 此值（v3: 五行神庙 + 君山环水；v2: 岳阳水域 POI 修复）

interface Footprint {
  lon: number;
  lat: number;
  地点?: string;
}

interface ClickableLayerProps {
  /** 看哪张地图（默认 `?map=`）；探索地图应传**玩家所在城市** */
  mapId?: string;
  /** 已探索足迹点；null/undefined = 不启用迷雾（显示全部） */
  footprints?: Footprint[] | null;
  /** 解锁半径（公里） */
  radiusKm?: number;
  /** 是否夜晚（由游戏时钟裁决，见 GameController）：决定取 <键>/night.png 还是 <键>/day.png */
  isNight?: boolean;
  /** 当前时辰索引（0=子…11=亥）：打烊的地点夜里不亮灯 */
  shichen?: number;
  /** 诊断开关（`?nofog=1`）：不做迷雾过滤，全部要素直接可见 */
  noFog?: boolean;
  /** 单点迷雾气泡（探索模式）：只保留这个点 ± radiusKm 内的要素 */
  focus?: { lon: number; lat: number } | null;
  /** 诊断开关（?noicons=1）：不渲染图标层 */
  hideIcons?: boolean;
  /** 诊断开关（?nohit=1）：不渲染命中层 */
  hideHit?: boolean;
  /** 点击 POI 弹窗里的动作（详细 / 观察 / 回忆） */
  onPlaceAction?: (place: string, act: string, kind?: string) => void;
  /** 弹窗是否显示动作按钮（**只在探索地图**为 true） */
  showActions?: boolean;
}

interface ClickableProps {
  id?: number;
  name?: string;
  name_modern?: string;
  kind?: string;
  group?: string;
  category?: string;
  tags?: Record<string, string>;
  icon?: string;
  icon_lon?: number;
  icon_lat?: number;
  /** 营业时间（来自 营业时间.json，如「卯-酉」「全天」） */
  hours?: string;
}

/* ================= IndexedDB 缓存 ================= */

function openCache(mapId: string): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(`${mapId}-map-cache`, 1);
    req.onupgradeneeded = () => {
      if (!req.result.objectStoreNames.contains(CACHE_STORE)) {
        req.result.createObjectStore(CACHE_STORE);
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function cacheGet(mapId: string, key: string): Promise<unknown> {
  try {
    const db = await openCache(mapId);
    return await new Promise((resolve, reject) => {
      const tx = db.transaction(CACHE_STORE, "readonly");
      const req = tx.objectStore(CACHE_STORE).get(key);
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  } catch {
    return null;
  }
}

async function cachePut(mapId: string, key: string, value: unknown): Promise<void> {
  try {
    const db = await openCache(mapId);
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(CACHE_STORE, "readwrite");
      tx.objectStore(CACHE_STORE).put(value, key);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  } catch {
    /* 缓存失败不影响主流程 */
  }
}

/* ================= 探索迷雾判定 ================= */

const KM_PER_DEG_LON = 96;
const KM_PER_DEG_LAT = 111;

function distKm(lon1: number, lat1: number, lon2: number, lat2: number): number {
  const dx = (lon2 - lon1) * KM_PER_DEG_LON;
  const dy = (lat2 - lat1) * KM_PER_DEG_LAT;
  return Math.hypot(dx, dy);
}

/** 要素的「代表点」+「包围盒」——一次遍历同时算出，供迷雾判定与视口裁剪使用 */
export type FeatureExtent = {
  /** 代表点（用于迷雾判定） */
  c: [number, number];
  /** 包围盒 [minLon, minLat, maxLon, maxLat]（用于视口裁剪） */
  bb: [number, number, number, number];
};

function featureExtent(f: Feature): FeatureExtent | null {
  const g = f.geometry;
  const p = f.properties as ClickableProps;

  if (g.type === "Point") {
    const c = g.coordinates as number[];
    return { c: [c[0], c[1]], bb: [c[0], c[1], c[0], c[1]] };
  }
  if (g.type === "GeometryCollection") {
    return null;
  }

  let n = 0, sumLon = 0, sumLat = 0;
  let mnx = Infinity, mny = Infinity, mxx = -Infinity, mxy = -Infinity;

  const walk = (x: unknown) => {
    if (Array.isArray(x) && typeof x[0] === "number") {
      const lon = x[0] as number, lat = x[1] as number;
      n++; sumLon += lon; sumLat += lat;
      if (lon < mnx) mnx = lon;
      if (lon > mxx) mxx = lon;
      if (lat < mny) mny = lat;
      if (lat > mxy) mxy = lat;
      return;
    }
    if (Array.isArray(x)) x.forEach(walk);
  };
  walk(g.coordinates);

  if (n === 0) return null;

  // 面要素优先用导出时算好的内部代表点
  const c: [number, number] =
    p.icon_lon != null && p.icon_lat != null
      ? [p.icon_lon, p.icon_lat]
      : [sumLon / n, sumLat / n];

  return { c, bb: [mnx, mny, mxx, mxy] };
}

/* ---------- 迷雾判定加速 ----------
 *
 * 原来：每个要素都跑一遍 featureCenter（会遍历整个几何），
 *       再和**全部足迹**逐个算距离 → O(要素数 × 足迹数)，
 *       而且足迹最多 200 条，每次重渲染都重算 → 明显卡顿。
 *
 * 现在：① 要素中心只算一次（缓存）；
 *       ② 足迹装进「半径大小的格子」，查询只看 3×3 邻格 → O(1)。
 */

type FootprintGrid = {
  grid: Map<string, Footprint[]>;
  dLat: number;
  dLon: number;
  radiusKm: number;
};

function buildFootprintGrid(
  footprints: Footprint[],
  radiusKm: number,
): FootprintGrid {
  const cellKm = Math.max(radiusKm, 0.05);
  const dLat = cellKm / 111.0;
  const dLon = cellKm / 94.0; // 扬州纬度下 1° 经度 ≈ 94 km
  const grid = new Map<string, Footprint[]>();
  for (const fp of footprints) {
    const key = `${Math.floor(fp.lat / dLat)}|${Math.floor(fp.lon / dLon)}`;
    const arr = grid.get(key);
    if (arr) arr.push(fp);
    else grid.set(key, [fp]);
  }
  return { grid, dLat, dLon, radiusKm };
}

function isExploredFast(c: [number, number], g: FootprintGrid): boolean {
  const ci = Math.floor(c[1] / g.dLat);
  const cj = Math.floor(c[0] / g.dLon);
  for (let di = -1; di <= 1; di++) {
    for (let dj = -1; dj <= 1; dj++) {
      const arr = g.grid.get(`${ci + di}|${cj + dj}`);
      if (!arr) continue;
      for (const fp of arr) {
        if (distKm(c[0], c[1], fp.lon, fp.lat) <= g.radiusKm) return true;
      }
    }
  }
  return false;
}

/** 平方距离（km²），用于单点气泡判定（免开方） */
function distKm2(lon1: number, lat1: number, lon2: number, lat2: number): number {
  const dx = (lon1 - lon2) * 94.0;   // 扬州纬度下 1° 经度 ≈ 94 km
  const dy = (lat1 - lat2) * 111.0;
  return dx * dx + dy * dy;
}

/* ================= 弹窗 HTML ================= */

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function buildPopupHtml(props: ClickableProps, showActions = false): string {
  const name = props.name || "无名";
  const parts: string[] = [];

  parts.push(`<div class="ink-title">${escapeHtml(name)}</div>`);
  const badges: string[] = [];
  if (props.kind && props.kind !== props.name) {
    badges.push(`<span class="ink-badge">${escapeHtml(props.kind)}</span>`);
  }
  const groupLabel = props.group;
  if (groupLabel && groupLabel !== props.name && groupLabel !== props.kind) {
    badges.push(`<span class="ink-badge ink-badge-sub">${escapeHtml(groupLabel)}</span>`);
  }
  if (badges.length > 0) {
    parts.push(`<div class="ink-badges">${badges.join("")}</div>`);
  }

  if (props.name_modern && props.name_modern !== props.name) {
    parts.push(
      `<div class="ink-modern">本名：${escapeHtml(props.name_modern)}</div>`,
    );
  }

  // 操作按钮（进入 / 观察 / 回忆）——**只在探索地图**显示（showActions），点击由 ClickableLayer 统一监听
  if (props.hours && props.hours !== "全天") {
    parts.push(`<div class="ink-hours">开放：${escapeHtml(props.hours)}</div>`);
  }
  if (showActions) {
    const esc = escapeHtml(name);
    const kesc = escapeHtml(props.kind || "");
    const canDetail = !NO_DETAIL_KINDS.has(props.kind || "");
    const btns = [
      canDetail ? `<button class="ink-act" data-place="${esc}" data-kind="${kesc}" data-act="detail">详细</button>` : "",
      `<button class="ink-act" data-place="${esc}" data-kind="${kesc}" data-act="observe">观察</button>`,
      `<button class="ink-act" data-place="${esc}" data-kind="${kesc}" data-act="recall">回忆</button>`,
    ].filter(Boolean).join("");
    parts.push(`<div class="ink-actions">${btns}</div>`);
  }

  return `<div class="ink-popup-body">${parts.join("")}</div>`;
}

/** 不适合「详细」的地点类型（山水 / 路网 / 城墙等）；城门例外（要点「出城/入城」） */
const NO_DETAIL_KINDS = new Set([
  "山", "湖", "林", "洲", "坊", "坊巷", "大街", "官道", "城墙",
  "桥", "浮桥", "钟鼓楼", "高台", "坟地", "义冢", "村", "镇",
]);

/* ================= 不可见矢量命中层 ================= */

function clickStyle(feature?: Feature): L.PathOptions {
  const gtype = feature?.geometry?.type;
  if (gtype === "Point") {
    return { stroke: false };
  }
  if (gtype === "LineString" || gtype === "MultiLineString") {
    return { color: "#000000", weight: 12, opacity: 0 };
  }
  return { stroke: false, fill: true, fillColor: "#000000", fillOpacity: 0 };
}

function onEachFeature(feature: Feature, layer: L.Layer, showActions = false): void {
  const props = feature.properties as ClickableProps | null;
  if (props?.name) {
    layer.bindPopup(buildPopupHtml(props, showActions), { className: "ink-popup" });
  }
}

function pointToLayer(_feature: Feature, latlng: L.LatLng): L.CircleMarker {
  return L.circleMarker(latlng, {
    radius: 16,
    stroke: false,
    fill: true,
    fillColor: "#000000",
    fillOpacity: 0,
  });
}

/** 不可见命中层（任何 zoom 都可点）
 *
 * 性能关键（2026-09-16 定案：`?nohit=1` 不卡、`?nofog=1` 最流畅 → 就是这里）：
 *   1. **图层只挂一次**，不再依赖 `data`。—— 早先 effect 依赖 `[map, data, extents]`，
 *      迷雾每走一段就让 `data` 变成新数组，于是整个 canvas 层被拆掉重建
 *      （新建 renderer + clearLayers + addData 几百个 L.Path）→ 「新走的地方卡」。
 *   2. **增量增删**：Map<Feature, L.Layer>，只加新进视口的、只删离开视口的。
 *   3. `data` 变化时**不重建图层**，只按当前视口重新 diff（mode="data"）。
 */
function HitLayer({
  data, extents, showActions = false,
}: {
  data: FeatureCollection;
  extents: Map<Feature, FeatureExtent | null>;
  showActions?: boolean;
}) {
  const map = useMap();
  const showActionsRef = useRef(showActions);
  showActionsRef.current = showActions;

  // 用 ref 读最新值，让图层生命周期完全不依赖 data / extents
  const dataRef = useRef(data); dataRef.current = data;
  const extentsRef = useRef(extents); extentsRef.current = extents;

  const groupRef = useRef<L.LayerGroup | null>(null);
  const optionsRef = useRef<(L.GeoJSONOptions & L.PathOptions) | null>(null);
  const renderedRef = useRef<Map<Feature, L.Layer>>(new Map());
  const renderedBounds = useRef<L.LatLngBounds | null>(null);

  const clearAll = useCallback(() => {
    const group = groupRef.current;
    if (!group) return;
    renderedRef.current.forEach((l) => group.removeLayer(l));
    renderedRef.current.clear();
  }, []);

  /** mode: "viewport"=视口移动（可短路）｜"data"=内容变了（必重算，但不重建层）｜"clear"=整层重画 */
  const render = useCallback((mode: "viewport" | "data" | "clear" = "viewport") => {
    const group = groupRef.current;
    const options = optionsRef.current;
    if (!group || !options) return;

    const view = map.getBounds();
    // 视口还在上次渲染范围内 → 什么都不用做（内容变化用 mode="data" 绕过）
    if (mode === "viewport" && renderedBounds.current && renderedBounds.current.contains(view)) {
      return;
    }

    const t0 = performance.now();
    if (mode === "clear") clearAll();

    const b = view.pad(0.35);
    const w = b.getWest(), e = b.getEast(), s = b.getSouth(), n = b.getNorth();
    const ex = extentsRef.current;
    const rendered = renderedRef.current;
    const want = new Set<Feature>();

    for (const f of dataRef.current.features) {
      const x = ex.get(f);
      if (!x) continue;
      const [mnx, mny, mxx, mxy] = x.bb;
      if (mxx < w || mnx > e || mxy < s || mny > n) continue;
      want.add(f);
      if (rendered.has(f)) continue;              // 已在场上 → 复用
      const layer = L.geoJSON(f as unknown as GeoJsonObject, options);
      layer.addTo(group);
      rendered.set(f, layer);
    }

    // 删掉本次不再需要的
    rendered.forEach((layer, f) => {
      if (!want.has(f)) { group.removeLayer(layer); rendered.delete(f); }
    });

    mapStats.hits = rendered.size;
    mapStats.hitMs = performance.now() - t0;
    renderedBounds.current = b;
  }, [map, clearAll]);

  // 图层生命周期：只挂一次
  useEffect(() => {
    optionsRef.current = {
      style: clickStyle,
      pointToLayer,
      onEachFeature: (f, l) => onEachFeature(f, l, showActionsRef.current),
      renderer: L.canvas(),        // renderer 也只建一次
    };
    const group = L.layerGroup().addTo(map);
    groupRef.current = group;
    render("clear");

    let timer: number | null = null;
    const onMoveEnd = () => {
      if (timer !== null) window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        timer = null;
        render("viewport");
      }, 180);
    };
    const onZoomEnd = () => render("clear");

    map.on("moveend", onMoveEnd);
    map.on("zoomend", onZoomEnd);
    return () => {
      if (timer !== null) window.clearTimeout(timer);
      map.off("moveend", onMoveEnd);
      map.off("zoomend", onZoomEnd);
      clearAll();
      group.remove();
      groupRef.current = null;
      optionsRef.current = null;
      renderedBounds.current = null;
    };
  }, [map, render, clearAll]);

  // data / extents 变化（迷雾）：只重算，不重建图层
  useEffect(() => {
    render("data");
  }, [data, extents, render]);

  return null;
}

/* ================= 图标层（zoom >= 15，只渲染可视范围） ================= */

/** 图标文件：`public/mapicons/<键>/<day|night>.png`
 *  —— 每个建筑一套早晚两图（见 trpg-map/draw_tiles/icongen/README.md）。 */
function iconUrl(key: string, night: boolean) {
  return `${ICON_DIR}/${key}/${night ? "night" : "day"}.png`;
}

/** 加载一张图。**必须留住 Image 的引用**：不保留的话可能被 GC 掉，
 *  加载被中止，onload/onerror 都不触发 → 那个图标永远显示成棕色圆点。 */
const iconProbes: HTMLImageElement[] = [];

function loadOne(src: string): Promise<boolean> {
  return new Promise((resolve) => {
    const img = new Image();
    iconProbes.push(img);
    img.onload = () => resolve(true);
    img.onerror = () => resolve(false);
    img.src = src;
  });
}

/** 解析出**真正能用**的图标 URL，顺序：
 *   ① `<键>/<昼夜>.png`
 *   ② 同一张带 `?v=时间戳` —— 绕开浏览器里那条被缓存的失败响应
 *      （vite 曾把不存在的图标返回的 index.html 也按 immutable 缓存一年）
 *   ③ 另一昼夜的图（宁可看错时段，也别只剩一个棕色圆点）
 *  返回 null = 三种都失败 → 交给 missingIconFor 画兜底圆点。
 *
 *  ⚠️ 关键：返回值必须**带着成功的那个 URL**，渲染时要用它。
 *     早先版本只返回 true/false，渲染时仍用原 URL → 又被缓存里的失败响应挡住，
 *     于是 preload 明明成功、地图上却还是点。
 */
async function resolveIconUrl(key: string, night: boolean): Promise<string | null> {
  const src = iconUrl(key, night);
  if (await loadOne(src)) return src;
  const busted = `${src}?v=${Date.now()}`;
  if (await loadOne(busted)) {
    console.warn('[mapicon] 命中缓存里的失败响应，已改用带时间戳的 URL：', key, busted);
    return busted;
  }
  const other = iconUrl(key, !night);
  if (await loadOne(other)) {
    console.warn('[mapicon] 另一时段的图可用，先顶上：', key, other);
    return other;
  }
  console.error('[mapicon] 三种尝试都失败，改用兜底圆点：', key, src);
  return null;
}

function preloadIcons(keys: string[], night: boolean): Promise<Record<string, string | null>> {
  return Promise.all(
    keys.map(async (key) => [key, await resolveIconUrl(key, night)] as const),
  ).then((pairs) => Object.fromEntries(pairs));
}


/** 缺美术文件时的兜底小圆点 */
function missingIconFor(size: number) {
  return L.divIcon({
    className: "ink-icon ink-icon-missing",
    iconSize: [size * 0.5, size * 0.5],
    iconAnchor: [size * 0.25, size * 0.25],
  });
}

/** 图标像素尺寸随 zoom 变大（z15=40 … z18=64），避免 z18 下图标显得过小 */
function iconSizeFor(zoom: number) {
  const s = 40 + Math.max(0, zoom - MIN_ICON_ZOOM) * 8;
  return Math.round(Math.min(s, 72));
}

function iconPosition(f: Feature, p: ClickableProps): L.LatLng | null {
  const g = f.geometry;
  if (g.type === "Point") {
    const c = g.coordinates as number[];
    return L.latLng(c[1], c[0]);
  }
  if (
    (g.type === "Polygon" || g.type === "MultiPolygon") &&
    p.icon_lon != null &&
    p.icon_lat != null
  ) {
    return L.latLng(p.icon_lat, p.icon_lon);
  }
  return null;
}

function IconsLayer({ data, isNight, shichen, showActions = false }: { data: FeatureCollection; isNight: boolean; shichen: number; showActions?: boolean }) {
  const map = useMap();

  // 图标键集合：用**签名**稳定引用，否则 data 一变就重新 preload + 额外一次渲染
  const iconKeySig = useMemo(() => {
    const set = new Set<string>();
    data.features.forEach((f) => {
      const p = f.properties as ClickableProps;
      if (p?.icon) set.add(p.icon);
    });
    return [...set].sort().join(",");
  }, [data]);

  const iconKeys = useMemo(
    () => (iconKeySig ? iconKeySig.split(",") : []),
    [iconKeySig],
  );

  /** 键 → 真正可用的图片 URL（null = 三种尝试都失败，用兜底圆点） */
  const [iconSrc, setIconSrc] = useState<Record<string, string | null> | null>(null);

  useEffect(() => {
    let alive = true;
    preloadIcons(iconKeys, isNight).then((result) => {
      if (alive) setIconSrc(result);
    });
    return () => {
      alive = false;
    };
  }, [iconKeys, isNight]);

  // ---- 增量渲染 ----
  // 不再“data 一变就 clearLayers + 全量重建”（几百个 DOM marker + popup，
  // 在 4 倍放大瓦片下会触发整层重新栅格化 → 一帧上千毫秒的尖峰）。
  // 现在只增删差异：同一个 Feature 对象复用它的 marker。
  const groupRef = useRef<L.LayerGroup | null>(null);
  const renderedRef = useRef<Map<Feature, L.Marker>>(new Map());
  const cacheRef = useRef<Map<string, L.Icon | L.DivIcon>>(new Map());
  const styleRef = useRef({ zoom: -1, night: false });

  // 用 ref 读最新值，让 render 保持稳定（不让 useCallback 依赖变化）
  const dataRef = useRef(data); dataRef.current = data;
  const srcRef = useRef(iconSrc); srcRef.current = iconSrc;
  const nightRef = useRef(isNight); nightRef.current = isNight;
  const shichenRef = useRef(shichen); shichenRef.current = shichen;

  const clearAll = useCallback(() => {
    renderedRef.current.forEach((m) => m.remove());
    renderedRef.current.clear();
    mapStats.icons = 0;
  }, []);

  const render = useCallback((force = false) => {
    const group = groupRef.current;
    if (!group) return;

    const t0 = performance.now();
    const zoom = map.getZoom();
    const src = srcRef.current;
    const night = nightRef.current;

    // zoom / 昼夜 变了 → 图标尺寸或图片变了，必须整层重画
    if (zoom !== styleRef.current.zoom || night !== styleRef.current.night) {
      force = true;
    }

    if (zoom < MIN_ICON_ZOOM || !src) {
      clearAll();
      styleRef.current = { zoom, night };
      mapStats.iconMs = performance.now() - t0;
      return;
    }

    if (force) {
      clearAll();
      styleRef.current = { zoom, night };
    }

    const size = iconSizeFor(zoom);

    const getIcon = (key: string, open: boolean): L.Icon | L.DivIcon => {
      const url = src[key];
      // 缓存键带 url 与「是否营业」：夜色里打烊的店不发光（open=false → 无 is-open）
      const ck = `${key}|${size}|${night ? "n" : "d"}|${url ?? "∅"}|${open ? "o" : "c"}`;
      let icon = cacheRef.current.get(ck);
      if (!icon) {
        icon = url
          ? L.icon({
              iconUrl: url,
              iconSize: [size, size],
              iconAnchor: [size / 2, size / 2],
              popupAnchor: [0, -size / 2 - 4],
              // 黑夜时由 CSS 给「营业中」的图标发光（索引：GameController.css）
              className: "map-poi-icon" + (open ? " is-open" : ""),
            })
          : missingIconFor(size);
        cacheRef.current.set(ck, icon);
      }
      return icon;
    };

    const bounds = map.getBounds().pad(0.35);
    const rendered = renderedRef.current;
    const want = new Set<Feature>();

    for (const f of dataRef.current.features) {
      const p = f.properties as ClickableProps;
      if (!p?.name || !p.icon) continue;
      const pos = iconPosition(f, p);
      if (!pos || !bounds.contains(pos)) continue;

      want.add(f);
      const open = isOpenNow(p.hours, shichenRef.current);
      const icon = getIcon(p.icon, open);
      const existing = rendered.get(f);
      if (existing) {
        // 已在场上：若之前的图标是「兜底圆点」而现在真图到了 → 换掉（增量，不重建）
        if (existing.options.icon !== icon) existing.setIcon(icon);
        continue;
      }

      const marker = L.marker(pos, { icon, title: p.name });
      marker.bindPopup(buildPopupHtml(p, showActions), { className: "ink-popup" });
      marker.addTo(group);
      rendered.set(f, marker);
    }

    // 删掉本次不再需要的
    rendered.forEach((marker, f) => {
      if (!want.has(f)) {
        marker.remove();
        rendered.delete(f);
      }
    });

    mapStats.icons = rendered.size;
    mapStats.iconMs = performance.now() - t0;
  }, [map, clearAll]);

  // 图层生命周期：只挂一次
  useEffect(() => {
    const group = L.layerGroup().addTo(map);
    groupRef.current = group;
    render(true);

    let timer: number | null = null;
    const onMoveEnd = () => {
      if (timer !== null) window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        timer = null;
        render(false);
      }, 180);
    };
    const onZoomEnd = () => render(true);

    map.on("moveend", onMoveEnd);
    map.on("zoomend", onZoomEnd);
    return () => {
      if (timer !== null) window.clearTimeout(timer);
      map.off("moveend", onMoveEnd);
      map.off("zoomend", onZoomEnd);
      clearAll();
      group.remove();
      groupRef.current = null;
      styleRef.current = { zoom: -1, night: false };
    };
  }, [map, render, clearAll]);

  // data / 图标 / 昼夜 变化 → **增量**更新（只增删差异）
  useEffect(() => {
    render(false);
  }, [data, iconSrc, isNight, shichen, render]);

  return null;
}


/* ================= 主组件 ================= */

export default function ClickableLayer({
  mapId = MAP_ID,
  footprints,
  radiusKm = 0.5,
  isNight = false,
  shichen = -1,
  noFog = false,
  focus = null,
  hideIcons = false,
  hideHit = false,
  onPlaceAction,
  showActions = false,
}: ClickableLayerProps) {
  const map = useMap();
  const actRef = useRef(onPlaceAction);
  actRef.current = onPlaceAction;

  // 弹窗里的「进入 / 观察 / 回忆」按钮：统一监听（弹窗是 HTML 字符串，不是 React 节点）
  useEffect(() => {
    const h = (e: MouseEvent) => {
      const el = (e.target as HTMLElement)?.closest?.(".ink-act") as HTMLElement | null;
      if (!el) return;
      const place = el.getAttribute("data-place") || "";
      const act = el.getAttribute("data-act") || "";
      const kind = el.getAttribute("data-kind") || "";
      map.closePopup();
      actRef.current?.(place, act, kind);
    };
    document.addEventListener("click", h);
    return () => document.removeEventListener("click", h);
  }, [map]);

  // Esc：层级栈一层——气泡开着时才入栈（只关气泡，不动别的面板）
  const [popupOpen, setPopupOpen] = useState(false);
  useEffect(() => {
    const onOpen = () => setPopupOpen(true);
    const onClosed = () => setPopupOpen(false);
    map.on("popupopen", onOpen);
    map.on("popupclose", onClosed);
    return () => { map.off("popupopen", onOpen); map.off("popupclose", onClosed); };
  }, [map]);
  useEsc(() => map.closePopup(), popupOpen);

  const [features, setFeatures] = useState<Feature[] | null>(null);

  useEffect(() => {
    let alive = true;

    // 用「条数 + 首尾签名」判断是否需要换数据。
    // ⚠️ 早先只比 `prev.length === list.length`：重新导出 geojson 后条数常常不变，
    //    网络拿到的新数据被直接丢弃，浏览器 IndexedDB 里的旧数据一直生效
    //    （症状：地图上的图标/点位怎么刷新都不更新）。
    const fingerprint = (list: Feature[]) =>
      `${list.length}|${list[0]?.properties?.name ?? ""}|${list[list.length - 1]?.properties?.name ?? ""}|${list.filter((f) => f.properties?.icon).length}`;

    const apply = (list: Feature[]) => {
      setFeatures((prev) => {
        if (prev && fingerprint(prev) === fingerprint(list)) return prev;
        return list;
      });
    };

    // 1. 先读本地缓存，命中则立即渲染（省下载 + 解析）
    cacheGet(mapId, GEO_CACHE_KEY).then((entry) => {
      const e = entry as { version?: string; features?: Feature[] } | null;
      if (alive && e?.version === GEO_VERSION && Array.isArray(e.features)) {
        apply(e.features);
      }
    });

    // 2. 再请求网络，成功后回写缓存（内容不变则不触发重渲染）
    fetch(dataUrlFor(mapId, "clickable.geojson"))
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((json: FeatureCollection) => {
        if (Array.isArray(json?.features)) {
          cachePut(mapId, GEO_CACHE_KEY, {
            version: GEO_VERSION,
            features: json.features,
          });
          apply(json.features);
        }
      })
      .catch((err) => {
        console.error("加载可点击图层失败:", err);
      });

    return () => {
      alive = false;
    };
  }, [mapId]);

  // 要素「代表点 + 包围盒」只算一次（featureExtent 要遍历整个几何，重复算很贵）
  const extents = useMemo(() => {
    const m = new Map<Feature, FeatureExtent | null>();
    if (!features) return m;
    for (const f of features) m.set(f, featureExtent(f));
    return m;
  }, [features]);

  // 探索迷雾：只保留落在任一脚迹点半径内的要素
  const visibleFeatures = useMemo(() => {
    if (!features) return null;
    if (noFog) return features;        // 诊断开关 ?nofog=1：不过滤
    if (focus) {
      // 探索模式：**只留玩家附近的要素**（单点气泡，不累积足迹）
      const r2 = radiusKm * radiusKm;
      return features.filter((f) => {
        const e = extents.get(f);
        if (!e) return false;
        return distKm2(e.c[0], e.c[1], focus.lon, focus.lat) <= r2;
      });
    }
    if (!footprints) return features;  // 后端未启动 → 不启用迷雾
    const g = buildFootprintGrid(footprints, radiusKm);
    return features.filter((f) => {
      const e = extents.get(f);
      return e ? isExploredFast(e.c, g) : false;
    });
  }, [features, footprints, radiusKm, extents, noFog, focus]);

  // ⚠️ 必须在 early return **之前**调用（否则会
  //    “Rendered more hooks than during the previous render” → 白屏）。
  const data: FeatureCollection = useMemo(
    () => ({ type: "FeatureCollection", features: visibleFeatures ?? [] }),
    [visibleFeatures],
  );

  mapStats.visible = visibleFeatures ? visibleFeatures.length : 0;

  if (!visibleFeatures) {
    return null;
  }

  return (
    <>
      {!hideHit && <HitLayer data={data} extents={extents} showActions={showActions} />}
      {!hideIcons && <IconsLayer data={data} isNight={isNight} shichen={shichen} showActions={showActions} />}
    </>
  );
}
