import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 5173,
    // 开发代理打到 8001 开发后端（生产同事仍用 8000，勿在此改）
    proxy: {
      '/api': 'http://127.0.0.1:8001',
      '/static': 'http://127.0.0.1:8001',
      '/assets': 'http://127.0.0.1:8001',
      '/classic': 'http://127.0.0.1:8001',
    },
  },
  build: {
    outDir: resolve(__dirname, '../backend/static/vue'),
    emptyOutDir: true,
  },
})
