import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// dev server 代理 /api 到后端，避免 CORS；SSE 同样走代理
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
