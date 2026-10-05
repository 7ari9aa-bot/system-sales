import react from '@vitejs/plugin-react'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig, loadEnv } from 'vite'

const dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig(({ mode }) => {
  // Vite does NOT populate process.env from .env files while evaluating this
  // config — without loadEnv a developer's VITE_API_PROXY_TARGET in .env is
  // silently ignored and the proxy stays on the default. loadEnv reads the
  // same .env files the app code gets (third arg: all vars, not just VITE_).
  const env = loadEnv(mode, process.cwd(), '');
  const apiProxyTarget = env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000';
  const apiProxy = {
    '/api': { target: apiProxyTarget, changeOrigin: true },
    '/auth': { target: apiProxyTarget, changeOrigin: true },
  };

  // الفرونت إند الجديد (بدون Base44) — alias @ على src، وفي التطوير
  // طلبات /api و /auth بتتوجه للـbackend المحلي على :8000 عشان مفيش CORS.
  return {
    plugins: [react()],
    resolve: {
      alias: { '@': path.resolve(dirname, 'src') },
    },
    server: {
      port: 3000,
      proxy: apiProxy,
    },
    // Keep API calls same-origin in browser checks against the built app too.
    preview: {
      proxy: apiProxy,
    },
  };
});
