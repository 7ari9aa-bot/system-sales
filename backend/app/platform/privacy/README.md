# privacy

PRIVACY domain — consent, data-subject requests, retention (spec §51-52).

## Where things are

- `meta_deletion.py` (Meta's data-deletion callback: verify `signed_request`, open a `delete` request)
- `models.py`
- `router.py`
- `service.py`

## HTTP

9 endpoints. Route prefixes: `/privacy`, and the public `/webhooks/meta/data-deletion` (Meta's
deletion callback and its status page, authenticated only by the signed request). Registered in
`app/main.py`.

The callback only OPENS a deletion request; it never erases. The merchant executes it from the
privacy screen, because a signature check alone must not be able to trigger an irreversible erasure.

## Tables

- `consents`
- `data_subject_requests`
- `retention_policies`

## Depends on

Other modules imported from here: `customers`, `identity`.
Import boundaries between modules are ratcheted by `tests/test_module_boundaries.py`; do not add
new cross-module imports without a reason, and never raise that baseline yourself.

## Rules for working here

- Business rules live in the service layer. Routers parse and authorise, then call a service.
- Services `flush()` and never `commit()`; the caller owns the transaction.
- Every tenant table has row-level security. Bind the tenant before touching data.
- Emit events through the outbox in the same transaction as the change.
- Tests for this module are in `backend/tests/` (search for `privacy` in the file names and imports).

_The sections above are derived from the code; if you change the structure, update them._
