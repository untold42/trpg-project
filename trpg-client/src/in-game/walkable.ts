// walkable.ts
// ===========
// 「体积碰撞」：WASD 探索时的可走判定。
//
// 规则（2026-09-16 规定）：
//   - 除**水域**和**城墙**外，其余一律可走；
//   - 路 ∩ 城墙：默认不可走，只有**城门 25m 半径**是通道；
//   - 路 ∩ 水域：默认路可走（路廊道内可通行）；
//   - 有**桥**：桥 100m 半径内可走。
//
// 另提供**地形步速倍率** `speedMultiplier(lon, lat)`：
//   - 有路走 → 路倍率（官道 1.15 / 坊巷 1.0），不算钻林子；
//   - 否则取最重的一层地形（林地 0.6 / 滩涂 0.45 / 山岩·山地 0.35 …）；
//   - 无地形无路 → 1.0（平地基准）。
//
// 数据由 `trpg-map/draw_tiles/export_walkable.py` 生成 →
//   `public/data/<map_id>/walkable.geojson`（水域 / 城墙 / 城门 / 桥 / 道路 / 地形）。
//
// 性能：水域、道路、地形建「0.005° 网格索引」，每次只测附近的要素；
//       点-多边形用射线法，点-折线用米制点段距离。未加载完成时一律放行。

import { dataUrlFor, MAP_ID } from "./mapId";

export type Pt = [number, number];

// ---- 规则参数（米）----
const GATE_R = 25;      // 城门通道半径
const BRIDGE_R = 100;   // 桥可走半径
const WALL_HALF = 12;   // 城墙阻挡半宽（城墙中心线 ±）
const ROAD_HALF = 6;    // 路廊道半宽（路∩水域时可走）

const M_PER_DEG_LAT = 111320;
const CELL = 0.005;     // 网格索引边长（度）

type Ring = Pt[];
type Poly = { rings: Ring[]; bb: BBox };
type Line = { pts: Pt[]; bb: BBox; mult: number; kind: string };
type Zone = { rings: Ring[]; bb: BBox; mult: number; kind: string };
type BBox = [number, number, number, number]; // [minLon, minLat, maxLon, maxLat]
type Gate = { lon: number; lat: number; hours: string };

type Index = {
  water: Poly[];
  waterGrid: Map<string, number[]>;
  roads: Line[];
  roadGrid: Map<string, number[]>;
  terrain: Zone[];
  terrainGrid: Map<string, number[]>;
  wall: Pt[];
  wallBB: BBox | null;
  gates: Gate[];
  bridges: Pt[];
};

// ---- 当前游戏时辰（由 GameController 通过 setShichen 同步）----
let CUR_SHICHEN = -1;
const SHICHEN_NAMES = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"];

/** 同步当前时辰（城门开闭判断用） */
export function setShichen(i: number): void {
  CUR_SHICHEN = i;
}

/** 时段字符串（如「卯-申」「全天」）在 shichen 是否开放 */
function isOpenHours(hours: string, shichen: number): boolean {
  if (!hours || hours === "全天" || shichen < 0) return true;
  const parts = hours.split("-");
  if (parts.length !== 2) return true;
  const s = SHICHEN_NAMES.indexOf(parts[0].trim());
  const e = SHICHEN_NAMES.indexOf(parts[1].trim());
  if (s < 0 || e < 0) return true;
  return s <= e ? (shichen >= s && shichen <= e) : (shichen >= s || shichen <= e);
}

let IDX: Index | null = null;
const CACHE = new Map<string, Index>();          // mapId -> 已构好的索引
const LOADING = new Map<string, Promise<void>>();  // mapId -> 进行中的请求

/** 碰撞数据是否已就绪（未就绪时 isWalkable 一律放行） */
export function walkableReady(): boolean {
  return IDX !== null;
}

// ------------------------------------------------------------
// 几何工具
// ------------------------------------------------------------
function toM(lon: number, lat: number, lon0: number, lat0: number): [number, number] {
  const k = Math.cos((lat0 * Math.PI) / 180);
  return [(lon - lon0) * M_PER_DEG_LAT * k, (lat - lat0) * M_PER_DEG_LAT];
}

function distM(lon1: number, lat1: number, lon2: number, lat2: number): number {
  const [x, y] = toM(lon2, lat2, lon1, lat1);
  return Math.hypot(x, y);
}

/** 点到线段（米制，以 px,py 为原点的局部坐标系） */
function segDistM(px: number, py: number, ax: number, ay: number,
                  bx: number, by: number): number {
  const dx = bx - ax, dy = by - ay;
  const l2 = dx * dx + dy * dy;
  let t = l2 > 0 ? ((px - ax) * dx + (py - ay) * dy) / l2 : 0;
  t = t < 0 ? 0 : t > 1 ? 1 : t;
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
}

/** 点是否在某条折线 maxM 米内 */
function nearPolyline(lon: number, lat: number, pts: Pt[], maxM: number): boolean {
  const px = 0, py = 0; // 原点即查询点（toM 已转为以查询点为原点的米制坐标）
  for (let i = 0; i + 1 < pts.length; i++) {
    const [ax, ay] = toM(pts[i][0], pts[i][1], lon, lat);
    const [bx, by] = toM(pts[i + 1][0], pts[i + 1][1], lon, lat);
    if (segDistM(px, py, ax, ay, bx, by) <= maxM) return true;
  }
  return false;
}

function inRing(x: number, y: number, ring: Ring): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0], yi = ring[i][1];
    const xj = ring[j][0], yj = ring[j][1];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) {
      inside = !inside;
    }
  }
  return inside;
}

function inPoly(x: number, y: number, p: Poly): boolean {
  if (!inRing(x, y, p.rings[0])) return false;
  for (let k = 1; k < p.rings.length; k++) {
    if (inRing(x, y, p.rings[k])) return false; // 洞
  }
  return true;
}

// ------------------------------------------------------------
// 构建索引
// ------------------------------------------------------------
function bboxOf(coords: unknown): BBox | null {
  let mnx = Infinity, mny = Infinity, mxx = -Infinity, mxy = -Infinity;
  const walk = (c: unknown): void => {
    if (Array.isArray(c) && typeof c[0] === "number") {
      const lon = c[0] as number, lat = c[1] as number;
      if (lon < mnx) mnx = lon;
      if (lon > mxx) mxx = lon;
      if (lat < mny) mny = lat;
      if (lat > mxy) mxy = lat;
      return;
    }
    if (Array.isArray(c)) c.forEach(walk);
  };
  walk(coords);
  return mnx === Infinity ? null : [mnx, mny, mxx, mxy];
}

function gridKeys(bb: BBox): string[] {
  const keys: string[] = [];
  const ix0 = Math.floor(bb[0] / CELL), ix1 = Math.floor(bb[2] / CELL);
  const iy0 = Math.floor(bb[1] / CELL), iy1 = Math.floor(bb[3] / CELL);
  for (let ix = ix0; ix <= ix1; ix++) {
    for (let iy = iy0; iy <= iy1; iy++) keys.push(ix + "|" + iy);
  }
  return keys;
}

function pushGrid(grid: Map<string, number[]>, bb: BBox, idx: number): void {
  for (const key of gridKeys(bb)) {
    const arr = grid.get(key);
    if (arr) arr.push(idx);
    else grid.set(key, [idx]);
  }
}

function polyRings(coords: unknown): Ring[] {
  return (coords as number[][][]).map((r) => r as Ring);
}

function build(features: GeoJSONFeature[]): Index {
  const water: Poly[] = [];
  const roads: Line[] = [];
  const terrain: Zone[] = [];
  const gates: Gate[] = [];
  const bridges: Pt[] = [];
  let wall: Pt[] = [];
  const waterGrid = new Map<string, number[]>();
  const roadGrid = new Map<string, number[]>();
  const terrainGrid = new Map<string, number[]>();

  for (const f of features) {
    const props = f.properties as { t?: string; mult?: number; kind?: string; hours?: string } | null;
    const t = props?.t;
    const g = f.geometry;
    if (!g) continue;

    if (t === "water" && (g.type === "Polygon" || g.type === "MultiPolygon")) {
      const polys: number[][][][] =
        g.type === "Polygon" ? [g.coordinates as number[][][]] : (g.coordinates as number[][][][]);
      for (const pl of polys) {
        const bb = bboxOf(pl);
        if (!bb) continue;
        const p: Poly = { rings: polyRings(pl), bb };
        pushGrid(waterGrid, bb, water.length);
        water.push(p);
      }
    } else if (t === "terrain" && (g.type === "Polygon" || g.type === "MultiPolygon")) {
      const mult = typeof props?.mult === "number" ? props.mult : 1;
      const kind = String(props?.kind || "地形");
      const polys: number[][][][] =
        g.type === "Polygon" ? [g.coordinates as number[][][]] : (g.coordinates as number[][][][]);
      for (const pl of polys) {
        const bb = bboxOf(pl);
        if (!bb) continue;
        const z: Zone = { rings: polyRings(pl), bb, mult, kind };
        pushGrid(terrainGrid, bb, terrain.length);
        terrain.push(z);
      }
    } else if (t === "road" && (g.type === "LineString" || g.type === "MultiLineString")) {
      const mult = typeof props?.mult === "number" ? props.mult : 1;
      const kind = String(props?.kind || "");
      const lines: number[][][] =
        g.type === "LineString" ? [g.coordinates as number[][]] : (g.coordinates as number[][][]);
      for (const ln of lines) {
        const bb = bboxOf(ln);
        if (!bb) continue;
        const L: Line = { pts: ln as Pt[], bb, mult, kind };
        pushGrid(roadGrid, bb, roads.length);
        roads.push(L);
      }
    } else if (t === "wall" && (g.type === "LineString" || g.type === "MultiLineString")) {
      const lines: number[][][] =
        g.type === "LineString" ? [g.coordinates as number[][]] : (g.coordinates as number[][][]);
      if (lines[0]) wall = lines[0] as Pt[];
    } else if (t === "gate" && g.type === "Point") {
      const co = g.coordinates as Pt;
      const hours = String(props?.hours || "");
      gates.push({ lon: co[0], lat: co[1], hours });
    } else if (t === "bridge" && g.type === "Point") {
      bridges.push(g.coordinates as Pt);
    }
  }

  return {
    water, waterGrid, roads, roadGrid, terrain, terrainGrid,
    wall, wallBB: wall.length ? bboxOf(wall) : null,
    gates, bridges,
  };
}

/** 加载某张地图的碰撞数据（按 mapId 缓存；重复调用只发一次请求）。
 *
 * 加载完就把该地图设为「当前生效」（模块级 `IDX`），供 `isWalkable` / `terrainAt` 使用。
 *
 * ⚠️ **只有 WASD 探索地图才该调它**——总览图（只看不走到）不要调，
 * 否则会把 `IDX` 换成另一座城的几何，导致探索时碰撞全错。
 */
export function loadWalkable(mapId: string = MAP_ID): Promise<void> {
  // ① 已构好：直接把 IDX 切回来（不切的话，看过别的地图后碰撞会留在那一张）
  const cached = CACHE.get(mapId);
  if (cached) {
    IDX = cached;
    return Promise.resolve();
  }
  // ② 正在请求：等它（resolve 时会自己设 IDX）
  const hit = LOADING.get(mapId);
  if (hit) return hit;
  // ③ 首次：拉数据
  const p = fetch(dataUrlFor(mapId, "walkable.geojson"))
    .then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    })
    .then((json: { features?: GeoJSONFeature[] }) => {
      const idx = build(json.features ?? []);
      CACHE.set(mapId, idx);
      IDX = idx;
    })
    .catch((err) => {
      console.error("[walkable] 加载失败，碰撞不生效:", err);
    });
  LOADING.set(mapId, p);
  return p;
}

// ------------------------------------------------------------
// 判定
// ------------------------------------------------------------
function inWater(lon: number, lat: number, idx: Index): boolean {
  const key = Math.floor(lon / CELL) + "|" + Math.floor(lat / CELL);
  const cand = idx.waterGrid.get(key);
  if (!cand) return false;
  for (const i of cand) {
    const p = idx.water[i];
    const [a, b, c, d] = p.bb;
    if (lon < a || lon > c || lat < b || lat > d) continue;
    if (inPoly(lon, lat, p)) return true;
  }
  return false;
}

function nearRoad(lon: number, lat: number, idx: Index): boolean {
  const key = Math.floor(lon / CELL) + "|" + Math.floor(lat / CELL);
  const cand = idx.roadGrid.get(key);
  if (!cand) return false;
  for (const i of cand) {
    const L = idx.roads[i];
    const [a, b, c, d] = L.bb;
    if (lon < a || lon > c || lat < b || lat > d) continue;
    if (nearPolyline(lon, lat, L.pts, ROAD_HALF)) return true;
  }
  return false;
}

function inBB(lon: number, lat: number, bb: BBox, padM: number): boolean {
  const pad = padM / M_PER_DEG_LAT;
  return lon >= bb[0] - pad && lon <= bb[2] + pad &&
         lat >= bb[1] - pad && lat <= bb[3] + pad;
}

/** 最近一次判定是否被阻挡（供 UI 反馈） */
export let lastBlocked = false;

/**
 * 该点的**地形步速倍率**（乘在基础步速上，1.0 = 平地）。
 *
 * 优先级：
 *   1. **路**：在路廊道内 → 用路的倍率（官道 1.15 / 坊巷 1.0），不算钻林子；
 *   2. **地形**：否则取覆盖该点的**最重**一层（倍率最小那层）；
 *   3. 都没命中 → 1.0。
 */
export type TerrainInfo = { mult: number; kind: string };

/**
 * 该点的地形信息（步速倍率 + 名称）。
 *
 * 优先级：
 *   1. **路**：在路廊道内 → 用路的倍率（官道 1.15 / 坊巷 1.0），不算钻林子；
 *   2. **地形**：否则取覆盖该点的**最重**一层（倍率最小那层）；
 *   3. 都没命中 → 1.0 / 平地。
 */
export function terrainAt(lon: number, lat: number): TerrainInfo {
  const idx = IDX;
  if (!idx) return { mult: 1, kind: "" };
  const key = Math.floor(lon / CELL) + "|" + Math.floor(lat / CELL);

  // 1) 路优先
  const rc = idx.roadGrid.get(key);
  if (rc) {
    for (const i of rc) {
      const L = idx.roads[i];
      const [a, b, c, d] = L.bb;
      if (lon < a || lon > c || lat < b || lat > d) continue;
      if (nearPolyline(lon, lat, L.pts, ROAD_HALF)) {
        return { mult: L.mult, kind: L.kind || "道路" };
      }
    }
  }

  // 2) 地形：取倍率最小（最重）的一层
  let m = 1;
  let kind = "";
  const tc = idx.terrainGrid.get(key);
  if (tc) {
    for (const i of tc) {
      const z = idx.terrain[i];
      const [a, b, c, d] = z.bb;
      if (lon < a || lon > c || lat < b || lat > d) continue;
      if (z.mult < m && inPoly(lon, lat, z)) {
        m = z.mult;
        kind = z.kind;
      }
    }
  }
  return { mult: m, kind };
}

/** 该点的地形步速倍率（乘在基础步速上，1.0 = 平地） */
export function speedMultiplier(lon: number, lat: number): number {
  return terrainAt(lon, lat).mult;
}

/**
 * 该点是否可走。未加载完数据时返回 true（不阻挡），避免开局走不动。
 *
 * 顺序很重要：
 *   1. **城墙**：中心线 ± WALL_HALF 内不可走；**只有城门 25m 内**放行。
 *      （桥/路不能破墙 —— 桥只作用于水域）
 *   2. **水域**：默认不可走；**桥 100m 内** 或 **路廊道内**可走。
 *   3. 其余一律可走。
 */
export function isWalkable(lon: number, lat: number): boolean {
  const idx = IDX;
  if (!idx) {
    lastBlocked = false;
    return true;
  }

  const nearGate = (): boolean => {
    // 城门通道：25m 内 **且城门开着** 才算能过（城中城门默认 卯-申，闭门后走不了）
    for (const g of idx.gates) {
      if (distM(lon, lat, g.lon, g.lat) <= GATE_R && isOpenHours(g.hours, CUR_SHICHEN)) {
        return true;
      }
    }
    return false;
  };

  // 1) 城墙（城门通道）
  if (idx.wallBB && inBB(lon, lat, idx.wallBB, WALL_HALF)) {
    if (nearPolyline(lon, lat, idx.wall, WALL_HALF)) {
      const ok = nearGate();
      lastBlocked = !ok;
      return ok;
    }
  }

  // 2) 水域（桥 / 路通道）
  if (inWater(lon, lat, idx)) {
    for (const b of idx.bridges) {
      if (distM(lon, lat, b[0], b[1]) <= BRIDGE_R) {
        lastBlocked = false;
        return true;
      }
    }
    if (nearRoad(lon, lat, idx)) {
      lastBlocked = false;
      return true;
    }
    lastBlocked = true;
    return false;
  }

  lastBlocked = false;
  return true;
}

// ---- 最小 GeoJSON 类型（避免引入 @types/geojson 依赖）----
interface GeoJSONFeature {
  type: "Feature";
  properties: Record<string, unknown> | null;
  geometry: {
    type: string;
    coordinates: unknown;
  } | null;
}
