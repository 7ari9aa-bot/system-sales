import react from '@vitejs/plugin-react'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import fs from 'node:fs'
import { defineConfig, loadEnv } from 'vite'
import { APP_PATH_PREFIXES, legacyPublicRedirects } from './src/lib/public-seo-routes.mjs'

const dirname = path.dirname(fileURLToPath(import.meta.url));


/**
 * `vite preview` falls back to index.html for every unknown URL, which hides
 * the prerendered pages and the real 404 that Vercel serves in production.
 * This plugin makes preview behave like production: prerendered folders are
 * served as-is, SPA screens fall back to index.html, anything else is a 404.
 * It only runs for `vite preview`; the build and the deployed site never use it.
 */
function productionLikeRouting() {
  return {
    name: 'production-like-routing',
    configurePreviewServer(server) {
      const dist = path.resolve(dirname, 'dist');
      const appPrefix = new RegExp(`^/(${APP_PATH_PREFIXES.join('|')})(/|$)`);
      const legacy = new Map(legacyPublicRedirects().map((r) => [r.source, r.destination]));
      server.middlewares.use((req, res, next) => {
        const url = (req.url || '/').split('?')[0];
        if (!['GET', 'HEAD'].includes(req.method || 'GET') || url.startsWith('/api/') || url.startsWith('/auth/')) return next();
        if (path.extname(url) || url.endsWith('/')) return next();
        const moved = legacy.get(url);
        if (moved) {
          res.statusCode = 308;
          res.setHeader('location', moved);
          res.end();
          return;
        }
        const prerendered = path.join(dist, url, 'index.html');
        if (fs.existsSync(prerendered)) {
          res.setHeader('content-type', 'text/html; charset=utf-8');
          res.end(fs.readFileSync(prerendered));
          return;
        }
        if (appPrefix.test(url)) return next();
        res.statusCode = 404;
        res.setHeader('content-type', 'text/html; charset=utf-8');
        res.end(fs.readFileSync(path.join(dist, '404.html')));
      });
    },
  };
}

export default defineConfig(({ mode }) => {
  // Vite does NOT populate process.env from .env files while evaluating this
  // config — without loadEnv a developer's VITE_API_PROXY_TARGET in .env is
  // silently ignored and the proxy stays on the default. loadEnv reads the
  // same .env files the app code gets (third arg: all vars, not just VITE_).
  const env = loadEnv(mode, process.cwd(), '');
  const apiProxyTarget = env.VITE_API_PROXY_TARGET || process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000';
  // حارس أمان: أوضاع معاينة الواجهات تتخطى تسجيل الدخول، ولا تُبنى مع الإنتاج.
  const cashierPreview = (env.VITE_CASHIER_PREVIEW || process.env.VITE_CASHIER_PREVIEW) === '1';
  const dashboardPreview = (env.VITE_DASHBOARD_PREVIEW || process.env.VITE_DASHBOARD_PREVIEW) === '1';
  const deployEnv = process.env.VERCEL_ENV || '';
  const previewBypassRequested = cashierPreview || dashboardPreview;
  if (previewBypassRequested && (deployEnv === 'production' || (!deployEnv && process.env.NODE_ENV === 'production' && process.env.CI_ALLOW_CASHIER_PREVIEW !== '1' && process.env.VERCEL))) {
    throw new Error('Preview-only login bypasses must never be enabled for a production build.');
  }
  // على Vercel Preview فقط تتفعل معاينات الواجهات ببيانات تجريبية تلقائياً.
  // الإنتاج لا يعرّف هذه العلامات، لذلك تظل كل مسارات الداشبورد محمية.
  const autoPreview = deployEnv === 'preview';
  const apiProxy = {
    '/api': { target: apiProxyTarget, changeOrigin: true },
    '/auth': { target: apiProxyTarget, changeOrigin: true },
    // مواقع العملاء المنشورة بتتخدم من الـbackend على الجذر (docs/SITES_SERVING.md)
    '/sites': { target: apiProxyTarget, changeOrigin: true },
  };

  // الفرونت إند الجديد (بدون Base44) — alias @ على src، وفي التطوير
  // طلبات /api و /auth بتتوجه للـbackend المحلي على :8000 عشان مفيش CORS.
  return {
    plugins: [react(), productionLikeRouting()],
    define: {
      'import.meta.env.VITE_CASHIER_PREVIEW': JSON.stringify(cashierPreview || autoPreview ? '1' : ''),
      'import.meta.env.VITE_DASHBOARD_PREVIEW': JSON.stringify(dashboardPreview || autoPreview ? '1' : ''),
    },
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
