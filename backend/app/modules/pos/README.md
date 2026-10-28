# pos

POS domain — the point-of-sale adapter (Commerce Core v1.0 §189).

## Where things are

- `models.py`
- `override.py`
- `profiles.py`
- `router.py`
- `service.py`
- `stock_view.py`

## HTTP

42 endpoints. Route prefixes: `/pos`. Registered in `app/main.py`.

## Tables

- `pos_cash_movements`
- `pos_daily_sales`
- `pos_held_carts`
- `pos_profile_users`
- `pos_profiles`
- `pos_receipts`
- `pos_registers`
- `pos_return_lines`
- `pos_session_floats`
- `pos_session_handovers`
- `pos_session_reconciliations`
- `pos_sessions`

## Depends on

Other modules imported from here: `analytics`, `catalog`, `customers`, `identity`, `inventory`, `orders`.
Import boundaries between modules are ratcheted by `tests/test_module_boundaries.py`; do not add
new cross-module imports without a reason, and never raise that baseline yourself.

## Rules for working here

- Business rules live in the service layer. Routers parse and authorise, then call a service.
- Services `flush()` and never `commit()`; the caller owns the transaction.
- Every tenant table has row-level security. Bind the tenant before touching data.
- Emit events through the outbox in the same transaction as the change.
- Tests for this module are in `backend/tests/` (search for `pos` in the file names and imports).

_The sections above are derived from the code; if you change the structure, update them._
