# POS (Cashier) Expansion Plan — Sales OS / FIHRIST

Status: **proposed, awaiting owner approval.**
Author: engineering session 2026-10-15.
Spec anchors: `docs/spec/ARCHITECTURE_PATCH_178-200.txt` §178–§190 (esp. §189),
`docs/COMMERCE_CORE_ARCHITECTURE.md`, ADR-061, ADR-054.
Current code: `backend/app/modules/pos/` (3 files, ~728 LOC), tests
`tests/test_pos_spec.py` + `tests/test_pos_flow.py`.

---

## 0. Scope and the ERPNext decision (read this first)

The owner asked to "take ERPNext's code ready-made and adapt it." This plan
**refuses to copy ERPNext source**, and instead re-implements its *design* on our
stack. Two independent reasons:

1. **Licence.** ERPNext/Frappe is **GPL-3.0**. Copying any source file into this
   repository would oblige the whole derivative work to be GPL — incompatible
   with a commercial closed SaaS.
2. **Stack mismatch.** ERPNext is Frappe (DocType ORM) + MySQL. Every line calls
   `frappe.db.get_value`, `frappe.throw`, `doc.save()`. Porting it means rewriting
   every statement into SQLAlchemy, converting MySQL→Postgres, adding Alembic
   migrations for DocType JSON, adding RLS, and replacing `doc.save()` with
   flush-only services — i.e. writing the feature twice, with a Frappe-shaped
   mental model glued on top. It is slower AND riskier than writing it clean.

**What we DO take from ERPNext: entity design, state model, and hard-won
lessons.** Those are ideas, not code, and carry no licence. Each adoption below
names the ERPNext doctype it was modelled on, so a future reader can look the
design up.

### Non-negotiable rules every phase obeys (from AGENT_BRIEF)

- Postgres + domain services are the only source of truth; nothing else writes.
- Every mutation goes through an Application/Domain service; routers never write rows.
- Outbox event in the SAME transaction as the mutation.
- Redis is transport, never truth.
- Tenant isolation twice: app authz + Postgres RLS (`bind_tenant`).
- Services are **flush-only**; the caller owns the transaction.
- Money is `Decimal` (`NUMERIC(14,2)`), never float.
- No new external dependencies.
- POS is an **adapter** over the Commerce Core (§189) — it issues commerce and
  inventory *commands*, and never writes balances, movements, or order state.

### Owner decisions already taken (2026-10-15)

| Question | Decision |
|---|---|
| Tax/VAT | **Not now** — deferred out of this plan. |
| Discounts | **Require approval** above a per-profile threshold. |
| Starting point | Owner delegated phase ordering; goal is a **complete, working cashier system**. |

---

## 1. Where POS stands today (measured against the code)

| Capability | State | Evidence |
|---|---|---|
| Register (till) bound to one warehouse | ✅ | `pos/models.py:39` |
| Session (cash-drawer shift), one OPEN per register | ✅ | `pos/models.py:54`, partial unique index |
| Cash ledger, sell-flow-only reasons refused on the wire | ✅ | `pos/models.py:95`, `pos/router.py:29` |
| Sell = CreateOrder → capture → settlement → receipt | ✅ | `pos/service.py:266` |
| Session close: expected = float + in − out, variance stored | ✅ | `pos/service.py:354` |
| Barcode scan entry point | ❌ | sell takes a raw `items` list |
| POS Profile (preconfigured defaults) | ❌ | invented per call |
| Cashier (employee) identity on the session | ❌ | only `opened_by_user_id` |
| Discount with approval | ❌ | `create_order` accepts `discount_total`, POS never sends it |
| Split tender (multiple payment methods) | ❌ | one payment per sale |
| Per-method reconciliation at close | ❌ | cash only |
| Returns / refunds | ❌ | not wired (must ride orders, ADR-054) |
| Held / parked carts | ❌ | — |
| Receipt printing / custom numbering | ❌ | random number only |
| Walk-in customer | ❌ | `customer_id` is required |
| Cashier UI (any) | ❌ | no page, no route, no component |
| Daily consolidation | ❌ | — |

---

## 2. What we adopt from ERPNext (design only)

| ERPNext doctype | The idea worth taking | Our equivalent (this plan) |
|---|---|---|
| `pos_profile` + `pos_profile_user` | A cashier's terminal is **preconfigured**: warehouse, default customer, allowed payment modes, price list, discount ceiling | `PosProfile` (+ `PosProfileUser` link table) |
| `pos_opening_entry` | A shift records the opening float **and who opened it**, bound to a profile | extend `PosSession` with `profile_id` + cashier identity |
| `pos_invoice` (`is_pos`, `change_amount`, `account_for_change_amount`) | A POS sale tracks **tendered vs owed** and the **change returned** | tender/change on the payment, computed by `money.py` |
| `sales_invoice_payment` table | **Multiple payments per invoice** (split tender) | loop `OrderService.add_payment` per tender line |
| `pos_closing_entry` + `_detail` (payment_reconciliation) | At close, reconcile **per payment mode**: expected vs counted | `PosSessionReconciliation` rows per method at close |
| `pos_invoice_merge_log` (`consolidate_pos_invoices`) | N daily POS invoices roll up into ONE accounting document | deferred to phase 3, delivered as an **event** + projection, never a core column |
| `is_return` on the POS invoice | A POS refund is a first-class flow, not a status edit | POS return = orders refund path (§188/ADR-054) + a cash `cash_refund` row |
| `pos_settings` (invoice_type toggle) | One tenant-level switch for POS behaviour | `PosProfile` fields (no global singleton) |

Explicitly **out of scope** (do not build now): serial/batch tracking, loyalty
points, bundled products, multi-currency, offline sync queue, shift handover
scheduling. Each is named in §6 as a deliberate defer.

---

## 3. Target entity model

All new tables: `tenant_id` + `workspace_id` scope, FORCE RLS + `sales_app`
grants in the SAME migration (pattern: `fe2026101401`), `IdMixin`/`TimestampMixin`.

```
PosProfile            (NEW)  one cashier station's defaults
  ├─ name, code (tenant-unique)
  ├─ warehouse_id  → warehouses            (default stock pool)
  ├─ default_customer_id → customers       (walk-in fallback)
  ├─ allowed_payment_methods: JSONB list   (subset of cash/card/wallet/bank_transfer)
  ├─ discount_ceiling_pct: NUMERIC         (above → needs approval)
  ├─ require_customer: bool                (False ⇒ walk-in allowed)
  └─ is_active: bool

PosProfileUser        (NEW)  which user may operate this profile
  └─ profile_id, user_id, UNIQUE(profile_id, user_id)

PosRegister           (EXISTING, +profile_id)
PosSession            (EXISTING, +profile_id, +cashier_user_id)
PosCashMovement       (EXISTING, unchanged)
PosReceipt            (EXISTING, +tendered_amount, +change_amount)
PosSessionReconciliation (NEW)  one row per payment method, written at close
  ├─ session_id, method
  ├─ expected_amount, counted_amount, variance
  └─ UNIQUE(session_id, method)

PosHeldCart           (NEW, phase 2)  parked sale, resumable
  ├─ session_id, label, payload JSONB (cart lines + customer)
  └─ status: HELD | RESUMED | DISCARDED
```

**Why a profile and not just fields on the register:** ERPNext models a *terminal
configuration* separately from the *physical till*, because one merchant runs many
tills off one config and changes the config without touching hardware. We copy that
separation.

---

## 4. API surface (all under `/api/v1/pos`)

Guarded by `orders:write` today; new profile routes use `settings:write` for
configuration and `orders:write` for operation.

**Phase 1**
```
POST   /pos/profiles                        create (settings:write)
GET    /pos/profiles                        list
GET    /pos/profiles/{id}                   detail
PATCH  /pos/profiles/{id}                   update (settings:write, if-match)
POST   /pos/profiles/{id}/users             grant a cashier
DELETE /pos/profiles/{id}/users/{user_id}   revoke

POST   /pos/sessions                        open (body: register_id | profile_id, opening_float)
GET    /pos/sessions/{id}                   live position incl. per-method breakdown
POST   /pos/sessions/{id}/scan              SCAN → resolve_identifier → variant + price
POST   /pos/sessions/{id}/quote             cart → totals (discount/ceiling check, no writes)
POST   /pos/sessions/{id}/sell              split tender + discount → order → receipt
POST   /pos/sessions/{id}/close             per-method reconciliation + variance
```

**Phase 2**
```
POST   /pos/sessions/{id}/returns           refund a POS sale (§188 path)
POST   /pos/sessions/{id}/held-carts        park a cart
GET    /pos/sessions/{id}/held-carts        list parked carts
POST   /pos/held-carts/{id}/resume          resume
DELETE /pos/held-carts/{id}                 discard
GET    /pos/receipts/{id}                   receipt payload for printing
```

**Phase 3**
```
GET    /pos/sessions/{id}/report            shift report (variance, per-method, hourly)
GET    /pos/reports/daily                   daily consolidation (event-fed projection)
```

Every new query param gets a DB-free guard test asserting it is on the wire
(AGENT_BRIEF §7), and every route is asserted mounted in `create_app().openapi()`.

---

## 5. Phases (dependency order — each builds on the last)

### Phase 1 — Foundation: make POS actually usable
1. **Migrations** for `pos_profiles`, `pos_profile_users`, `pos_session_reconciliations`,
   `pos_held_carts` (empty until phase 2), plus `pos_registers.profile_id`,
   `pos_sessions.profile_id`/`cashier_user_id`, `pos_receipts.tendered_amount`/`change_amount`.
2. **`PosProfileService`** — CRUD + cashier grants + discount-ceiling policy (a `can()`-style
   predicate that returns, never raises, plus an `ensure()` that raises).
3. **Scan** — `POST /scan` calls `CatalogService.resolve_identifier`, checks product
   sellability, and returns variant + `CatalogService.price_for` price. Read-only.
4. **Quote** — pure calculation over `orders/money.py::compute_totals`, plus the
   discount-ceiling check (approval required above ceiling). Read-only, no writes.
5. **Split tender + discount on sell** — `sell` takes `tenders: [{method, amount}]`
   and `discount_total`; loops `OrderService.add_payment`; computes tender/change
   when a single cash tender covers the total; writes `tendered_amount`/`change_amount`
   on the receipt; refuses a discount above the ceiling without an approval grant.
6. **Per-method reconciliation at close** — expected per method from payments in the
   session; counted per method supplied at close; variance stored per method.
7. **Tests** — DB-free guards (routes mounted, params on the wire, ceiling predicate
   truth table) + DB-backed in CI (scan flow, split tender, ceiling refusal, close
   reconciliation). DB-backed reported as **UNVERIFIED locally** per AGENT_BRIEF §3a.

### Phase 2 — Cashier operations
8. **Returns** — `POST /returns` refunds a POS sale through `OrderService.register_refund`
   (§188/ADR-054) and books a `cash_refund` cash row in the same transaction.
9. **Held carts** — park/resume/discard, backed by `pos_held_carts`.
10. **Walk-in customer** — when `require_customer = false`, resolve/create the profile's
    default walk-in customer via `CustomerService`; never a fake id.
11. **Receipt payload** — a read model for printing (no printer driver in the backend).

### Phase 3 — Expansion and UI
12. **Cashier UI** — a React page (`frontend/src/pages/Pos.jsx` + components): scan box,
    cart, quantity/price keyboard, discount with approval prompt, tender screen with
    change, shift open/close. RTL, touch-friendly, i18n keys in `ar` **and** `en`.
13. **Shift report** — variance, per-method totals, hourly sales (event-fed, §190).
14. **Daily consolidation** — N sales → one accounting document, delivered as an event
    + projection, never a column on a core table.

---

## 6. Deliberately deferred (named, not forgotten)

Serial/batch tracking · loyalty points · product bundles · multi-currency · offline
sync queue · shift scheduling/handover · fiscal-printer drivers · tax/VAT engine
(owner deferred) · multi-location routing beyond the register's warehouse.

---

## 7. Risks and how we hold them

| Risk | Mitigation |
|---|---|
| GPL contamination | No ERPNext source is copied; only design. Reviewer checks this. |
| Breaking §189 (POS writing core state) | Every POS mutation calls a Core service; no direct ledger/balance writes. |
| Money rounding on tender/change | All math in `orders/money.py` (`Decimal`, quantized); no float. |
| Discount abuse | Ceiling per profile + approval grant; refused on the wire AND in the service. |
| Receipt number collisions | Keep the savepoint-retry; move to a per-profile sequence in phase 2 if needed. |
| DB-backed tests silently skipping locally | Report as UNVERIFIED; CI owns real verification (AGENT_BRIEF §3a). |
| Two agents editing one file | This work stays inside `app/modules/pos/` + its migrations + its tests. Out-of-scope needs are reported, not edited. |

---

## 8. Definition of Done for the whole plan

1. Every capability in §5 implemented, called from `app/` (no dead code).
2. Each has a test that fails before and passes after — DB-free where possible,
   DB-backed (CI) otherwise, the latter reported UNVERIFIED locally.
3. `ruff check` clean; frontend `tsc --noEmit` + `npm run lint` clean.
4. The cashier flow works end to end: open shift → scan → cart → discount →
   split tender → receipt → close with reconciliation → (phase 2) return.
5. No ERPNext dependency, no GPL code, no new third-party package.
