# authority

Authority domain module (V12 Wave B): Capability Grants & Authority Leases.

## Where things are

- `executor.py`
- `models.py`
- `router.py`
- `schemas.py`
- `service.py`

## HTTP

11 endpoints. Route prefixes: `/authority`. Registered in `app/main.py`.

## Tables

- `authority_leases`
- `autonomy_budgets`
- `budget_reservations`
- `capability_grants`

## Depends on

Other modules imported from here: `decisions`, `identity`.
Import boundaries between modules are ratcheted by `tests/test_module_boundaries.py`; do not add
new cross-module imports without a reason, and never raise that baseline yourself.

## Rules for working here

- Business rules live in the service layer. Routers parse and authorise, then call a service.
- Services `flush()` and never `commit()`; the caller owns the transaction.
- Every tenant table has row-level security. Bind the tenant before touching data.
- Emit events through the outbox in the same transaction as the change.
- Tests for this module are in `backend/tests/` (search for `authority` in the file names and imports).

_The sections above are derived from the code; if you change the structure, update them._
