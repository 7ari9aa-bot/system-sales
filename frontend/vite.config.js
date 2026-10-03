import react from '@vitejs/plugin-react'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'

const dirname = path.dirname(fileURLToPath(import.meta.url));
const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000';

// الفرونت إند الجديد (بدون Base44) — alias @ على src، وفي التطوير
// طلبات /api و /auth بتتوجه للـbackend المحلي على :8000 عشان مفيش CORS.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(dirname, 'src') },
  },
  server: {
    port: 3000,
    proxy: {
      '/api': { target: apiProxyTarget, changeOrigin: true },
      '/auth': { target: apiProxyTarget, changeOrigin: true },
    },
  },
});
