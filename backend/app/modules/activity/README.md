# activity

The read-only operations timeline: a feed and summary of what happened in the shop.

## Where things are

- `router.py`
- `service.py`

## HTTP

2 endpoints. Route prefixes: `/activity`. Registered in `app/main.py`.

## Tables

None. This module has no tables of its own.

## Depends on

Other modules imported from here: `analytics`, `identity`.
Import boundaries between modules are ratcheted by `tests/test_module_boundaries.py`; do not add
new cross-module imports without a reason, and never raise that baseline yourself.

## Rules for working here

- Business rules live in the service layer. Routers parse and authorise, then call a service.
- Services `flush()` and never `commit()`; the caller owns the transaction.
- Every tenant table has row-level security. Bind the tenant before touching data.
- Emit events through the outbox in the same transaction as the change.
- Tests for this module are in `backend/tests/` (search for `activity` in the file names and imports).

_The sections above are derived from the code; if you change the structure, update them._
