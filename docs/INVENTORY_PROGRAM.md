# FIHRIST Inventory Program — the executable plan

Status: **completed**. Owner: Mavis. Last updated: 2026-11-17.

This is the implementation plan for turning the inventory domain from "a stock
screen" into a supply-chain platform. It follows the architecture agreed in the
program brief, with the corrections this repository forces. **The code is the
truth**: where this document and the code disagree, the code wins and this file
is the thing to fix.

---

## 1. The one-paragraph version

The inventory domain already owns the part that is hard to get right — an
append-only ledger, a transactionally maintained balance, reservations, a
snapshot-based stocktake, and a reconciliation that compares the ledger with
the projection. What it does **not** own is the supply chain around that
ledger: no goods receipt, no quality inspection, no transfer lifecycle, no
storage locations, no replenishment engine, no FIFO costing, no traceability.
The program builds those, in an order that never puts a new domain on top of
an unproven chain.

---

## 2. Binding architectural decisions

These are decided. Every change in this program obeys them. If a change
violates one, it needs an ADR, not a review comment.

### D1 — The ledger is the audit truth; the balance is a projection; reconciliation compares them

- `inventory_movements` is append-only. Never updated, never deleted. A
  mistake is corrected by a **counter-movement**, not an edit.
- `inventory_balances` is a projection updated **in the same transaction** as
  the ledger write, under `SELECT … FOR UPDATE`.
- The balance is **not** computed by replaying the ledger.
- `inventory/reconciliation.py` exists to catch the projection drifting from
  the ledger. If the balance were replay-derived, drift would be impossible and
  the module would be dead code.

**Consequence for the brief:** the brief's wording "the visible balance is a
projection computed from the movements" is *wrong as written* and must not be
implemented literally. The correct sentence is: *the visible balance is a
projection; the ledger is the truth; reconciliation proves they agree.*

### D2 — The balance grain does not change

`inventory_balances` stays keyed on `(tenant_id, warehouse_id, variant_id)`.
New dimensions live in side tables and never enter this key.

Why: `inventory_movements.balance_after` is reconciled against this row, and
`reservation` holds against it. Changing the grain breaks both, and the ledger
cannot be rewritten.

### D3 — Condition (quarantine / damage) is a subset counter, not a new balance row

`inventory_balances` gains one column: `quarantined INTEGER NOT NULL DEFAULT 0`.
`on_hand` keeps its meaning — **total physical stock at that warehouse for that
variant**. Sellable stock is derived:

```
physical_total = on_hand
sellable       = on_hand - quarantined
available      = on_hand - quarantined - reserved
```

The ledger gains two directions that move `quarantined` without moving
`on_hand`, exactly the way `hold`/`release` already move `reserved` without
moving stock: `quarantine` and `unquarantine`, carrying the reasons
`quality_hold` and `quality_release`.

**Every place that reads availability must subtract `quarantined`.** As of the
program start those are `balances.reserve()`, `pos` stock availability,
`check_physical_settlement`, and the stock read model.

### D4 — Storage locations are a sub-position, never a second balance

`warehouse_locations` describes the physical places (zone → rack → shelf → bin,
plus the functional ones: receiving, QC, quarantine, damaged, returns).
`inventory_location_balances` says how much of the warehouse's stock sits at
each location.

Moving stock **between locations inside one warehouse** does not change
`on_hand` and does not write an `in`/`out` movement. It writes a `relocate`
ledger row (balance_after unchanged, like `hold`) and a row in
`inventory_location_movements`.

The service enforces the invariant: the sum of a variant's location balances at
a warehouse may never exceed that warehouse's `on_hand`.

### D5 — A purchase order never adds stock. Only an approved goods receipt does.

`purchase_orders` gain `quantity_received` on their lines and a status machine
of `draft → approved → sent → partially_received → received → cancelled`.
Receiving is a **document** (`goods_receipts` + `goods_receipt_lines`), it
supports partial receipt, and the stock movement references the receipt, not
the order.

### D6 — A transfer is a document with a lifecycle, not two moves at once.

Today `complete_transfer` writes the `out` and the `in` in the same call, so
goods appear at the destination the instant the source says "shipped". The
program replaces this with:

```
draft → approved → picking → packed → in_transit → partially_received → completed
                                   ↘ cancelled (only before shipping)
                                   ↘ exception (shortage / damage)
```

Shipping writes the `out` at the source and nothing at the destination.
Receiving writes the `in` at the destination. Transfer lines become relational
rows, not JSONB.

### D7 — Documents, not log lines

Every new operational object (goods receipt, transfer, inspection, stocktake,
adjustment, purchase requisition) is a document with: relational lines, an
approved status set, transition timestamps, and a responsible user.

### D8 — Every operation is idempotent

Every write endpoint accepts an `Idempotency-Key`. The frontend already has the
mechanism (`frontend/src/cashier/api/intentStore.js` + `useIntentMutation`).
Backend retries must never double-apply.

### D9 — Analytics compute; AI explains

Replenishment, valuation, stock-out risk and dead-stock detection are
**deterministic functions** with unit tests. The AI layer reads their output
and explains it. The AI never writes to the ledger, never creates a purchase
order, and never executes a transfer without an approval.

### D10 — One currency per tenant

Costs, purchase prices, landed cost and valuation follow ADR-053. A tenant has
one currency; a purchase order in another currency is not representable.

### D11 — Events follow the existing `domain.action` convention

`order.cancelled`, `pos.sale.exchanged`, `pos.session.closed` are the precedent.
New events: `inventory.stock_changed`, `inventory.low_stock`,
`inventory.stockout_risk`, `inventory.reservation.expired`,
`inventory.transfer.shipped`, `inventory.transfer.received`,
`inventory.stocktake.approved`, `purchasing.purchase_order.approved`,
`purchasing.goods_receipt.posted`, `inventory.quality_hold.created`.

### D12 — New domains are new modules

A new capability gets a new module under `backend/app/modules/<name>/` with
its own `models.py`, `service.py`, `router.py` and `README.md`. Cross-module
edges go through a service, never a direct model import. The import-boundary
ratchet in `tests/test_module_boundaries.py` is never raised without the
owner's explicit say.

---

## 3. Target module map

| Module | Owns | New? |
|---|---|---|
| `inventory` | ledger, balances, reservations, transfers, stocktakes, reconciliation | extended |
| `purchasing` | suppliers, purchase orders, goods receipts, supplier returns, payments | extended |
| `catalog` | products, variants, identifiers, bundles/kits | extended |
| `pos` | registers, sessions, receipts, the cashier's own read models | extended (reads only) |
| `warehousing` | storage locations, bins, location balances, relocation | **new** |
| `quality` | inspections, inspection results, holds, quarantine | **new** |
| `replenishment` | policies, demand calculation, reorder suggestions | **new** |
| `valuation` | cost layers, FIFO, landed cost, COGS | **new** |
| `traceability` | lots, serials, expiry, tracking policy | **new** |

---

## 4. Build order

Each phase has an acceptance criterion that is a **test**, not a description.

### Phase 0 — Prove the chain (blocking, no new tables)

The production database holds **zero** `pos_receipts`, zero `sale` movements,
zero stocktakes and zero reorder levels. The cashier→inventory chain has never
run against real data.

- **0.1** A runnable test environment (see §5).
- **0.2** One integration test that walks the whole chain in one tenant:
  supplier → purchase order → **goods receipt** → stock on the shelf → cashier
  sale → reservation → `out`/`sale` movement → stock down → customer return →
  restock → stocktake → variance → adjustment → **reconciliation finds no
  discrepancy**. Assert the ledger, the balance and the reconciliation at
  every step.
- **0.3** A regression test that the ledger's `balance_after` always equals the
  balance row, for every movement the test produces.

**Exit criterion:** the integration test is green and stays green.

### Phase 1 — Supply chain core

- **1.1** Goods receipts with partial receiving (D5).
- **1.2** Quality inspection of an incoming receipt; the verdict decides
  whether the quantity lands as sellable, as quarantined, or is rejected into a
  supplier return.
- **1.3** Customer-return inspection: a returned item is not sellable until it
  passes inspection.

**Exit criterion:** a receipt of 70 against an order of 100 leaves the order
`partially_received` with 70 received and 30 open, and the rejected portion
never reaches sellable stock.

### Phase 2 — Transfers and the stocktake upgrade

- **2.1** Transfer lifecycle (D6), relational lines, partial receipt,
  split shipments, exception handling.
- **2.2** Stocktake kinds: full, cycle, blind, spot. Assignments to
  counters, recount on a large variance, blind counts that do not reveal the
  book quantity.

**Exit criterion:** a transfer shipped but not received shows as `in_transit`
stock and the destination's `on_hand` does not include it.

### Phase 3 — Warehousing: locations and condition

- **3.1** `warehouse_locations` and the functional location kinds.
- **3.2** Location balances and relocation (D4).
- **3.3** Quarantine and condition (D3), including every availability reader.

**Exit criterion:** quarantined stock is excluded from availability, excluded
from the sale path, and visible as its own figure.

### Phase 4 — Replenishment

- **4.1** `inventory_policies`: min, max, safety stock, lead time, MOQ, order
  multiple, review period, preferred supplier.
- **4.2** A deterministic demand calculation from real sales.
- **4.3** Suggestions that prefer a **transfer** from a warehouse with surplus
  over a **purchase**, and state the arithmetic that produced them.

**Exit criterion:** the same inputs always produce the same suggestion, and
the suggestion names its source and its reason.

### Phase 5 — Valuation

- **5.1** Cost layers and FIFO, alongside the existing moving average.
- **5.2** Landed cost allocation.
- **5.3** COGS on the sale movement.

**Exit criterion:** a receipt of 10 at 10 and 10 at 20, then a sale of 12,
books 120 of cost against the sale, and the remaining layers are 8 at 20.

### Phase 6 — Traceability, bundles, reporting, the inventory agent

- **6.1** Lots and serials, with a per-variant tracking policy
  (none / batch / serial) and expiry.
- **6.2** Bundles and kits: selling a bundle consumes its components.
- **6.3** The reporting centre: stock on hand, available/reserved/incoming/
  in transit, valuation, low stock and reorder suggestions, dead stock,
  stock age, turnover, days of supply, sell-through, count variance, supplier
  performance, returns/damage/expiry. Plus the apparel-specific cuts: best
  selling colours, sizes that run out, stagnant colours and sizes, size
  distribution per model, high-demand/low-stock variants, and which branch has
  the surplus for which size.
- **6.4** The inventory agent: read-only tools over the metrics above, in the
  existing `si_*` pattern.

**Exit criterion:** selling a bundle decrements each component exactly once and
never lets the bundle sell past its components' availability.

### Phase 7 — Channel allocation & checkout traceability

- **7.1** `InventoryChannelAllocation` model, service, and DB migration (`inventory_channel_allocations`).
- **7.2** Reserve/release per-channel quota enforcement in `movements.py` and `orders/service.py`.
- **7.3** Checkout traceability integration in POS cashier (`TraceabilityDialog`, serial scanning, FEFO batch selection).
- **7.4** Supply Chain & Inventory UI tab for channel allocations in `frontend/src/pages/Inventory.jsx`.

**Exit criterion:** A channel cannot reserve or sell past its allocated quota; checkout enforces serial numbers and lot selection according to tracking policies.

---

## 5. Test environment

The suite runs against a real PostgreSQL as the `sales_app` role with RLS
enforced; each test executes inside a transaction that is rolled back.

- The **transaction** pooler (`:6543`) is used for tests. The **session**
  pooler (`:5432`) is for Alembic only.
- Every test rolls back, so production data is never changed.
- Redis is required by roughly a third of the suite.

---

## 6. Rules that apply to every phase

1. A bug fix needs a test that fails without the fix.
2. New code must be called by something.
3. Services `flush()` and never `commit()`; the caller owns the transaction.
4. Events go through the outbox in the same transaction as the change.
5. Every tenant table carries `tenant_id` and RLS.
6. Any route change ships with a regenerated `desktop/openapi.lock.json`,
   produced with **Python 3.13**.
7. No credentials in the repository.
