# expenses

EXPENSES domain: categories, posted expenses, document counters.

## Where things are

- `models.py`
- `router.py`
- `service.py`

## HTTP

6 endpoints. Route prefixes: `/expenses`. Registered in `app/main.py`.

## Tables

- `document_counters`
- `expense_categories`
- `expenses`

## Depends on

Other modules imported from here: `identity`, `orders`.
Import boundaries between modules are ratcheted by `tests/test_module_boundaries.py`; do not add
new cross-module imports without a reason, and never raise that baseline yourself.

## Rules for working here

- Business rules live in the service layer. Routers parse and authorise, then call a service.
- Services `flush()` and never `commit()`; the caller owns the transaction.
- Every tenant table has row-level security. Bind the tenant before touching data.
- Emit events through the outbox in the same transaction as the change.
- Tests for this module are in `backend/tests/` (search for `expenses` in the file names and imports).

_The sections above are derived from the code; if you change the structure, update them._
