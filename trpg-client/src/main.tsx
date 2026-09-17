import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { API } from './api.ts'

// ------------------------------------------------------------
// 启动时同步「当前地图」：真相源是后端的 游戏数据/地图设置.json
// （前端主菜单「环境设定 → 地图」改它）。
//
// URL 上没有 ?map= 时先问一次后端，拿到就带着参数重载 —— 这样切图只需要在一个
// 地方改（UI 或 .env），前端自动跟上，不会出现「后端查岳阳、前端画扬州」的错位。
// 后端没起就用默认 yangzhou，不阻塞。
// ------------------------------------------------------------
async function bootMapSync(): Promise<void> {
  if (new URLSearchParams(window.location.search).get('map')) return;
  try {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), 1200);
    const r = await fetch(`${API}/maps`, { signal: ctl.signal });
    clearTimeout(t);
    const d = await r.json();
    if (d?.current) {
      window.location.replace(`?map=${d.current}`);
      return; // 页面即将重载，不再渲染
    }
  } catch {
    /* 后端没起：用默认地图 */
  }
}

bootMapSync().finally(() => {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
})
