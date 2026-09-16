/**
 * mapStats —— 地图各层的实时计数（仅用于 ?debug=1 的 HUD）
 *
 * 放在独立模块里，避免 Map.tsx ↔ ClickableLayer.tsx 循环 import。
 */
export const mapStats = {
  /** 图标层当前 DOM marker 数 */
  icons: 0,
  /** 命中层当前矢量要素数 */
  hits: 0,
  /** 迷雾过滤后可见要素数 */
  visible: 0,
  /** 命中层上次渲染耗时（ms） */
  hitMs: 0,
  /** 图标层上次渲染耗时（ms） */
  iconMs: 0,
};
