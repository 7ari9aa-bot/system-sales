# billing

BILLING domain — plans, subscriptions, entitlements, usage, invoices.

## Where things are

- `models.py`
- `router.py`
- `service.py`
- `services/`

## HTTP

9 endpoints. Route prefixes: `/billing`, `/webhook-endpoints`. Registered in `app/main.py`.

## Tables

- `entitlements`
- `invoices`
- `plans`
- `subscriptions`
- `usage_records`

## Depends on

Other modules imported from here: `identity`, `platform`.
Import boundaries between modules are ratcheted by `tests/test_module_boundaries.py`; do not add
new cross-module imports without a reason, and never raise that baseline yourself.

## Rules for working here

- Business rules live in the service layer. Routers parse and authorise, then call a service.
- Services `flush()` and never `commit()`; the caller owns the transaction.
- Every tenant table has row-level security. Bind the tenant before touching data.
- Emit events through the outbox in the same transaction as the change.
- Tests for this module are in `backend/tests/` (search for `billing` in the file names and imports).

_The sections above are derived from the code; if you change the structure, update them._
