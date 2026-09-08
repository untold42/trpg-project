import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'

// 给“内容不可变”的静态资源加长缓存头：
// 瓦片（245MB）与图标文件名固定，内容不变时浏览器直接读磁盘缓存，二次打开秒开。
// 注意：重新生成瓦片/图标后，若浏览器仍用旧缓存，可 Ctrl+Shift+R 强刷一次。
function cacheImmutableAssets(): Plugin {
  return {
    name: 'cache-immutable-assets',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = (req.url || '').split('?')[0]
        if (url.startsWith('/tiles/') || url.startsWith('/mapicons/')) {
          res.setHeader('Cache-Control', 'public, max-age=31536000, immutable')
        }
        next()
      })
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
