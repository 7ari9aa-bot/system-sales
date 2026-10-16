# POS Implementation Plan v2 — the complete cashier layer

Status: **phases 1–4 (backend) and phase 3 (cashier UI) LANDED 2026-10-15.**
The owner approved D1–D4 and the whole plan was implemented in one pass:
migrations `fe2026101504`/`fe2026101505`, `pos_session_floats` +
one-open-drawer-per-cashier + day staleness + per-method reconciliation netting
refunds + `close-preview` + session resume + receipts payload + line-level
returns (`POS-RET-` receipts, per-original-tender allocation, per-variant restock
caps) + the catalog browse grid + the shift report. Frontend: `POS.jsx` rebuilt
on `src/components/pos/{money,Numpad,OpenShiftPanel,PaymentPanel,ClosePanel,
ReturnsPanel,ReceiptView}` with i18n parity (ar/en, 111 `pos.*` keys).

Still open from this plan: the **daily consolidation projection** (phase 4 step
28 — needs the worker consumer, the outbox event already carries the figures),
the deep-crawl `/pos` route (phase 5 step 32), the cashier-day runbook section
(phase 5 step 33), and DB-backed test verification on CI (locally UNVERIFIED per
AGENT_BRIEF §3a).

## 9. ERPNext parity review (2026-10-16 self-review)

Audited rule-by-rule against `POS_ERPNEXT_STUDY.md` §2. Covered: one-open-per-
till AND per-cashier, day-staleness refusal, per-method opening float, tender
sum must settle the whole order (ERPNext `validate_pos`), change cash-only via
`tendered_cash`, profile-gated methods + walk-in + discount ceiling, per-method
close reconciliation with refunds netted, line-level returns priced at the
original sale with per-original-tender allocation and per-variant restock caps,
return receipts (`POS-RET-`), session resume, close preview, shift report,
thermal receipt print. Stock reservation rides the orders ledger (§140), which
is strictly stronger than ERPNext's unconsolidated-invoice reservation.

Deliberate deviations (each is a decision, not an oversight):

1. **Profile ↔ till**: ERPNext binds the open shift to the PROFILE; we bind it
   to the REGISTER (the physical till) and capture the profile on the session —
   one config, many tills, and a shift's policy cannot drift mid-shift.
2. **Change accounting**: ERPNext books gross payments and subtracts change in
   the closing aggregation; we book the cash drawer NET at sale time
   (`cash_sale` = the cash portion owed, change handed back instantly) and
   `tendered/change` live on the receipt. Arithmetically equivalent, simpler
   audit.
3. **Write-off**: ERPNext auto-writes off precision loss up to
   `write_off_limit`; we have no GL — the discount ceiling with approval plays
   the control role instead.
4. **Returns scope**: ERPNext returns any past invoice from any shift; we
   require the original receipt to be on the CURRENT open session (drawer
   discipline — a refund never moves money between two drawers). Older sales
   ride the orders refund path on the dashboard.
5. **No session-cancel path**: ERPNext can cancel an opening entry; our close
   is final and the report is the record. Revisit if a "void shift" need
   appears in practice.

Still missing for full parity — CLOSED 2026-10-16 (the "close every gap" pass):

- **Daily consolidation projection**: `pos_daily_sales` (fe2026101506) recomputed
  by the new `PosWorker` pool on every `pos.session.closed` event — delete+rewrite
  per (date, register), idempotent by construction. `GET /pos/reports/daily?date=`.
  The ERPNext async-close-for-≥10-invoices machinery DISSOLVES: our close is pure
  arithmetic, the heavy part (consolidation) is already async in the worker.
- **Taxes roll-up infrastructure**: close-preview, the close event payload, the
  session report and the projection all carry `taxes_total` (summed from the
  orders' `tax_total`). Actual VAT computation remains blocked on the owner's
  VAT decision — the roll-up surfaces whatever the orders carry, the day VAT
  lands it flows with zero POS changes.
- **Email receipt**: `POST /pos/receipts/{id}/email` stages a durable
  `pos.receipt.email_requested` event (refused up front when the deployment has
  no email delivery); `PosWorker` sends it via Resend with the outbox id as the
  provider idempotency key. UI: the receipt card has the email field.
- **Derived "Credit Note Issued"**: receipts carry `returned_units`/
  `refunded_total`, receipt lines carry `returned_qty`, orders expose
  `fully_returned` — derived from the return lines, never a status column.
  The returns picker badges partially-returned receipts and caps inputs at
  sold-minus-returned.
- **Realtime shift-closed**: `pos_session.events` joined the SSE gateway's
  default streams; the cashier page subscribes via a stream-token EventSource
  (`useRealtime`) and resets itself the moment its shift is closed elsewhere —
  ERPNext's `frappe.realtime` behavior on our stack.
- **Item-group scoping**: `pos_profiles.item_group_ids` (ERPNext `POS Item
  Group`); browse and scan both refuse outside the profile's categories; the
  existence guard rides `CatalogService.categories_exist`.
- **Barcode disambiguation**: N/A by design — our identifiers are unique per
  (tenant, type, value) at write time, so an ambiguous scan cannot exist.
- **Keyboard shortcuts**: Ctrl+I scan focus, Ctrl+D discount focus,
  Ctrl+Enter charge, Escape closes panels.

The only parity item left is the VAT decision itself: the roll-up plumbing is
live end to end and stays at zero until the owner defines the tax engine.

## 10. Verification audit (2026-10-16) — DB-backed tests EXECUTED, 4 bugs found and fixed

The suite was run against a REAL PostgreSQL 17 (a fresh local `pos_audit`
database: all 107 migrations, `provision.py`, RLS as `sales_app`) instead of
staying UNVERIFIED-locally. Result: **72/72 POS tests pass on real data**. The
audit caught four defects that the skipped-by-default runs had been hiding:

1. **`PosDailySales` vs its migration**: the model inherits `TimestampMixin`
   (`created_at` + `updated_at`) but the migration only created `updated_at` —
   every projection INSERT would have crashed. Migration fe2026101506 fixed
   before first application.
2. **Receipt-join double counting**: `_expected_by_method` joined payments to
   receipts, and a returned order carries BOTH its sale and return receipt —
   every payment (and refund) was counted twice. Replaced with semi-joins
   (`order_id IN (session orders)`), each payment summed exactly once.
3. **Non-deterministic refund allocation**: `created_at` is the TRANSACTION
   time (AGENT_BRIEF §6), so a split sale's refund legs landed on a random
   tender. Both `return_sale` and `refund` now order cash-first (the drawer is
   where refund money physically leaves), then oldest.
4. **Atomic-resume error shape**: the sequential second resume of a claimed
   cart surfaced as a bare 404; it now reports the same `ConflictError`
   sentence as the concurrent claim, and `sell` accepts `items=None` when
   `held_cart_id` names the cart.

Also hardened while probing: `sell(tenders=[])` (an explicitly EMPTY list) is
now refused instead of silently charging the profile's default method. This plan supersedes the phase
numbering in `POS_EXPANSION_PLAN.md` (its rationale and the ERPNext-adoption
decision remain valid) and is grounded in two audits:

- `docs/POS_ERPNEXT_STUDY.md` — ERPNext v16.51.1 POS design, rule by rule.
- A full read of the working tree (2026-10-15): `backend/app/modules/pos/`
  (models 337 LOC, service 1283 LOC, profiles 299 LOC, router 508 LOC),
  migrations `fe2026101501/02/03`, tests `test_pos_spec/flow/expansion`, and the
  untracked cashier page `frontend/src/pages/POS.jsx` (814 LOC, route `/pos`).

---

## 0. Where the code actually stands (measured, not assumed)

Already built (and further than the old plan doc recorded):

| Capability | State | Evidence |
|---|---|---|
| Profile + user grants + discount ceiling | ✅ | `pos/models.py:45`, `pos/profiles.py`, routes `/pos/profiles*` |
| Register bound to a warehouse, optional profile | ✅ | `pos/models.py:103` |
| Session: one OPEN per register (partial unique index), profile + cashier captured at open | ✅ | `pos/models.py:163`, `service.py:127` |
| Append-only cash ledger; sale-only reasons refused on the wire | ✅ | `service.py:229`, `router.py:151`, `test_pos_spec.py:27` |
| Scan via `CatalogService.resolve_identifier`, priced off the ladder | ✅ | `service.py:307` |
| Quote = the order's own `compute_totals` + ceiling preview | ✅ | `service.py:358` |
| Sell = CreateOrder(channel=pos) → split tenders → §140 reservation converts → cash row → receipt with tendered/change | ✅ | `service.py:469`, proven by `test_pos_flow.py:104` |
| Close: expected = float + in − out, variance stored, outbox `pos.session.closed` | ✅ | `service.py:704` |
| Per-method reconciliation rows at close | ✅ | `service.py:780` |
| Held carts (park/resume/discard) — beyond ERPNext | ✅ | `service.py:867` |
| Refunds through the orders ledger (per-payment legs, capped), cash_refund booked on the ORIGINAL session, guarded single restock | ✅ | `service.py:975` |
| Mid-shift handover with counted drawer at the seam — beyond ERPNext | ✅ | `service.py:1202` |
| Cashier page: open drawer, scan cart, single tender, park, refund by order id, close, recon table | ✅ (v0) | `frontend/src/pages/POS.jsx` |
| i18n keys `pos.*` in ar + en | ✅ | 63 keys in both files |

Real gaps found by auditing against the ERPNext rules:

1. **Session resumability**: after a page refresh the till cannot find its open
   session — there is no `GET /pos/sessions?status=OPEN`. The UI comment admits
   it (`POS.jsx:102`).
2. **One open session per user is not enforced** — a cashier can hold two
   registers at once (ERPNext `check_user_already_assigned`).
3. **Stale sessions sell forever** — a session opened Monday can sell on Friday
   (ERPNext refuses sales when the opening entry is not dated today).
4. **Opening float is one cash number** — ERPNext opens the drawer per payment
   method (change float, card tips drawer, etc.).
5. **Non-cash reconciliation ignores refunds**: expected for card/wallet is the
   gross `OrderPayment.amount` sum (`service.py:798-827`); a card refund would
   make the close report lie. Cash is correct only because the drawer arithmetic
   nets it.
6. **Returns are amount-only** — no line-level return, no per-original-method
   refund allocation, no return receipt. ERPNext's return is a first-class
   document with negated tenders.
7. **No close preview**: the UI cannot show "expected per method" before
   counting (ERPNext `get_invoices`).
8. **No item browse/search for the till** — barcode-only. ERPNext has a paginated
   item grid with name search and stock pills.
9. **Profile can be disabled while a session is open on it** (ERPNext blocks
   this).
10. **Held-cart resume is a client-side race** — resume deletes the cart, then
    sells separately; two cashiers can both resume one cart, and a crash between
    delete and sell loses the basket.
11. **No profile-default payment method** (ERPNext `set_grand_total_to_default_mop`)
    and no `allow_in_returns` gate on refund methods.
12. **UI is a v0**: no numpad, no split-tender UI, no per-method counted inputs at
    close, refund needs a typed order id, no receipt view/print, no day warning.

Deliberately still deferred (owner decisions and study §6): taxes/VAT, loyalty,
serials/batches, offline mode, multi-currency, daily-consolidation projection
(phase 4 keeps it event-fed), item-group/customer-group profile scoping.

---

## 1. Design decisions to carry (and two new ones to take)

Carried from the owner (2026-10-15): no VAT now; discounts need approval above a
per-profile ceiling; POS is an adapter over the Commerce Core — every mutation is
a commerce/inventory command, never a direct ledger write.

New decisions this plan asks the owner to confirm:

- **D1 — one open session per user** (recommended: yes). Partial unique index on
  `(tenant_id, cashier_user_id) WHERE status='OPEN'` plus a service pre-check
  with a sentence. Handovers must re-check it (the drawer changes hands).
- **D2 — a session expires at midnight** (recommended: yes, ERPNext-style).
  `sell`/`quote`/`scan`/`hold` refuse on a session whose `opened_at` date (UTC
  until `tenants.timezone` lands) is not today; the UI warns before the refusal.
  Overnight shifts close and reopen — the report stays per-day.
- **D3 — per-method opening float** (recommended: yes). New child table
  `pos_session_floats (session_id, method, amount)`; `opening_float` stays as the
  cash figure for compatibility and is mirrored into the table on open.
- **D4 — line-level returns** (recommended: yes, this is the ERPNext core
  lesson). A return names lines and quantities, is priced at the original sale's
  own line prices, refunds allocate across the ORIGINAL captured tenders per
  method, and a return receipt is issued. The existing amount-based refund stays
  for goodwill/money-only cases.

## 2. Phase 1 — Shift integrity (backend)

Migration `fe2026101504_pos_session_floats_and_guards`:

1. New table `pos_session_floats`: `session_id FK CASCADE`, `method` CHECK in
   vocabulary, `amount NUMERIC(14,2) NOT NULL`, `UNIQUE(tenant_id, session_id,
   method)` — RLS FORCE + `sales_app` grants in the same migration (pattern
   `fe2026101501`).
2. `pos_profiles.default_payment_method` (`String(31) NULL`) and
   `pos_profiles.returns_allowed_methods` (`JSONB` default `[]`).
3. Partial unique index `uq_pos_sessions_open_per_user` on
   `pos_sessions (tenant_id, cashier_user_id) WHERE status = 'OPEN'`.

Code (`pos/service.py`, `pos/profiles.py`):

4. `open_session` accepts `floats_by_method: dict[str, object]`; validates the
   methods against the profile's `allowed_payment_methods`, writes the float
   rows, keeps `opening_float` as the cash leg (defaulting to the cash float).
5. Per-user open-session pre-check (and re-check inside `handover_session`).
6. `PosProfileService.update(is_active=False)` refuses while an OPEN session or
   register references the profile (ERPNext `validate_disabled`).
7. Sell-path staleness guard: `_ensure_session_sellable` refuses
   scan/quote/sell/hold/refund when `opened_at` date ≠ today (D2).
8. `sell` uses the profile's `default_payment_method` when no tender is named
   (cash stays the fallback when the profile has none).

New read endpoints (thin, `TenantCtxDep`/`orders:write`):

9. `GET /pos/sessions?status=OPEN|CLOSED&register_id=` — resume the till.
10. `GET /pos/sessions/{id}/close-preview` — the ERPNext `get_invoices`
    equivalent: per-method expected (float + payments − refunds for non-cash;
    float + in − out for cash), invoice counts, totals, taxes line (zeros until
    VAT exists). This same SQL fixes gap 5 when close consumes it.
11. `GET /pos/receipts/{id}` and `GET /pos/sessions/{id}/receipts` — receipt
    payload (order lines, tenders, change) for the UI and printing.

Held carts:

12. `sell(held_cart_id=...)` — resume becomes server-side and atomic: the sell
    validates the cart, sells, and deletes the cart in the same transaction;
    a second resume of the same cart is refused. The client-side DELETE path
    stays for discard.

Tests: DB-free guards (routes mounted, wire shapes, staleness predicate truth
table, ceiling already covered) + DB-backed (per-user index, stale refusal,
close-preview numbers with a card refund, atomic held-cart resume, profile
disable blocked while open). DB-backed reported UNVERIFIED per AGENT_BRIEF §3a.

## 3. Phase 2 — Returns as a first-class document (backend)

13. `PosReceipt.kind` (`String(7)` CHECK `sale|return`, default `sale`) —
    migration `fe2026101505_pos_receipt_kind`; return receipts get their own
    `POS-RET-` number series.
14. `POST /pos/sessions/{id}/returns` body:
    `{order_id, lines: [{variant_id, quantity}], restock: bool}`.
    Service rules (each maps to an ERPNext rule from the study §2):
    - the original must have a receipt on THIS session (already our rule);
    - each line is capped at sold quantity minus previously returned quantity
      for that variant (query past `return` restock movements + prior return
      receipts);
    - refund amount per line = the ORIGINAL order line's unit price × quantity,
      minus the line's proportional share of the order discount
      (`Decimal` only, `orders/money.py` quantization);
    - refund legs allocate across the ORIGINAL captured payments per method —
      the customer gets money back the way they paid (ERPNext negation rule),
      gated by the profile's `returns_allowed_methods` when set;
    - `cash` legs book `cash_refund` on this session (existing path);
    - restock rides the existing guarded `_restock_pos_sale` but becomes
      line-quantity-aware (currently it is all-or-nothing per order — it must
      move only the returned quantities; the single-restock guard becomes
      per-variant remaining quantity);
    - a return receipt (`kind="return"`) is issued referencing the original
      receipt.
15. `close`/`close-preview` arithmetic: non-cash expected =
    Σ payments − Σ refunds (already done in Phase 1 step 10); return receipts
    count as negative sales in the session invoice list.
16. The existing `POST /sessions/{id}/refunds` stays as the money-only path and
    is documented as such in the router docstring.

Tests: DB-backed return flow (sell → partial return → second return capped →
close recon per method with a card refund → return receipt readable),
DB-free guards (routes, wire shapes, cap predicate as a pure function).

## 4. Phase 3 — The cashier page becomes a product (frontend)

`frontend/src/pages/POS.jsx` grows into the ERPNext UX on our design system
(Arabic-first, keys in `ar` AND `en`, React-query where reads repeat):

17. **Open-shift dialog**: register picker, profile picker (defaults to the
    register's profile), per-method float inputs seeded from the profile's
    methods, day-warning badge when resuming an older session.
18. **Resume-on-load**: `GET /pos/sessions?status=OPEN` → continue or open new
    (fixes the refresh amnesia).
19. **Item browse panel** (second tab beside scan): a paginated grid from the
    new catalog-backed endpoint — name search, stock pill (green/orange/red),
    tap-to-add. Needs one backend addition: a catalog-owned read-model function
    `search_sellable(session, tenant_id, *, q, warehouse_id, limit, offset)`
    (variant + ladder price + bin stock) called function-scope from the POS
    service — POS writes no cross-module SQL (§137, ratchet stays at 162).
20. **Numpad**: field-select-then-type model (qty), `Enter` scans/adds,
    `Ctrl+Enter` charge, on-screen keypad for touch tills.
21. **Split-tender UI**: tiles per profile method, tapping a tile auto-fills the
    remaining amount, running paid/remaining/change line, `tendered_cash` for
    the cash leg, change shown big after sale.
22. **Close flow**: per-method counted inputs prefilled from
    `close-preview`, variance highlighted, confirm → reconciliation table
    (replacing the cash-only `counted_cash` box; keep cash quick-close).
23. **Returns UI**: pick from the session's receipts list (no typed ids),
    line-level quantities, restock checkbox, per-method refund allocation shown
    before confirm.
24. **Held carts**: label, customer, discount on hold; resume goes through the
    new atomic endpoint.
25. **Handover UI**: pick the next cashier (profile grantees), counted drawer,
    note.
26. **Receipt view + print**: a thermal-width receipt component rendered from
    `GET /pos/receipts/{id}` with `window.print()` and a `@media print` sheet.

Frontend gates: `npm run lint`, i18n parity check, and a Playwright e2e that
drives open → scan → sell → hold → resume → close against the built bundle
(CI pattern already exists in `ci.yml`).

## 5. Phase 4 — Reports and the daily projection

27. `GET /pos/sessions/{id}/report` — per-method totals, cash movements list,
    invoice count, net sales, variances, handover trail.
28. Daily consolidation stays an **event-fed projection** (§190): the worker
    consumes `pos.session.closed` + sale events into a `pos_daily_sales`
    read-model — never a column on a core table. `GET /pos/reports/daily?date=`.
29. The existing `pos.session.closed` outbox payload grows the per-method and
    return figures it already carries.

## 6. Phase 5 — Hardening and release gate

30. Test matrix completion: profile grant gates on sell/handover, walk-in
    customer resolution, scan refusal on unsellable products, held-cart rot
    (variant deleted), refund over-cap refusal (already proven), per-user
    two-drawer refusal, midnight rollover.
31. RLS verification for the three new tables in `tests/security/` (FORCE +
    cross-tenant refusal), and the boot reconciler passes on them.
32. `deep-crawl.spec.js` gains the `/pos` route once the page is stable.
33. Runbook: `docs/RUNBOOK.md` gets the cashier-day section (open → sell →
    handover → close → read the report).

## 7. Risks

| Risk | Mitigation |
|---|---|
| Midnight refusal breaks a late shift mid-sale | The UI warns the day-diff at open and on resume; the refusal names the session age, close-and-reopen is two taps |
| Return cap arithmetic drifts across partial returns | One SQL per variant computing sold − returned, single source: restock movements + return receipts; pinned by tests |
| Per-user index fights the handover flow | Handover re-checks inside the same transaction; the index is the backstop, the service gives the sentence |
| Ratchet grows with catalog/returns imports | All cross-module reads stay function-scope through the owning service (§137); baseline only moves with a written justification |
| Non-cash recon change breaks existing closes | Phase 1 step 10 lands BEFORE phase 2 returns; closes before any refund existed are unaffected (payments − 0) |
| UI scope creep | Phase 3 is one page + components under `src/pages/` and `src/components/pos/`; no router/i18n infra changes beyond keys |

## 8. Definition of Done (whole plan)

1. Every phase lands with its tests: a test that fails before and passes after,
   DB-backed ones reported UNVERIFIED locally, verified on CI.
2. The day works end to end on the built bundle: open with per-method float →
   scan + browse → split tender with change → hold → resume → line-level return
   → handover → close with per-method reconciliation → report.
3. `ruff check` clean; import ratchet at 162 or lower; `npm run lint` clean;
   i18n parity OK.
4. No GPL code, no new dependencies, flush-only services, outbox events in the
   same transaction, RLS FORCE on every new table.
