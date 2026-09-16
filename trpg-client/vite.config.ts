import fs from 'node:fs'
import path from 'node:path'
import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'

// 给“内容不变”的静态资源加长缓存：瓦片（245MB）与图标文件名固定，
// 内容不变时浏览器直接读磁盘缓存，二次打开秒开。
//
// ⚠️ 这里的两个坑都踩过，别改回去：
//
//  1) **不能按状态码判断**。dev server 对不存在的路径返回的是 `index.html` + **200**
//     （SPA 回退），所以 404 根本不会出现；浏览器会把这段 HTML 当成图片缓存下来，
//     之后图标文件补上了也永远不再请求 → 地图上那几个点一直是棕色圆点。
//     → 正解：用 `fs.existsSync` 按**文件是否真的存在**决定缓存策略。
//
//  2) **必须抢在 Vite 内置静态中间件之前**。`configureServer` 里 `use()` 是追加在末尾的，
//     存在于 public/ 的文件会被内置静态中间件先响应掉，我们的头就永远设不上。
//     → 正解：`middlewares.stack.unshift(...)` 前置。
function cacheImmutableAssets(): Plugin {
  return {
    name: 'cache-immutable-assets',
    configureServer(server) {
      const publicDir = server.config.publicDir
      const handler = (req: { url?: string }, res: any, next: () => void) => {
        const url = (req.url || '').split('?')[0]
        if (url.startsWith('/tiles/') || url.startsWith('/mapicons/')) {
          let exists = false
          try {
            exists = fs.existsSync(path.join(publicDir, decodeURIComponent(url)))
          } catch {
            exists = false
          }
          res.setHeader(
            'Cache-Control',
            exists ? 'public, max-age=31536000, immutable' : 'no-store',
          )
        }
        next()
      }
      server.middlewares.stack.unshift({ route: '', handle: handler as never })
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), cacheImmutableAssets()],
  server: {
    watch: {
      // 瓦片是静态文件，不会在开发时改动，排除监视以免拖慢 Vite
      ignored: ['**/public/tiles/**'],
    },
  },
})
