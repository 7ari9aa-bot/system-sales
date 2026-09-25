# The platform boundary

Two rules, and the rest of the document is about how they stay true:

1. **The React tree never calls `invoke()`.**
2. **The React tree never calls `fetch()`, opens an `EventSource`, or touches web
   storage.**

Layers: `Presentation → Application → Platform SDK → Tauri adapter → OS`.
Only `src/platform/tauri/` may know a Tauri runtime exists, and only it may be
imported with a dynamic `import()` so that a browser build never links the bridge.

```
src/platform/
├── index.ts          resolvePlatform() — decided once, at bootstrap
├── port.ts           the interfaces (ShellPort, LogPort, RuntimePort, …)
├── noop.ts           the in-memory platform `vite dev` and every test run on
├── runtime.ts        parseRuntimeConfig — the boot validator
├── contract/         zod: the error envelope, money, ids. `unknown` in, typed out
└── tauri/
    ├── invoke.ts     the ONE call site of invoke(), with a typed command map
    └── index.ts      one adapter per port
```

## What enforces it

| mechanism | catches |
|---|---|
| `config/check-platform-boundary.mjs` (CI + `npm run boundary`) | a banned call in any `.ts`/`.tsx` under `src/`, including a file no lint config ever matched |
| `eslint.config.js` `no-restricted-globals` / `no-restricted-syntax` / `no-restricted-imports` | the same calls while you type, in the editor and at `npm run lint` |
| `src/platform/contract/*.test.ts` | a response shape that was assumed rather than parsed |
| `config/check-no-hardcoded-host.mjs` | a server address baked into the bundle |
| `src/platform/tauri-config.test.ts` | a capability file that grants more than `core:`, a window label nobody creates, or the old product name |

A `// eslint-disable` line silences the editor rule. It does not silence the
script, which is why both exist.

## Phase ownership of the surface

| port | phase | notes |
|---|---|---|
| `shell` | 0 | `appInfo()` today; open/focus/reuse/restore is the Phase 2 window manager |
| `log` | 0 | writes an already-redacted record; the Rust side filters again |
| `runtime` | 0 | returns `null` unless a dev value exists; the on-disk settings file arrives with the transport that consumes it |
| `http`, `tokens`, `events` | 1 | transport + `TokenPair` + **SSE** (there is no WebSocket server here), refresh single-flight across windows |
| `windows`, `tray`, `notifications`, `shortcuts`, `deepLinks`, `updater` | 2 | each lands with its plugin and its capability diff |
| `localdb` | 3 | SQLite read model, drafts, sync cursors — never a system of record |

Adding a port means adding: the interface in `port.ts`, a noop implementation, a
Tauri adapter, a command in `invoke.ts`'s typed map, a Rust command that is thin
(validate → native service → typed result), and the capability diff. Business
rules and domain-mutating SQL do not belong in any of those layers: the backend
remains the only owner of domain rules.

## Money, tenants, PII

- **Money is a string on the wire.** `contract/primitives.ts` validates a decimal
  string; `shared/money.ts` formats the integer part through `Intl` as a `BigInt`
  and re-attaches the fraction digit by digit. No `Number()` in the path — that is
  how `9007199254740993.01` silently becomes `...992`, which is a bug this repo
  already spent a wave deleting once.
- **A tenant is never a parameter.** The credential carries the tenant; the
  workspace switcher calls `/auth/switch-tenant` with a `tenant_id` copied from
  `/auth/me → tenants[]`, and then invalidates every cached query and every cached
  row. RLS protects the server; it cannot protect a laptop.
- **PII redaction is server-side.** The client caches what the API said for *that*
  actor and drops it on logout. `shared/log.ts` refuses to log credential- and
  PII-shaped keys even when the server answered with them.
- **Branch on `code` and `retryable`, never on `message`.** `ApiError` is the only
  place the envelope is read.
