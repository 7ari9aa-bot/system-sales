# purchasing

PURCHASING domain: suppliers, purchase orders, supplier payments/returns, moving-average cost.

## Where things are

- `catalog_lookup.py`
- `models.py`
- `router.py`
- `service.py`

## HTTP

18 endpoints. Route prefixes: see `router.py`. Registered in `app/main.py`.

## Tables

- `purchase_order_lines`
- `purchase_orders`
- `supplier_payments`
- `supplier_return_lines`
- `supplier_returns`
- `suppliers`
- `variant_cost_history`
- `variant_costs`

## Depends on

Other modules imported from here: `catalog`, `expenses`, `identity`, `inventory`, `orders`.
Import boundaries between modules are ratcheted by `tests/test_module_boundaries.py`; do not add
new cross-module imports without a reason, and never raise that baseline yourself.

## Rules for working here

- Business rules live in the service layer. Routers parse and authorise, then call a service.
- Services `flush()` and never `commit()`; the caller owns the transaction.
- Every tenant table has row-level security. Bind the tenant before touching data.
- Emit events through the outbox in the same transaction as the change.
- Tests for this module are in `backend/tests/` (search for `purchasing` in the file names and imports).

_The sections above are derived from the code; if you change the structure, update them._
