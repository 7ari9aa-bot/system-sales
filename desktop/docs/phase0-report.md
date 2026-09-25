# Phase 0 report — Fihrist Desktop (Session B)

Date: 2026-09-25 · Branch checked out: `w4-t3-money` · Author: desktop session B
Scope per the mission §0: wrote only inside `desktop/**`, `.github/workflows/desktop-ci.yml`,
one new file in `docs/adrs/`, and an append-only section in `docs/DESKTOP_ARCH_REVIEW.md`.
**No git command was run.** The pre-existing dirty working tree was not touched, cleaned, or committed.

---

## 1. What Phase 0 delivered

A pinned, gated scaffold — no screens, no features.

| area | state |
|---|---|
| Toolchain | `package.json` with **exact** versions + `package-lock.json` (279 packages, lockfileVersion 3), `rust-toolchain.toml` = 1.98.1 with `clippy`/`rustfmt`, no `latest` anywhere |
| Build | Vite 8.3.1 static SPA, `tsc --noEmit` strict + `noUncheckedIndexedAccess`, React 19.3.0, TanStack Query 5.103.2, Zustand 5.0.15, Zod 4.6.5 |
| Platform seam | `src/platform/{port,index,noop,runtime}.ts` + `tauri/{invoke,index}.ts`; `resolvePlatform()` is the only place the runtime is chosen, via dynamic import |
| Contract | `contract/envelope.ts` (the v2 error envelope + additive `detail`/`tier`/`retry_after`), `contract/primitives.ts` (money stays a string) |
| Presentation edge | `shared/money.ts` (BigInt + `Intl`, never a double), `shared/i18n.ts` (Arabic-first catalog with a completeness test), `shared/log.ts` (redaction filter), `app/{document,boot-state,boot-screen,error-boundary,fatal,App,main}` |
| Retry policy | `app/query-client.ts`: retry on the server's `retryable` only, ≤2 attempts, no retry on auth codes or long `Retry-After`, **mutations never retried** |
| Native shell | `src-tauri/`: `tauri.conf.json` (Fihrist / `com.fihrist.desktop`, strict CSP, one `main` window), 4 capability files, `Cargo.toml` with `=` deps and denied `unwrap`/`expect`/`panic`/`print_stdout`, `commands.rs` (`app_info`, `log_write`), `redaction.rs` (+6 Rust unit tests), generated icon set |
| Gates | `config/check-platform-boundary.mjs`, `config/check-no-hardcoded-host.mjs`, `.github/workflows/desktop-ci.yml` |
| Docs | `docs/phase0-gates.md`, `docs/platform-boundary.md`, `e2e/README.md` (why it is empty) |

Tests: **14 files, 110 cases** — every behavioural unit was written test-first.

## 2. Evidence — commands and verbatim output

```
$ npm run verify     # boundary → typecheck → lint → test → build → no-hardcoded-host
platform boundary: OK (20 files outside the adapters)
 Test Files  14 passed (14)
      Tests  110 passed (110)
vite v8.3.1 building client environment for production...
✓ 172 modules transformed.
dist/index.html                    0.53 kB │ gzip:  0.31 kB
dist/assets/index-iiU3Fa9b.css     1.71 kB │ gzip:  0.79 kB
dist/assets/tauri-BTUNL8wV.js      0.69 kB │ gzip:  0.47 kB │ map:    17.61 kB
dist/assets/schemas-BpU2lLse.js   83.58 kB │ gzip: 23.82 kB │ map: 512.67 kB
dist/assets/index-DHP8TeXV.js    255.32 kB │ gzip: 80.38 kB │ map: 1,220.45 kB
✓ built in 467ms
hardcoded host check: OK (5 built files, no host)
VERIFY_EXIT=0
```

The RED step that preceded it (mission §6.1 — watched, not paraphrased):

```
 FAIL  src/platform/contract/envelope.test.ts [ src/platform/contract/envelope.test.ts ]
Error: Failed to resolve import "@/platform/contract/envelope" from
"src/platform/contract/envelope.test.ts". Does the file exist?
 Test Files  10 failed (10)
      Tests  no tests
```

Each gate proven non-vacuous with a throwaway violation file (since deleted):

```
src/tmp-gate-probe.ts  2:16  error  Unexpected use of 'fetch'. …  no-restricted-globals
tmp-gate-probe.ts:2  no-invoke        invoke() may only be called from src/platform/tauri/
tmp-gate-probe.ts:1  no-tauri-import  import the platform interface from src/platform, not the runtime
platform boundary: 2 violation(s)      boundary exit=1
```

`npx tsc --noEmit` → `tsc exit=0` · `npm run lint` (`--max-warnings=0`) → `lint exit=0`.
Dev server smoke (the only runtime reachable on this machine): `HTTP=200`, served
`lang="ar" dir="rtl" <title>Fihrist</title>`; server then stopped (PID terminated, port 5183 refuses)
and both probe files removed.

## 3. Three test expectations I corrected, with old → new (mission §6.3)

1. `src/platform/runtime.test.ts` — old: `https:/api.fihrist.app` → `invalid`.
   new: `{ok:true, apiBaseUrl:'https://api.fihrist.app'}`. WHATWG resolves a special scheme written
   without the authority marker to that origin; the invalid loop gained `javascript:alert(1)` and
   `https://` so coverage did not shrink.
2. `src/shared/money.test.ts` — old: locale `ar` expected Arabic-Indic digits.
   new: `ar-EG`, plus an explicit `ar-EG-u-nu-latn` case. CLDR gives root `ar` Latin digits — the
   production code was right, the locale in the test was not. A second fix was test-only (the helper
   missed U+066C, the Arabic thousands separator).
3. `src/app/error-boundary.test.tsx` — old: exactly 2 renders after clicking retry.
   new: renders strictly increase, and the panel survives a second failure. The literal 2 measured
   React's DEV re-invoke of a throwing render, not the product behaviour.

## 4. Not verified here

* **`cargo fmt --check`, `cargo clippy -- -D warnings`, `cargo test`, `tauri build`** — no Rust
  toolchain on this machine (`cargo: command not found`). Everything under `src-tauri/` is unverified
  until `desktop-ci.yml` runs green. Two named risks: (a) `AppInfo.product_name` returns the Cargo
  package name, not the brand — nothing renders it in Phase 0; (b) **there is no `Cargo.lock`**, because
  it cannot be generated without a compiler; direct deps are `=`-pinned, transitive ones are not until
  CI generates one and it is committed.
* No real window, tray, deep link, updater, SQLite, signed build, or notarization — later phases.
* UI correctness was verified by mounting the tree in jsdom (`app.test.tsx`, `error-boundary.test.tsx`),
  **not** in a webview. No screenshot was taken.

## 5. Defects found, reported, not fixed (mission §6.6)

| where | what |
|---|---|
| `backend/app/modules/realtime/router.py:51-59`, `:61-65` | access token accepted as `?token=`, and a stream can stay live "for the whole token lifetime" → bearer in a URL / access logs |
| `backend/tests/test_automation_routes.py:37,205-213` | the "a tenant is never a parameter" guard is pinned on `PREFIX="/api/v1/automation"` only, while `/auth/switch-tenant` takes `tenant_id` as a query parameter (`identity/router.py:132-135`) |
| `docs/GAP_REGISTER.md:431` vs `docs/DESKTOP_ARCH_REVIEW.md:62-64` | "~45 of 62" vs "175 of 185" vs measured **245 routes / 82 typed / 163 untyped** — three figures, one truth needed from `app.openapi()` |
| `backend/app/core/search.py:57` | `/api/v1/search` is still escaped ILIKE while `tsvector` columns exist (`ai/models.py:179-186`, `catalog/models.py:79-87`) |
| `docs/DESKTOP_ARCH_REVIEW.md:176-180` | promised a `## 5. Requests to the API team` heading that §5 had already taken → the table is now §6 |

## 6. Handover file list

* `desktop/**` — 84 files (excluding `node_modules/`, `dist/`, `package-lock.json`)
* `.github/workflows/desktop-ci.yml` — new, YAML-validated: `web` (ubuntu, 9 steps) + `native` matrix `windows-latest` / `macos-latest` (9 steps), `paths:` filtered to `desktop/**`
* `docs/adrs/ADR-059-desktop-transport-is-rust-side.md` — new
* `docs/DESKTOP_ARCH_REVIEW.md` — appended `## 6. Requests to the API team` (R1–R8) + `### 6.1` measurements (203 → 270 lines; §1–§5 untouched)

## 7. Open items for Session A

1. Runner budget: `desktop-ci.yml` is the only place the native gates exist; `ci.yml` has no `paths:`
   filter, so a desktop push also runs the whole web/API suite today.
2. Confirm ADR-059 → no `tauri://localhost` / `http://tauri.localhost` added to `CORS_ORIGINS`.
3. Say which ADR directory is canonical (`docs/adr/` range files vs `docs/adrs/` per-number).
4. **R1** (`openapi.lock.json` + SHA-256 + drift job) is the critical path for Phase 1: without an input,
   "a generated `any` fails CI" cannot be enforced.
5. Commit only after re-running `npm run verify` from `desktop/`.
