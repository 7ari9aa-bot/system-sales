# customers

CUSTOMERS domain — customers, customer_identities, addresses, tags, notes, events.

## Where things are

- `meta_oauth.py`
- `meta_whatsapp_signup.py`
- `models.py`
- `router.py`
- `routers/`
- `schemas.py`
- `service.py`
- `services/`
- `timeline.py`

## HTTP

26 endpoints. Route prefixes: see `router.py`. Registered in `app/main.py`.

## Tables

- `addresses`
- `customer_events`
- `customer_identities`
- `customers`
- `identity_merge_candidates`
- `identity_merge_events`
- `notes`
- `tags`

## Depends on

Other modules imported from here: `billing`, `conversations`, `identity`, `platform`.
Import boundaries between modules are ratcheted by `tests/test_module_boundaries.py`; do not add
new cross-module imports without a reason, and never raise that baseline yourself.

## Rules for working here

- Business rules live in the service layer. Routers parse and authorise, then call a service.
- Services `flush()` and never `commit()`; the caller owns the transaction.
- Every tenant table has row-level security. Bind the tenant before touching data.
- Emit events through the outbox in the same transaction as the change.
- Tests for this module are in `backend/tests/` (search for `customers` in the file names and imports).

_The sections above are derived from the code; if you change the structure, update them._
