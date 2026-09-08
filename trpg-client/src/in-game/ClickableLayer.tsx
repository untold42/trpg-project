import { useEffect, useMemo, useState } from "react";
import { useMap } from "react-leaflet";
import * as L from "leaflet";
import type { Feature, FeatureCollection } from "geojson";

const GEO_URL = "/data/clickable.geojson";
const ICON_DIR = "/mapicons";
const MIN_ICON_ZOOM = 15;

/* 本地缓存：clickable.geojson 存 IndexedDB，二次打开免下载、免解析 */
const CACHE_DB = "yangzhou-map-cache";
const CACHE_STORE = "kv";
const GEO_CACHE_KEY = "clickable-geojson";
const GEO_VERSION = "v1"; // 重新导出 clickable.geojson 后，若想强制前端刷新，bump 此值

interface Footprint {
  lon: number;
  lat: number;
  地点?: string;
}

interface ClickableLayerProps {
  /** 已探索足迹点；null/undefined = 不启用迷雾（显示全部） */
  footprints?: Footprint[] | null;
  /** 解锁半径（公里） */
  radiusKm?: number;
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
}

/* ================= IndexedDB 缓存 ================= */

function openCache(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(CACHE_DB, 1);
    req.onupgradeneeded = () => {
      if (!req.result.objectStoreNames.contains(CACHE_STORE)) {
        req.result.createObjectStore(CACHE_STORE);
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function cacheGet(key: string): Promise<unknown> {
  try {
    const db = await openCache();
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

async function cachePut(key: string, value: unknown): Promise<void> {
  try {
    const db = await openCache();
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

/** 求要素的“代表点”，用于判断它是否在某个足迹半径内 */
function featureCenter(f: Feature): [number, number] | null {
  const g = f.geometry;
  const p = f.properties as ClickableProps;

  if (g.type === "Point") {
    const c = g.coordinates as number[];
    return [c[0], c[1]];
  }
  // 面要素优先用导出时算好的内部代表点
  if (p.icon_lon != null && p.icon_lat != null) {
    return [p.icon_lon, p.icon_lat];
  }
  if (g.type === "GeometryCollection") {
    return null;
  }
  // 其它情况：收集所有坐标点取均值
  const pts: [number, number][] = [];
  const walk = (c: unknown) => {
    if (Array.isArray(c) && typeof c[0] === "number") {
      pts.push([c[0], c[1]]);
      return;
    }
    if (Array.isArray(c)) c.forEach(walk);
  };
  walk(g.coordinates);
  if (pts.length === 0) return null;
  const lon = pts.reduce((s, x) => s + x[0], 0) / pts.length;
  const lat = pts.reduce((s, x) => s + x[1], 0) / pts.length;
  return [lon, lat];
}

function isExplored(f: Feature, footprints: Footprint[], radiusKm: number): boolean {
  const c = featureCenter(f);
  if (!c) return false;
  for (const fp of footprints) {
    if (distKm(c[0], c[1], fp.lon, fp.lat) <= radiusKm) return true;
  }
  return false;
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

function buildPopupHtml(props: ClickableProps): string {
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

  return `<div class="ink-popup-body">${parts.join("")}</div>`;
}

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

function onEachFeature(feature: Feature, layer: L.Layer): void {
  const props = feature.properties as ClickableProps | null;
  if (props?.name) {
    layer.bindPopup(buildPopupHtml(props), { className: "ink-popup" });
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

/** 不可见命中层（任何 zoom 都可点） */
function HitLayer({ data }: { data: FeatureCollection }) {
  const map = useMap();

  useEffect(() => {
    const renderer = L.canvas();
    const options: L.GeoJSONOptions & L.PathOptions = {
      style: clickStyle,
      pointToLayer,
      onEachFeature,
      renderer,
    };
    const layer = L.geoJSON(data, options);
    layer.addTo(map);
    return () => {
      layer.remove();
    };
  }, [map, data]);

  return null;
}

/* ================= 图标层（zoom >= 15，只渲染可视范围） ================= */

function preloadIcons(keys: string[]): Promise<Record<string, boolean>> {
  return new Promise((resolve) => {
    let pending = keys.length;
    const result: Record<string, boolean> = {};
    if (pending === 0) {
      resolve(result);
      return;
    }
    keys.forEach((key) => {
      const img = new Image();
      img.onload = () => {
        result[key] = true;
        if (--pending === 0) resolve(result);
      };
      img.onerror = () => {
        result[key] = false;
        if (--pending === 0) resolve(result);
      };
      img.src = `${ICON_DIR}/${key}.png`;
    });
  });
}

/** 缺美术文件时的兜底小圆点 */
const missingIcon = L.divIcon({
  className: "ink-icon ink-icon-missing",
  iconSize: [14, 14],
  iconAnchor: [7, 7],
});

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

function IconsLayer({ data }: { data: FeatureCollection }) {
  const map = useMap();

  const iconKeys = useMemo(() => {
    const set = new Set<string>();
    data.features.forEach((f) => {
      const p = f.properties as ClickableProps;
      if (p?.icon) set.add(p.icon);
    });
    return [...set];
  }, [data]);

  const [icons, setIcons] = useState<Record<string, L.Icon | L.DivIcon>>({});

  useEffect(() => {
    let alive = true;
    preloadIcons(iconKeys).then((ok) => {
      if (!alive) return;
      const built: Record<string, L.Icon | L.DivIcon> = {};
      iconKeys.forEach((key) => {
        built[key] = ok[key]
          ? L.icon({
              iconUrl: `${ICON_DIR}/${key}.png`,
              iconSize: [36, 36],
              iconAnchor: [18, 18],
              popupAnchor: [0, -20],
            })
          : missingIcon;
      });
      setIcons(built);
    });
    return () => {
      alive = false;
    };
  }, [iconKeys]);

  useEffect(() => {
    if (Object.keys(icons).length === 0) return;

    const group = L.layerGroup().addTo(map);

    const render = () => {
      group.clearLayers();
      if (map.getZoom() < MIN_ICON_ZOOM) return;
      const bounds = map.getBounds().pad(0.25); // 向外扩 25% 预渲染边缘
      data.features.forEach((f) => {
        const p = f.properties as ClickableProps;
        if (!p?.name || !p.icon) return;
        const pos = iconPosition(f, p);
        if (!pos || !bounds.contains(pos)) return;
        const marker = L.marker(pos, {
          icon: icons[p.icon] ?? missingIcon,
          title: p.name,
        });
        marker.bindPopup(buildPopupHtml(p), { className: "ink-popup" });
        marker.addTo(group);
      });
    };

    render();
    map.on("moveend", render);
    map.on("zoomend", render);
    return () => {
      map.off("moveend", render);
      map.off("zoomend", render);
      group.remove();
    };
  }, [map, data, icons]);

  return null;
}

/* ================= 主组件 ================= */

export default function ClickableLayer({
  footprints,
  radiusKm = 0.5,
}: ClickableLayerProps) {
  const [features, setFeatures] = useState<Feature[] | null>(null);

  useEffect(() => {
    let alive = true;

    const apply = (list: Feature[]) => {
      setFeatures((prev) => {
        if (prev && prev.length === list.length) return prev;
        return list;
      });
    };

    // 1. 先读本地缓存，命中则立即渲染（省下载 + 解析）
    cacheGet(GEO_CACHE_KEY).then((entry) => {
      const e = entry as { version?: string; features?: Feature[] } | null;
      if (alive && e?.version === GEO_VERSION && Array.isArray(e.features)) {
        apply(e.features);
      }
    });

    // 2. 再请求网络，成功后回写缓存（内容不变则不触发重渲染）
    fetch(GEO_URL)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((json: FeatureCollection) => {
        if (Array.isArray(json?.features)) {
          cachePut(GEO_CACHE_KEY, {
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
  }, []);

  // 探索迷雾：只保留落在任一脚迹点半径内的要素
  const visibleFeatures = useMemo(() => {
    if (!features) return null;
    if (!footprints) return features; // 后端未启动 → 不启用迷雾
    return features.filter((f) => isExplored(f, footprints, radiusKm));
  }, [features, footprints, radiusKm]);

  if (!visibleFeatures) {
    return null;
  }

  const data: FeatureCollection = {
    type: "FeatureCollection",
    features: visibleFeatures,
  };

  return (
    <>
      <HitLayer data={data} />
      <IconsLayer data={data} />
    </>
  );
}
