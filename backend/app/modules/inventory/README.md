# inventory

INVENTORY domain — warehouses, balances, movements, transfers.

## Where things are

- `models.py`
- `reconciliation.py`
- `router.py`
- `service.py`
- `services/`
- `stock_view.py`

## HTTP

5 endpoints. Route prefixes: `/inventory`. Registered in `app/main.py`.

## Tables

- `inventory_balances`
- `inventory_movements`
- `inventory_reconciliation_findings`
- `inventory_reservations`
- `inventory_transfers`
- `stocktake_lines`
- `stocktakes`
- `variant_stock_settings`
- `warehouses`

## Depends on

Other modules imported from here: `catalog`, `identity`, `orders`.
Import boundaries between modules are ratcheted by `tests/test_module_boundaries.py`; do not add
new cross-module imports without a reason, and never raise that baseline yourself.

## Rules for working here

- Business rules live in the service layer. Routers parse and authorise, then call a service.
- Services `flush()` and never `commit()`; the caller owns the transaction.
- Every tenant table has row-level security. Bind the tenant before touching data.
- Emit events through the outbox in the same transaction as the change.
- Tests for this module are in `backend/tests/` (search for `inventory` in the file names and imports).

_The sections above are derived from the code; if you change the structure, update them._
