import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    port: 5173,
    host: true,
    // 文件监听配置：排除不需要监听的目录，避免 EMFILE 错误
    watch: {
      // 排除 node_modules 和其他不需要监听的目录
      ignored: [
        '**/node_modules/**',
        '**/.git/**',
        '**/dist/**',
        '**/.vite/**',
        '**/logs/**',
        '**/*.log'
      ],
      // 启用轮询模式（避免文件系统监听器打开过多文件导致 EMFILE 错误）
      // 轮询模式会定期检查文件变化，而不是使用文件系统事件监听
      usePolling: true,
      // 轮询间隔（毫秒）- 1000ms = 1秒检查一次
      interval: 1000
    },
    // 代理后端 API
    proxy: {
      '/api/ws': {
        target: 'ws://localhost:5858',
        ws: true
      },
      '/api/ytd': {
        target: 'http://localhost:5858',
        changeOrigin: true
      },
      '/api/dyd': {
        target: 'http://localhost:5858',
        changeOrigin: true
      },
      '/api': {
        target: 'http://localhost:5858',
        changeOrigin: true
      },
      // 视频流代理
      '/api/video': {
        target: 'http://localhost:5858',
        changeOrigin: true,
        rewrite: (path) => path
      },
      // 只代理 /downloads/ 下的静态资源，不代理 /downloads 路由本身
      // 使用正则匹配，确保有子路径才代理
      '^/downloads/.+': {
        target: 'http://localhost:5858',
        changeOrigin: true,
        rewrite: (path) => path  // 保持原路径
      },
      '/files': {
        target: 'http://localhost:5858',
        changeOrigin: true
      },
      // noVNC 代理
      '/novnc': {
        target: 'http://localhost:5858',
        changeOrigin: true
      },
      // WebSocket 代理（用于 noVNC）
      '/websockify': {
        target: 'ws://localhost:5858',
        ws: true,
        changeOrigin: true
      }
    }
  },
  build: {
    outDir: 'dist',
    // 使用 esbuild 进行压缩（默认，更快）
    minify: 'esbuild',
    // esbuild 配置
    esbuild: {
      drop: ['debugger']
    }
  }
})
