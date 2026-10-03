# Frontend project instructions

## Project context

This directory contains the React 18 + Vite frontend for FIHRIST. The FastAPI backend and PostgreSQL/Supabase database are the source of business truth. Keep requests and mutations behind the existing authenticated API client in `src/lib/api.js`; do not add direct browser access to Supabase or local business-data substitutes.

Locale and page-direction choices are intentional. Preserve them unless the user asks to change them.

## Before changing the app

- Read the repository root `README.md` for architecture and local service setup.
- Read this directory's `README.md` for frontend API and deployment environment configuration.
- Inspect the existing route, API schema, and shared component patterns before changing a page.
- Do not report an API mutation as successful until the backend response confirms it.

## Local workflow

Run PostgreSQL, Redis, and the FastAPI backend before using the frontend for authenticated workflows. `npm run dev` serves Vite on port 3000 and proxies `/api` and `/auth` to `http://localhost:8000`.

## Verification

Run the relevant scripts in `package.json` after frontend changes. Browser checks use Playwright against the production Vite build; authenticated integration checks require an explicitly configured non-production backend and account.
