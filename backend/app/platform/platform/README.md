# platform

PLATFORM domain — integrations, webhooks, notifications, automations, outbox_events, idempotency_keys, audit_logs.

## Where things are

- `channel_specs/`
- `diagnostics.py`
- `dr.py`
- `flags.py`
- `impersonation.py`
- `integration_verifier.py`
- `metrics.py`
- `models.py`
- `router.py`
- `routers/`
- `schemas.py`
- `security_events.py`
- `service.py`
- `services/`
- `tenant_restore.py`

## HTTP

37 endpoints. Route prefixes: `/platform`. Registered in `app/main.py`.

## Tables

- `audit_logs`
- `automations`
- `delivery_attempts`
- `dr_policy`
- `event_log`
- `feature_flags`
- `idempotency_keys`
- `inbound_message_dedupe`
- `integrations`
- `jobs`
- `metric_definitions`
- `notification_preferences`
- `notifications`
- `outbox_events`
- `processed_events`
- `restore_test_runs`
- `saved_views`
- `scheduled_jobs`
- `secret_references`
- `secret_values`
- `security_events`
- `tenant_restore_jobs`
- `webhook_deliveries`
- `webhook_events`
- `webhooks`

## Depends on

Other modules imported from here: `identity`.
Import boundaries between modules are ratcheted by `tests/test_module_boundaries.py`; do not add
new cross-module imports without a reason, and never raise that baseline yourself.

## Rules for working here

- Business rules live in the service layer. Routers parse and authorise, then call a service.
- Services `flush()` and never `commit()`; the caller owns the transaction.
- Every tenant table has row-level security. Bind the tenant before touching data.
- Emit events through the outbox in the same transaction as the change.
- Tests for this module are in `backend/tests/` (search for `platform` in the file names and imports).

_The sections above are derived from the code; if you change the structure, update them._
