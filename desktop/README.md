# Fihrist Desktop

A Tauri 2 desktop shell with a React 19 + TypeScript interface, for the same Sales OS backend
the web app uses. **It is at Phase 0.5: wrap mode.** The shell loads the deployed web
application (the real product — cashier, inbox, dashboard) into its `main` window and
injects a barcode-scan bridge, so a shop PC gets the whole system as a native app with
USB-scanner support. When no web-app URL resolves it falls back to the Phase 0 scaffold
SPA. See `docs/platform-boundary.md` (wrap-mode section), `docs/phase0-report.md` for what
Phase 0 delivered, and `docs/phase0-gates.md` for the gates that must keep passing.

Read the root [AGENTS.md](../AGENTS.md) first for the project map.

## Wrap mode in one paragraph

Window creation moved to Rust (`src-tauri/src/lib.rs`): `shell_url.rs` resolves the web-app
URL — settings file (`<app-config-dir>/fihrist-desktop.json`, key `web_app_url`) →
`FH_WEB_APP_URL` env → the reviewed default — and the window is built with the scan bridge
as an `initialization_script`. The bridge (`src/platform/scanner/scan_bridge.js`, one file
shared verbatim with the shell and its tests) listens globally for keyboard-wedge scanner
bursts (layout-immune `event.code` decoding — Arabic keyboards safe) and dispatches a DOM
`fihrist:scan` event; the web app's POS screen (`frontend/src/lib/scannerBridge.js`) feeds
that into its existing scan pipeline when the cashier's focus is outside a text field.
Auth is the web app's own (HttpOnly cookies, persisted by the WebView profile); there is
no native auth, no token store, and no Tauri IPC exposed to the remote page.

## The one rule that shapes the code

The React tree never calls `invoke()`, `fetch()`, opens an `EventSource`, or touches web
storage. It talks to a small "platform" interface; only `src/platform/tauri/` knows a Tauri
runtime exists. Browsers and tests run on an in-memory platform (`src/platform/noop.ts`).
Full explanation and how it is enforced: [docs/platform-boundary.md](docs/platform-boundary.md).

## Layout

| Path | What it holds |
|---|---|
| `src/main.tsx`, `src/app/` | Bootstrap, boot screen, error boundary, query client |
| `src/platform/` | The platform interfaces (`port.ts`), the browser/test platform (`noop.ts`), boot-config validation, `scanner/` (the scan bridge — plain JS shared with the Rust shell), and `tauri/` (the only place that touches Tauri) |
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
