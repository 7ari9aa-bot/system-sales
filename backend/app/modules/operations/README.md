# operations

OPERATIONS domain — tasks, SLA, business calendars (spec §46, §83).

## Where things are

- `models.py`
- `router.py`
- `routers/`
- `schemas.py`
- `sla.py`
- `slo_service.py`
- `task_service.py`

## HTTP

20 endpoints. Route prefixes: `/search`, `/sla`. Registered in `app/main.py`.

## Tables

- `business_calendars`
- `sla_events`
- `sla_policies`
- `tasks`

## Depends on

Other modules imported from here: `ai`, `identity`, `platform`.
Import boundaries between modules are ratcheted by `tests/test_module_boundaries.py`; do not add
new cross-module imports without a reason, and never raise that baseline yourself.

## Rules for working here

- Business rules live in the service layer. Routers parse and authorise, then call a service.
- Services `flush()` and never `commit()`; the caller owns the transaction.
- Every tenant table has row-level security. Bind the tenant before touching data.
- Emit events through the outbox in the same transaction as the change.
- Tests for this module are in `backend/tests/` (search for `operations` in the file names and imports).

_The sections above are derived from the code; if you change the structure, update them._
