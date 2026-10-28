# identity

IDENTITY domain — tenants, users, tenant_users, roles, permissions.

## Where things are

- `bootstrap.py`
- `cookies.py`
- `deps.py`
- `email_delivery.py`
- `models.py`
- `router.py`
- `routers/`
- `schemas.py`
- `service.py`
- `services/`

## HTTP

37 endpoints. Route prefixes: `/hierarchy`, `/tenants`, `/users`. Registered in `app/main.py`.

## Tables

- `email_verification_tokens`
- `invitations`
- `locations`
- `password_reset_tokens`
- `permissions`
- `refresh_tokens`
- `roles`
- `tenant_users`
- `tenants`
- `user_location_access`
- `user_mfa_secrets`
- `users`
- `workspaces`

## Depends on

Other modules imported from here: `billing`, `platform`.
Import boundaries between modules are ratcheted by `tests/test_module_boundaries.py`; do not add
new cross-module imports without a reason, and never raise that baseline yourself.

## Rules for working here

- Business rules live in the service layer. Routers parse and authorise, then call a service.
- Services `flush()` and never `commit()`; the caller owns the transaction.
- Every tenant table has row-level security. Bind the tenant before touching data.
- Emit events through the outbox in the same transaction as the change.
- Tests for this module are in `backend/tests/` (search for `identity` in the file names and imports).

_The sections above are derived from the code; if you change the structure, update them._
