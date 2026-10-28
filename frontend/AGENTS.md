# Frontend project instructions

## Project context

This directory contains the React 18 + Vite frontend for FIHRIST. The FastAPI backend and PostgreSQL/Supabase database are the source of business truth. Keep requests and mutations behind the existing authenticated API client in `src/lib/api.js`; do not add direct browser access to Supabase or local business-data substitutes.

Locale and page-direction choices are intentional. Preserve them unless the user asks to change them.

## Before changing the app

- Read the repository root `README.md` for architecture and local service setup.
- Read this directory's `README.md` for frontend API and deployment environment configuration.
- Inspect the existing route, API schema, and shared component patterns before changing a page.
- Do not report an API mutation as successful until the backend response confirms it.

## Map of `src/`

| Path | What it holds |
|---|---|
| `main.jsx`, `App.jsx` | Entry point and every route. Pages are lazy-loaded; `/cashier/*` mounts the cashier app. |
| `pages/` | One file per screen (Inbox, Customers, AI, Analytics, Home...). `pages/settings/` has one file per settings tab. |
| `cashier/` | The cashier (POS) as its own app: about 260 files, larger than the rest of the frontend. It has its own `components/`, `lib/`, `api/` and `routes/`, and its own `cashier.css`. Entry: `cashier/CashierApp.jsx`. |
| `components/` | Shared pieces grouped by feature (`inbox/`, `customers/`, `dashboard/`, `settings/`). `components/ui/` is the shadcn/Radix kit; many of its files are unused on purpose, so do not delete them to tidy up. |
| `lib/` | `api.js` (the only place that calls `fetch`; everything else goes through it, so add endpoints there or in `cashier/api/`), `AuthContext.jsx`, `i18n/` (`ar.js` and `en.js`, keep them in step), `query-client.js`. |
| `hooks/` | Data hooks (`useCustomers`, `useApprovals`, `useSalesStats`...). |

The cashier has no mock data any more; it reads the real backend through `cashier/api/`.

Marketing is not in the first release. `pages/Marketing*.jsx`, `pages/Website.jsx` and
`pages/marketing/` are kept but unrouted: old links land on the dashboard and `/website` shows
"coming soon". Do not delete them without asking, and do not mistake them for live code.

Tests: `*.test.js` sit next to the code (Vitest, `npm test`). Browser tests are in `e2e/`
(Playwright, `npm run test:e2e`).

## Local workflow

Run PostgreSQL, Redis, and the FastAPI backend before using the frontend for authenticated workflows. `npm run dev` serves Vite on port 3000 and proxies `/api` and `/auth` to `http://localhost:8000`.

## Verification

Run the relevant scripts in `package.json` after frontend changes. Browser checks use Playwright against the production Vite build; authenticated integration checks require an explicitly configured non-production backend and account.
