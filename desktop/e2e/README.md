# e2e

Empty on purpose in Phase 0.

An end-to-end suite needs a packaged app to drive, and `tauri build` does not run on
this machine (no Rust toolchain — see `../docs/phase0-gates.md`). A spec written
against a binary nobody has booted would be theatre: green checks that prove the
test file parses, nothing more.

Phase 5 owns this directory: Windows and macOS runners drive a signed local build
through login, the workspace switch, inbox send, and crash recovery. What lands here
before then is only whatever a phase can genuinely execute — the first honest
candidate is the update-rehearsal loop, because that is the one behaviour a unit
test cannot approximate at all.

The gates that *do* run today are `npm run verify` (JS side, this machine) and
`.github/workflows/desktop-ci.yml` (both platforms, CI).
