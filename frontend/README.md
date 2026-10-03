# FIHRIST Web

React 18 + Vite frontend for the FIHRIST sales platform. Business data and mutations go through the authenticated FastAPI API; the browser does not connect directly to Supabase or own business data.

## Local development

Start the local services and backend first, following the repository root [README](../README.md). The backend should listen on `http://localhost:8000` and use a local PostgreSQL database and Redis instance.

Then run the frontend:

```bash
npm ci
npm run dev
```

Vite serves the app at `http://localhost:3000` and proxies `/api` and `/auth` to `http://127.0.0.1:8000` by default. Set `VITE_API_PROXY_TARGET` to a different backend origin if that port is already in use. To bypass the proxy, set `VITE_API_URL` to the backend's `/api/v1` URL; that API must allow the frontend origin through CORS.

## API and deployment environments

`src/lib/api.js` defaults to the same-origin `/api/v1` path. Vercel proxies that path to the backend, so bearer tokens and API requests remain same-origin in the browser.

The Vercel config uses `VERCEL_ENV` and the optional `BACKEND_API_ORIGIN`:

- Production uses the current production API origin unless a Production-only `BACKEND_API_ORIGIN` overrides it.
- Preview deployments do not proxy API requests by default. They must not use production data for QA.
- When a staging backend is available, set `BACKEND_API_ORIGIN` for the Vercel Preview environment to that HTTPS origin. The config rejects the production API origin in non-production environments.

Do not put API credentials, Supabase keys, or service-role values in `VITE_*` variables or frontend source. Only public origins belong in `BACKEND_API_ORIGIN`.

## Checks

```bash
npm run check:headers
npm run lint
npm run build
npm run test:e2e
```
