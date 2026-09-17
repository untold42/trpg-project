// mapId.ts
// ========
// 当前地图（多城市）。
//
// **真相源是后端**（`游戏数据/地图设置.json`，前端主菜单「环境设定 → 地图」改它）。
// 这里只是把它落到 URL / localStorage，好让瓦片与数据 URL 能同步切换：
//
//   public/tiles/<map_id>/{z}/{x}/{y}.png        瓦片
//   public/data/<map_id>/clickable.geojson       点击层
//   public/data/<map_id>/walkable.geojson        碰撞/地形层
//
// 启动时若 URL 上没有 `?map=`，`main.tsx` 会先问一次后端再渲染（见 bootMapSync）。

const _Q = new URLSearchParams(window.location.search);

const LS_KEY = "trpg-map";

const _fromLS = (() => {
  try {
    return localStorage.getItem(LS_KEY);
  } catch {
    return null;
  }
})();

/** 默认查看的地图 id（`?map=` > localStorage > yangzhou）。
 *  注意：**游戏城市不是它** —— 游戏城市由玩家坐标决定（后端 map_settings.get_map）。 */
export const MAP_ID: string = _Q.get("map") || _fromLS || "yangzhou";

/** 任意地图的瓦片 url 模板 */
export function tileUrlFor(mapId: string): string {
  return `/tiles/${mapId}/{z}/{x}/{y}.png`;
}

/** 任意地图的 public/data 下文件 */
export function dataUrlFor(mapId: string, name: string): string {
  return `/data/${mapId}/${name}`;
}

/** 默认地图的瓦片 url 模板 */
export const TILE_URL = tileUrlFor(MAP_ID);

/** 默认地图的 public/data 下文件 */
export function dataUrl(name: string): string {
  return dataUrlFor(MAP_ID, name);
}

/** 记住选择（下次没带 ?map= 时用） */
export function rememberMap(id: string): void {
  try {
    localStorage.setItem(LS_KEY, id);
  } catch {
    /* 隐私模式等：忽略 */
  }
}
