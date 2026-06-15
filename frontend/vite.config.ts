import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [vue()],
  server: {
    // 优先用 preview 分配的 PORT（autoPort），否则回落 5273；/api 走代理，端口与功能无关
    port: Number(process.env.PORT) || 5273,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
