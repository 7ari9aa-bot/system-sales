# Cashier POS, Phase 1 report (sales, returns, exchanges, shifts, Z-report)

Branch `feature/cashier-wiring`, head `2f610fb`. Every number below was produced by a command run
against the real backend (Postgres 17, FastAPI, Python 3.13), not a mock.

## Verdict
Phase 1 is **done with 3 known limits and 9 open product decisions** (listed below). No gate was
skipped. Two real bugs found by the gates were fixed, each with a test that fails without the fix.

## The 7 gates

| Gate | Result | Evidence |
|---|---|---|
| G1 code review | pass | mock data removed from shifts, sales, returns, exchanges, Z; hard-coded shop name removed in 5 places; no `mockData` import left on a wired screen |
| G2 code tests | pass | frontend **215/215**; backend POS/migration/contract/openapi/warehouse/CRM suite **86 passed, 2 skipped, 0 failed** |
| G3 logic against the live API | pass **13/13** | oversell 409; tenders must equal total; card cannot carry change; cash 200 on 120 records change 80; same key twice = one receipt + stock -1 once; return > sold 409; qty -1 now 400; exchange 350->120 needs no tender (net -230); held cart released twice 404; close short records -409; sell/exchange on a closed session 409 |
| G4 tables | pass | migrations apply clean from empty (migration test in the 86) |
| G5 relations | pass | receipt -> order -> session; return/exchange rows reference the original order; cash movements by reason |
| G6 every screen | pass **9/9** | pos, shifts, sales, returns(+log), exchanges(+log), reports, settings: 0 failed requests, 0 console errors, 0 leaked mock strings, RTL container present, empty states readable |
| G7 full journey in a browser | pass **14/14** | open shift (100) -> 3 lines 590 -> hold -> restore -> pay 400 cash + 190 card with F2 (ONE request, idempotency key) -> receipt -> sales log -> return 120 -> close counting 50 short -> variance -50.00 shown -> Z row matches |

Static: official `npm run lint` 0 errors (6 warnings, all in legacy `pages/settings`, none in
`src/cashier`); production build passes; backend `ruff check` passes. `ruff format` flags 63 files, the
same 63 as on `origin/main`, none introduced here.

## Bugs found by the gates and fixed
1. **Z-report overstated cash returns** (commit `187b2df`). It used the all-tender returns total (590)
   but only 240 left the drawer, 350 went back on a card. Columns now come from cash movements by reason.
2. **`/sell` answered HTTP 500 (retryable) for quantity 0 or negative** (commit `2f610fb`). `/quote` was
   already strict; `/sell` fell through to `OrderService`'s bare `ValueError`. Now 400. 6 tests, all fail
   without the change.
3. Earlier in this phase: a shift closed with a shortage was shown as balanced (`7202236`).

## Known limits (stated, not hidden)
1. The "cash sales" column in the Z-report includes the internal cash echo of an exchange. The
   expected-in-drawer and variance figures come from the backend and are correct.
2. Stock is checked at the moment of sale, not when the cart is filled (backend design). The UI warns early.
3. Deferred (credit) payment is disabled in the UI because the backend has no such tender yet.

## Test-environment caveat
The shift used for the browser journey lives in a test shop (`E2E Shop`) with many repeated runs. I
compared every figure with the backend report for the same shift; I did not test with a second cashier
or concurrent registers (that is Phase 2 territory).

## Open decisions (need the owner)
1. Link the two exchange receipts in the backend, or keep them as separate entries?
2. Suspended invoices left at shift close: warn only (today) or block closing?
3. Allow returns/exchanges for a sale made in an earlier shift?
4. Refund method: forced to the original tender, or chosen by the cashier?
5. Exchange discount: apply the original invoice discount to new lines?
6. Keep or drop the reason / customer / staff fields the backend does not store?
7. Persist shop details (name, address, phone, receipt footer) in the backend settings?
8. Legacy shifts with no counted cash: show as "not counted" or hide?
9. Exchange drafts/notes kept only in the browser: keep or remove?
