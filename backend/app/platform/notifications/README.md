# notifications

Notification infrastructure: per-user notifications and digest aggregation (spec section 166).

## Where things are

- `digest.py`
- `models.py`
- `router.py`
- `schemas.py`
- `service.py`

## HTTP

7 endpoints. Route prefixes: `/notifications`. Registered in `app/main.py`.

## Tables

- `notification_digests`
- `notification_preferences`

## Depends on

Other modules imported from here: `identity`, `platform`.
Import boundaries between modules are ratcheted by `tests/test_module_boundaries.py`; do not add
new cross-module imports without a reason, and never raise that baseline yourself.

## Rules for working here

- Business rules live in the service layer. Routers parse and authorise, then call a service.
- Services `flush()` and never `commit()`; the caller owns the transaction.
- Every tenant table has row-level security. Bind the tenant before touching data.
- Emit events through the outbox in the same transaction as the change.
- Tests for this module are in `backend/tests/` (search for `notifications` in the file names and imports).

_The sections above are derived from the code; if you change the structure, update them._
