# Cashier integration: Phase 0 report (foundation)

Commit: `7765b32` on `feature/cashier-wiring` (on top of `8a79fc9`).

## What Phase 0 delivered
| Piece | Where | Why it matters |
|---|---|---|
| Money layer (integer cents, wire strings) | `frontend/src/cashier/api/money.js` | No float rounding; negatives rejected before any request |
| Retry-safe POS backend | `backend/app/core/idempotency.py` (+ tests) | A double tap or network retry cannot sell twice |
| POS API client | `frontend/src/cashier/api/posApi.js` | One intent = one `Idempotency-Key`; bad input rejected locally |
| Till state machine | `frontend/src/cashier/api/shiftState.js` | `needs_setup / no_open_shift / open / forbidden / error`; never guesses |
| First-use warehouse | `POST /warehouses/ensure-default` | A new shop had no warehouse and no API to create one, so profile, register and stock were blocked |
| Contract test | `api/contract.test.js` | Every path the client sends must exist in `desktop/openapi.lock.json` |

## The 7 gates
| # | Gate | Result | Evidence |
|---|---|---|---|
| 1 | Code review | Pass | Reviewed against the real routes; found 2 wrong assumptions (below) |
| 2 | Code tests | Pass | Frontend 43/43, backend gate set 53 passed |
| 3 | Logic tests | Pass | Mutation checks: dropping the idempotency header, un-normalised tenders, a CLOSED shift treated as open, an error swallowed as "needs setup", always-insert warehouse, and a mistyped path were each caught by a test |
| 4 | Tables | Pass | Migration `fe2026101715` applied; no new tables needed |
| 5 | Relations | Pass | profile -> warehouse, register -> warehouse + profile; unique codes per tenant keep bootstrap repeat-safe |
| 6 | Page / API checks | Pass | Frontend build ok, lint 0 errors; `openapi.lock` regenerated and its gate passes |
| 7 | Full user journey | Pass | Real backend, no mocks, 40+ checks (see below) |

## Journey verified on a real backend
login (cookies + CSRF) -> fresh shop reports no register -> ensure-default twice returns one warehouse -> product, variant, 10 in stock -> profile + register MAIN (second create refused) -> open shift with float (second open refused) -> split sale 30 cash + 20 card -> same key replayed returns the same receipt, stock 10 -> 8 (not 6) -> drawer expected 130 (card stays out of the drawer) -> pay-out 10 then retried once, drawer 120 -> oversell, negative and underpayment refused -> close counted 118 gives variance -2.00 -> no open shift afterwards -> selling on the closed shift refused.

## Real problems found by running it (the mocks were all green)
1. `bootstrapPos` called `/catalog/warehouses`; the real path is `/warehouses`. The contract test now blocks this class of bug.
2. A brand-new shop could not be set up at all (no warehouse, no way to create one). Fixed with the manager-only endpoint.

## Known, not caused by this work
- `ruff format --check` flags 63 files on `origin/main` (same count). Mine are clean. Left alone to keep the diff reviewable.
- `openapi.lock.json` was already drifted on `main` (impersonation routes). Regenerating it fixes that too.
- The 8 baseline test failures from earlier are unchanged.

## Decision needed before Phase 1
The local run used a throwaway owner I verified directly in the local DB. Production setup needs a real manager login; nothing here touches production.
