# ERPNext POS Study — Design Reference for the FIHRIST Cashier Layer

Source examined: `frappe/erpnext` tag **v16.51.1** (shallow clone kept locally at
`C:/Users/CS/.zcode/refs/erpnext` for future reference).

Status: **reference document** — feeds `POS_EXPANSION_PLAN.md` phases. This repo
adopts ERPNext's *design*, never its code: ERPNext/Frappe is GPL-3.0, our stack is
FastAPI + Postgres + React with a different domain model (orders/payments/inventory,
no Chart of Accounts). Every rule below cites the ERPNext file it was read from.

---

## 1. Entity model (ERPNext → FIHRIST mapping)

| ERPNext doctype | Role in the design | FIHRIST equivalent (existing or planned) |
|---|---|---|
| `POS Profile` | Terminal configuration: warehouse, price list, allowed payment methods, capability flags, cashier grants, catalog scoping | `PosProfile` + `PosProfileUser` (done, fe2026101501) — add item-group scoping later |
| `POS Opening Entry` | Shift open: who opened, when, opening float **per payment method**; status derived (Open = submitted, no closing entry linked) | `PosSession` (+ `cashier_user_id`, done) — needs float-per-method, not cash-only |
| `POS Closing Entry` | Shift close: expected vs counted per method, taxes roll-up, invoice lists, triggers consolidation | `PosSessionReconciliation` (done per-method) — plus session-scoped invoice list |
| `POS Invoice` | The sale document; a Sales Invoice subtype forced into POS shape by the profile | Our POS sell already routes through `OrderService` (commerce core) — keep this, it matches §189 |
| `Sales Invoice Payment` (child) | Split tender: one row per method, `mode_of_payment`, `amount`, `type`, resolved `account` | Our `tenders` list on sell (phase 1) |
| `POS Payment Method` (child of profile) | Per-profile method + `allow_in_returns` + default flag | `PosProfile.allowed_payment_methods` JSONB — add `default` + `allow_in_returns` |
| `Mode of Payment` (+ `Mode of Payment Account`) | Global method registry; `type: Cash/Bank/General/Phone`; per-company default account | Tenant-level payment methods concept (not yet built) |
| `POS Invoice Merge Log` | N daily POS invoices → one consolidated Sales Invoice per customer; returns → credit notes | Deferred (phase 3, event + projection) — design captured in §5 below |
| `POS Settings` (tenant singleton) | `invoice_type` switch, `post_change_gl_entries`, configurable invoice fields, extra search fields | N/A for now; our profile-per-tenant choices cover it |
| `POS Item Group` / `POS Customer Group` | Profile-scoped catalog/customer filtering (nested-set subtree expansion) | Deferred — we scope by workspace/warehouse only |

## 2. The hard rules (each is a validation to port)

### Shift lifecycle (`pos_opening_entry.py`)

1. One open shift **per profile** — hard block (`check_open_pos_exists`, lines 64-71).
2. One open shift **per user** — a cashier cannot be in two stations at once
   (`check_user_already_assigned`, lines 73-78).
3. Profile must exist, not be disabled, company must match; user must be enabled.
4. Opening float is a child table keyed by **payment method**, not just cash —
   every profile method gets a pre-filled row at 0.
5. Cancellation blocked while unconsolidated invoices exist for that
   (profile, user, period).
6. Every sale requires exactly one open shift for the profile, and that shift's
   start date must be **today** (`services/pos.py:235-264` — "Outdated POS Opening
   Entry" otherwise).

### Sale document (`pos_invoice.py`, `services/pos.py`)

7. Profile injection: currency, price list precedence (customer > customer-group >
   profile), warehouse, taxes, write-off account, cost center, capability flags —
   copied from the profile onto the doc at creation (`set_pos_fields`, 660-756).
   Cashier cannot change what the profile owns.
8. Payment rows: ≥1 required; zero-amount rows deleted on submit; partial payment
   blocked unless the profile allows it (`validate_full_payment`).
9. Change: `paid > total` grants change **only if at least one tender row is Cash**
   (`controllers/taxes_and_totals.py:1215-1232`). `change = paid - (rounded|grand)
   + write_off`. Change account comes from the profile, default = company cash
   account.
10. Write-off is for precision loss only; the profile's `write_off_limit` (default 1)
    bounds it on consolidation — it is NOT a cashier discount cap. Our discount
    ceiling (already in `PosProfile`) is a stricter, better guard; keep ours.
11. `paid + write_off <= grand_total` for sales; totals negative for returns
    (`validate_pos` / `validate_payment_amount`).
12. Stock: draft-time availability check optional (`validate_stock_on_save`),
    always on submit. Availability = bin qty − **sum of submitted unconsolidated
    POS invoices** for that item+warehouse (`get_stock_availability`, 992-1045) —
    open shifts reserve stock so concurrent cashiers cannot oversell.
13. Update stock is forced on (hidden, read-only on the profile).
14. Returns: created only via `make_sales_return` against an original; qty rows all
    negative; payment rows **fully negated per method**; serials must have been
    sold on the return-against; the original flips to "Credit Note Issued".
    Consolidated invoices cannot be returned directly.
15. Status chain: Consolidated > Overdue/Partly Paid/Unpaid > Credit Note Issued >
    Return > Paid > Submitted. Cancel of a consolidated invoice requires cancelling
    the closing entry first.

### Shift close (`pos_closing_entry.py`)

16. Closing scope = (profile, user, period window): invoices owned by the closing
    user, on that profile, posted in [period_start, period_end], not yet
    consolidated (`build_invoice_query`, 442-481).
17. Reconciliation rows seeded from opening float: `expected = opening float +
    aggregated payments`; `closing` is what the cashier counts; `difference`
    stored per method.
18. Change-aware aggregation: an invoice's `change_amount` is subtracted from the
    payment row it was paid **from** — preference order: a Cash row on the
    change-account → any row on the change-account → any Cash row
    (`get_change_payment_row`, 341-349; pinned by tests 443-490).
19. Taxes roll up grouped by account across all in-scope invoices.
20. Closing submission triggers consolidation; ≥10 invoices → async job with
    status Queued/Failed + retry endpoint; realtime event tells the open POS
    screen to reset. Cancel closes/unconsolidates and reopens the shift.
21. Closing entry cannot be cancelled while the profile has another open shift.

## 3. Consolidation design (phase 3 — worth the detail)

`pos_invoice_merge_log.py`: sales split per customer → one consolidated invoice;
returns become credit notes whose `return_against` is the consolidated sale of the
original. Merge math: item `rate = net_rate` (price_list_rate zeroed), taxes become
`Actual` summed rows recomputed never, rounding adjustments summed, header discounts
zeroed, pricing rules ignored. Invoices split by accounting dimension; serial
returns forced to follow their sale in the same batch.

FIHRIST mapping: this stays an **event + projection**, never a mutation of core
order state (§190); the exact merged-row construction above is what the projection
should reproduce.

## 4. Frontend UX (for the phase-3 React cashier page)

ERPNext v16 UI is jQuery + template strings at `selling/page/point_of_sale/` —
no framework, online-only (zero offline/IndexedDB code in v16 — validates our
"offline deferred" decision). Flow to replicate:

1. Boot: `check_opening_entry(user)` → if no open shift, opening dialog collects
   profile + per-method float → `create_opening_voucher` → app defaults.
2. Left panel: item grid (page 40), debounced search (300ms, memoized per price
   list, invalidated on customer change), barcode scan goes through search with
   ambiguous-scan disambiguation, item-group tabs, stock pill colored by qty.
3. Right panel: cart with customer block, totals, numpad
   [1-9, ., 0, Del] mapping to selected field (qty/discount/rate first —
   field-select-then-type model), rate/discount editing gated by profile flags.
4. Checkout → payment screen: one tile per profile method, clicking a tile
   auto-fills the remaining amount, Tab cycles methods, change vs remaining shown
   in the same slot (red unpaid / green change), optional invoice fields dialog.
5. Submit → receipt summary → auto-print when profile flag set; print formats are
   thermal-width (4-inch) Jinja templates.
6. Returns: Recent Orders → order summary → "Return" (only if returnable) →
   `make_sales_return` mapper renders the negative cart through the same flow.
7. Close: prefill a closing entry (per-method expected vs counted rows,
   difference editable) → submit → async job → realtime completion → POS resets.
8. Keyboard: Ctrl+I search, Ctrl+Enter checkout/new order, Ctrl+D discount,
   Ctrl+P print, Ctrl+E edit, scanner-wedge via global key listener.
   For RTL: mirror the 2-column grid, localize every label (ar + en), keep the
   field-select-then-type numpad.

## 5. Gaps between ERPNext's design and our current phase-1 code

Already aligned (done in fe2026101501 + `pos/profiles.py`): profile entity +
user grants, register/session binding, tendered/change on receipt, per-method
reconciliation at close, discount ceiling (stricter than ERPNext's write-off limit).

To port from this study (candidates for next POS phases, in dependency order):

1. **Per-method opening float** on the session (today our float is cash-only).
2. **One-open-per-profile and one-open-per-user** session validation (ERPNext
   rule 1-2) and **open shift required, dated today** on sell (rule 6).
3. **Unconsolidated-POS-reservation in availability** (rule 12) — our scan/quote
   should subtract open-session sell lines from bin qty, or we accept the simpler
   check-stock call and note the oversell window explicitly.
4. **Returns flow** (phase 2 as planned) following rules 14-15 exactly: negated
   tenders per method, return-against required, original status flip.
5. **Change-aware per-method aggregation at close** (rule 18) — our current
   reconciliation stores per-method variance but does not yet subtract change from
   the paying method's row.
6. `allow_in_returns` on profile methods + a `default` method flag
   (`set_grand_total_to_default_mop` equivalent).
7. Session close → async consolidation as an outbox event + projection (phase 3).
