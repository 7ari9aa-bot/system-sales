# Fihrist Desktop

A Tauri 2 desktop shell with a React 19 + TypeScript interface, for the same Sales OS backend
the web app uses. **It is at Phase 0: a pinned, gated scaffold with no screens or features yet.**
The working product today is the web app in `../frontend/`. See `docs/phase0-report.md` for what
Phase 0 delivered and `docs/phase0-gates.md` for the gates it must keep passing.

Read the root [AGENTS.md](../AGENTS.md) first for the project map.

## The one rule that shapes the code

The React tree never calls `invoke()`, `fetch()`, opens an `EventSource`, or touches web
storage. It talks to a small "platform" interface; only `src/platform/tauri/` knows a Tauri
runtime exists. Browsers and tests run on an in-memory platform (`src/platform/noop.ts`).
Full explanation and how it is enforced: [docs/platform-boundary.md](docs/platform-boundary.md).

## Layout

| Path | What it holds |
|---|---|
| `src/main.tsx`, `src/app/` | Bootstrap, boot screen, error boundary, query client |
| `src/platform/` | The platform interfaces (`port.ts`), the browser/test platform (`noop.ts`), boot-config validation, and `tauri/` (the only place that touches Tauri) |
| `src/shared/` | Small utilities: i18n, logging, money |
| `src/features/`, `src/components/`, `src/state/` | Empty placeholders, each with a README, waiting for Phase 1 |
| `src-tauri/` | The Rust side: `tauri.conf.json`, capabilities, icons |
| `config/` | Scripts that fail the build on a boundary violation or a hard-coded host |
| `e2e/` | Placeholder (README only) for Phase 1 end-to-end tests |
| `docs/` | Boundary rules and the Phase 0 report and gates |
| `openapi.lock.json` | The backend API contract this app was built against |

## Commands

```bash
npm ci
npm run dev        # Vite dev server on http://127.0.0.1:5183
npm run verify     # everything CI runs: boundary, typecheck, lint, test, build, host check
npm run tauri      # Tauri CLI (needs the Rust toolchain)
```

Node 24 and Rust 1.98.1 are pinned (`package.json` `engines`, `rust-toolchain.toml`) so a red
build is never caused by a drifting toolchain. CI for this folder is
`.github/workflows/desktop-ci.yml`; it runs only when `desktop/**` changes, which is why the
main `ci.yml` never mentions it.
