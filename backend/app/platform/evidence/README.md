# evidence

EVIDENCE domain — the Evidence Platform (V12 §9).

## Where things are

- `models.py`
- `router.py`
- `schemas.py`
- `service.py`

## HTTP

6 endpoints. Route prefixes: `/evidence`. Registered in `app/main.py`.

## Tables

- `evidence_facts`
- `evidence_sets`

## Depends on

Other modules imported from here: `identity`.
Import boundaries between modules are ratcheted by `tests/test_module_boundaries.py`; do not add
new cross-module imports without a reason, and never raise that baseline yourself.

## Rules for working here

- Business rules live in the service layer. Routers parse and authorise, then call a service.
- Services `flush()` and never `commit()`; the caller owns the transaction.
- Every tenant table has row-level security. Bind the tenant before touching data.
- Emit events through the outbox in the same transaction as the change.
- Tests for this module are in `backend/tests/` (search for `evidence` in the file names and imports).

_The sections above are derived from the code; if you change the structure, update them._
