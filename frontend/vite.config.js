import react from '@vitejs/plugin-react'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'

const dirname = path.dirname(fileURLToPath(import.meta.url));

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
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      '/auth': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
});
