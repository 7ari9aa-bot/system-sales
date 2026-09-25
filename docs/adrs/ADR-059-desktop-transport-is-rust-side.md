# ADR-059 — The desktop's network calls leave from Rust, so the API needs no CORS change

- **Status:** Proposed — needs Session A's confirmation (§6 of `docs/DESKTOP_ARCH_REVIEW.md` lists adding the Tauri origins as a config request; this ADR argues it is unnecessary, and asks that it stay unmade)
- **Date:** 2026-09-25
- **Spec:** desktop mission §2 (layers), §3.2 (realtime is SSE), §3.6 (CORS), §5 (API behaviour)
- **Related:** `docs/DESKTOP_ARCH_REVIEW.md` C-D3 / C-D4 / C-D6; ADR-015 (consumer idempotency, for the queue this defers); ADR-013 (execution modes)

## Context

The desktop is a Tauri 2 app: the UI is a WebView running `tauri://localhost`
(macOS/Linux) or `http://tauri.localhost` (Windows). If the React tree issued its
own `fetch()`, every request would be a cross-origin one, and the API would have to
allow those two origins — a permanent widening of a public API's allow-list, on the
one client that has a native process standing right behind it.

Meanwhile the transport requirements are not browser-shaped anyway:

* The access token lives in Rust memory and never enters the webview
  (`docs/DESKTOP_ARCH_REVIEW.md` C-D4). A webview-origin `fetch` cannot attach an
  `Authorization` header to a stream it must keep open, which is why
  `backend/app/modules/realtime/router.py:51-59` accepts the token as `?token=` —
  a bearer in a URL, for the whole lifetime of a tenant's event firehose
  (`realtime/router.py:61-65`). The desktop has no reason to inherit that trade-off.
* `EventSource` cannot send headers at all, and gap detection here must re-query
  because server-side `Last-Event-ID` replay does not exist yet (register line P9).
* Offline reads, drafts and sync cursors need a database and a filesystem, which a
  webview does not have.

## Decision

1. **Every HTTP request the desktop makes originates in the Rust process**, behind
   the `http` port (`desktop/docs/platform-boundary.md`). The React tree never calls
   `fetch()`; `config/check-platform-boundary.mjs` fails the build if it tries.
2. **SSE is consumed in Rust too**, with an `Authorization: Bearer` header. The
   `?token=` fallback is not used by this client, and this ADR asks that it be
   narrowed server-side (see the request table, R5).
3. **No CORS allowance is added for Tauri origins.** `CORS_ORIGINS` stays as it is;
   `backend/app/core/config.py:189-190` keeps refusing `*` in a secure environment.
4. If a later phase ever needs a webview-origin request, that is a new ADR with the
   allow-list change in it — not a config edit.

## Consequences

* A public API keeps one fewer trusted origin set, and the desktop cannot be
  tricked into sending a bearer from a page it did not load.
* The transport is untestable in a browser, so it is tested the other way: the
  interfaces have noop adapters and every unit above them runs under `vitest` with
  no Tauri runtime present. The Rust half is covered by `desktop-ci.yml` on
  `windows-latest` and `macos-latest`.
* The cost is a request path that must be written once, carefully, instead of
  borrowing the browser's. That path is Phase 1's main deliverable, and it inherits
  the envelope, retry and `Idempotency-Key` rules already pinned by
  `desktop/src/app/query-client.test.ts` and
  `desktop/src/platform/contract/envelope.test.ts`.
* The desktop's certificate/proxy story becomes the OS's, not the webview's — worth
  naming now, because enterprise TLS interception is a support conversation Phase 5
  will have.
