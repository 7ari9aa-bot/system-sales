# Phase 0 — what the gates are, and what they prove

Phase 0 ships no screens. It ships the things every later phase has to inherit
whether it wants them or not: a pinned toolchain, a platform boundary that cannot
be crossed by accident, an error surface, a redacted log, and a CI job that fails
on the same rules on Windows and macOS.

Run everything in one go from `desktop/`:

```
npm run verify
```

That is `boundary → typecheck → lint → test → build → no-hardcoded-host`, chained
with `&&`, so the first gate that fails stops the chain.

| command | what it actually proves |
|---|---|
| `npm run boundary` | `config/check-platform-boundary.mjs` walks `src/` and fails on `invoke()`, `fetch()`, `new EventSource`, web storage, an `@tauri-apps/*` import, or an `any` in the contract layer — outside `src/platform/tauri/`. Comments are stripped first, so a doc line that says "never call fetch()" is not a violation |
| `npm run typecheck` | `tsc --noEmit` with `strict` + `noUncheckedIndexedAccess`, so an unhandled `undefined` from a list index is a build error, not a Friday |
| `npm run lint` | ESLint 10 flat config, type-aware rules for `src/`, `--max-warnings=0`, plus the same bans as the script above expressed as lint rules (belt and braces: the script catches a file the lint config never saw) |
| `npm run test` | Vitest, jsdom, no Tauri runtime — which is the point: the whole UI layer is exercised without one |
| `npm run build` | `tsc --noEmit && vite build` → a static SPA in `dist/`. No SSR, no server components, no API routes |
| `node config/check-no-hardcoded-host.mjs` | the built bundle contains no server address. `FH_API_BASE_URL` is runtime configuration, and a `.env` that was present at build time cannot silently become a shipped host |

## Gates that CI owns and this machine cannot run

The Phase 0 exit criteria in the mission include `cargo fmt`, `cargo clippy`,
`cargo test` and `tauri build` for Windows and macOS. **None of them were run
locally for this commit: there is no Rust toolchain on this machine**
(`cargo --version` → `command not found`). `.github/workflows/desktop-ci.yml`
runs them on `windows-latest` and `macos-latest`, and the `src-tauri` code in this
tree is therefore **unverified until that job is green for the first time**.

That includes two specific claims worth naming rather than hiding:

1. `AppInfo.product_name` returns the Cargo package name, which is not the brand.
   Nothing renders it in Phase 0. It is reconciled with `tauri.conf.json` when the
   window manager lands in Phase 2.
2. `desktop/src-tauri` has no `Cargo.lock`, because a lockfile cannot be generated
   without a compiler. Direct dependencies are pinned with `=` versions; the
   transitive graph is unpinned until the first CI run generates it and it gets
   committed.

## Dependencies added, with the §6.4 justification

Runtime: `react`, `react-dom` (the UI, 19.3.0 — same major as the web app so the
two clients do not fork on React semantics); `@tanstack/react-query` (5.103.2,
same major as the web app — every server value goes through it); `zustand`
(5.0.15, UI state only); `zod` (4.6.5, the runtime validator at the SDK boundary,
which is what lets this client consume an API whose routes mostly declare no
`response_model`); `@tauri-apps/api` (2.11.1, imported by exactly one directory).

Dev: `vite` 8.3.1 + `@vitejs/plugin-react` 6.1.1 + `vitest` 5.0.2 + `jsdom` 30.1.1
(build and test); `typescript` 5.9.3 — **not** the registry's `latest` (7.0.2),
because `typescript-eslint` 8.70.1 declares `>=4.8.4 <6.1.0` and TS 7 would remove
the type-aware lint above; `eslint` 10.11.0 + `@eslint/js` 10.0.1 + `typescript-eslint`
8.70.1 + `eslint-plugin-react-hooks` 7.1.1 + `eslint-plugin-react-refresh` 0.5.7 +
`globals` 17.12.0 (the lint gate); `@testing-library/react` 16.3.3 (component tests
for the error boundary and the boot states); `@tauri-apps/cli` 2.11.5 (build
commands and `tauri icon`); `@types/*`.

Nothing was added "because it might help": there is no UI kit, no date library, no
HTTP client (the transport is Rust-side by design), and no i18n framework — the
message catalog is one module with a completeness test, which is all Phase 0 needs.

## What is deliberately absent

- **No plugin, therefore no extra capability.** `capabilities/*.json` grant
  `core:default` only. Installing a plugin is not granting a permission, so the
  plugins arrive in the phase that uses them, each with its permission diff
  reviewed: `stronghold` (Phase 1, tokens), `single-instance` + `deep-link` +
  `global-shortcut` + `notification` + `window-state` + `updater` (Phase 2).
- **No HTTP transport.** `Platform` exposes `shell`, `log`, `runtime` only. The
  transport, token store and SSE event plane are Phase 1, and the retry rules they
  will need are already pinned by `src/app/query-client.test.ts`.
- **No SQLite, no queue, no offline.** Phase 3, and the mutation queue waits on
  the decision about which writes may be deferred.
- **No e2e specs.** `desktop/e2e/README.md` explains why an empty directory is the
  honest Phase 0 state.
