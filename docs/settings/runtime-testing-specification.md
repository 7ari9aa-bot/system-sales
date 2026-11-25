# Runtime & Testing Specification

> **Status:** specification derived from actual backend code.
> **Last updated:** 2026-11-25 · **Source:** `backend/app/workers/`, `backend/app/core/events/`, `backend/tests/`, `.github/workflows/ci.yml`

## 0. Purpose

This document describes how the settings control plane operates at runtime — the workers,
the outbox, the event bus — and the testing strategy that keeps it honest. It is derived from
the actual code, not from a design document.

---

## 1. Runtime architecture

### Worker pools

The worker process (`python -m app.workers.run`) starts the outbox relay plus every worker
pool in one process. The pools are declared in `app/workers/run.py::POOLS`:

| Pool | Worker class | Stream | Role |
|---|---|---|---|
| `messages` | `MessageWorker` | `message.events` | Inbound/outbound message processing |
| `notifications` | `NotificationWorker` | `notification.events` | In-app notification creation |
| `notification_delivery` | `NotificationDeliveryWorker` | `notification.events` | Email/push delivery (second gate) |
| `webhooks` | `WebhookWorker` | `webhook.events` | Outbound webhook delivery |
| `campaigns` | `CampaignWorker` | `campaign.events` | Bulk campaign execution |
| `scheduler` | `SchedulerWorker` | `platform.events` | Scheduled job polling + global sweepers |
| `jobs` | `JobRunner` | `job.events` | Long-running job execution |
| `pos` | `PosWorker` | `pos_session.events` | POS async surface (projections, receipt email) |

### Outbox relay

The outbox (`OutboxRelay`) is the durability backbone. Every domain event is staged in the
`outbox_events` table in the SAME transaction as the business change. The relay polls the
table, publishes events to Redis Streams, and marks rows as published.

**Flow:**
1. A service writes a business change + an `add_outbox_event()` call in one transaction.
2. The relay picks up `pending` rows, publishes to the stream, marks `published`.
3. Stream workers consume the event and execute the effect.

### Event bus

Redis Streams (`RedisStreamsBus`) is the transport. Each event carries a typed envelope
(`EventEnvelope`) with routing keys (type, tenant_id, aggregate_type, aggregate_id) and a
payload. The envelope is serialized to `payload` + `meta` JSON fields.

**Settings-relevant event types:**
* `settings.changed` — emitted on every settings write (for cache invalidation).
* `notification.email` — staged by `NotificationService._send_email` when `email_enabled` is True.
* `notification.push` — staged by `NotificationService._send_push` when `push_enabled` is True.
* `platform.secret_rotated` — emitted on master-key rotation.

### Scheduler

The `SchedulerWorker` polls `scheduled_jobs` for due work. Recurring sweeps are seeded at
boot via `ensure_recurring_jobs()` (one row per active tenant per job type, idempotent via
`ON CONFLICT DO NOTHING`).

**Settings-relevant recurring jobs:**

| Job type | Interval | Handler | Settings consumed |
|---|---|---|---|
| `inventory.low_stock_alerts` | (on demand) | `_handle_low_stock_alerts` | `notifications.low_stock_alert` |
| `pos.auto_close_shifts` | (on demand) | `_handle_auto_close_shifts` | `branch.auto_close_shift`, `branch.shift_end_time` |
| `secret_rotation_sweep` | 24h | `_handle_secret_rotation_sweep` | `security.api_key_rotation_days` |
| `einvoice.eta_deliver` | 1 min | `_handle_eta_deliver` | `einvoice.*` (via `eta_settings`) |

**Global sweepers** (not tenant-scoped, no `scheduled_jobs` row):

| Sweeper | Interval | Settings consumed |
|---|---|---|
| `billing.lock_expired_trials` | 30 min | `billing.auto_renew` (via `trial_expiry.py`) |

### Notification delivery worker

`NotificationDeliveryWorker` is the SECOND gate for email/push delivery. The first gate is
`NotificationService.dispatch`, which checks `notifications.email_enabled` /
`notifications.push_enabled` before staging the outbox event. The worker re-checks the setting
at delivery time so a tenant that disables email after an event was staged does not send a
stale message.

**Provider selection:**
* Email: `ResendEmailProvider` (production) or `FakeEmailProvider` (tests).
* Push: `FCMPushProvider` (production) or `FakePushProvider` (tests).

---

## 2. Settings read paths at runtime

| Pattern | Used by | When |
|---|---|---|
| `SettingsService(session, tenant_id).value(key)` | POS, orders, inventory, purchasing, catalog, AI, e-invoice | Standard — no cycle risk |
| `app.core.settings_read.resolve_setting` / `resolve_settings` | identity, billing, notifications, API key rotation | Avoids cyclic imports (identity → settings) |
| `app.core.settings_read.setting_bool` | notification delivery worker | Quick boolean check |

The `settings_read` module mirrors `SettingsService.resolve` but is read-only and lives in
`app.core` so modules that share a cyclic SCC with `settings` can read settings without
importing the settings module.

---

## 3. Testing strategy

### Test layers

| Layer | What it covers | Command |
|---|---|---|
| Unit (no DB) | Pure logic: `is_rotation_due`, registry validation, provider protocol | `pytest tests/test_api_key_rotation.py::TestIsRotationDue` |
| Behavioural (DB) | End-to-end settings consumption: resolve → check → act | `pytest tests/test_api_key_rotation.py::TestResolveRotationDays` |
| Worker tests | Worker handle() with fake providers and shared DB session | `pytest tests/test_notification_delivery_worker.py` |
| Scheduler handler tests | Scheduler job handlers with real DB + fake notifications | `pytest tests/test_secret_rotation_sweep.py` |
| Provider tests | HTTP adapter with fake client, no network | `pytest tests/test_fcm_push_provider.py` |
| Guard tests | Enforced keys, registry spec sync, module boundaries | `pytest tests/test_settings_enforced_keys.py tests/test_registry_spec_in_sync.py` |

### Test conventions

* Database-backed tests use the `db` fixture (shared async session). They skip silently when
  no database is configured — a skip is NOT a pass.
* A bug fix needs a test that fails without the fix and passes with it.
* Worker tests inject fake providers (`FakeEmailProvider`, `FakePushProvider`) so no network
  is touched.
* Provider tests inject a fake HTTP client (`FakeFCMClient`, or `httpx.MockTransport`) to
  verify request shape and error handling.
* Scheduler handler tests call the handler function directly with the shared DB session,
  avoiding the need for a running Redis stream.

### Settings-specific guard tests

| Test | What it guards |
|---|---|
| `test_settings_enforced_keys.py` | Every key in `ENFORCED_KEYS` is actually read by code, and every read key is listed. Bidirectional. |
| `test_registry_spec_in_sync.py` | The auto-generated `registry-specification.md` matches `registry.py`. Runs `gen_registry_spec.py --check`. |
| `test_module_boundaries.py` | Cross-module imports are ratcheted. Adding a new import from `settings` into another module may raise the baseline. |

---

## 4. CI checks

From `.github/workflows/ci.yml`, the backend checks that must pass:

```bash
# Lint + format
ruff check app tests scripts
ruff format --check app tests scripts

# Migrations + provisioning
alembic upgrade head
python scripts/provision.py

# Tests (needs Postgres 17 + Redis 7)
ENVIRONMENT=test pytest -q
```

Settings-specific CI tests that run as part of `pytest -q`:

```bash
pytest tests/test_settings_enforced_keys.py -q          # enforced keys bidirectional check
pytest tests/test_registry_spec_in_sync.py -q           # registry spec drift check
pytest tests/test_api_key_rotation.py -q                # API key rotation behavioural tests
pytest tests/test_secret_rotation_sweep.py -q           # scheduler sweep + notification tests
pytest tests/test_notification_delivery_worker.py -q    # delivery worker tests
pytest tests/test_fcm_push_provider.py -q               # FCM push provider tests
```

Frontend CI:

```bash
cd frontend && npm run lint && npm test
```

---

## 5. Run commands

### Local development

```bash
# Start infrastructure
docker compose -f infra/docker-compose.yml up -d          # Postgres + Redis

# Backend
cd backend && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/uvicorn app.main:app --reload                   # API on :8000

# Workers (separate terminal)
cd backend && .venv/bin/python -m app.workers.run           # all pools

# Frontend
cd frontend && npm install && npm run dev                  # web app on :3000
```

### Running settings-specific tests

```bash
cd backend

# All settings tests
ENVIRONMENT=test pytest tests/test_settings_enforced_keys.py \
  tests/test_registry_spec_in_sync.py \
  tests/test_api_key_rotation.py \
  tests/test_secret_rotation_sweep.py \
  tests/test_notification_delivery_worker.py \
  tests/test_fcm_push_provider.py -q

# Regenerate registry spec
python scripts/dev/gen_registry_spec.py
python scripts/dev/gen_registry_spec.py --check    # CI mode
```

### Running individual worker pools

```bash
# Only the scheduler + notification delivery
python -m app.workers.run scheduler notification_delivery

# Only the notification delivery
python -m app.workers.run notification_delivery
```

---

## 6. Settings → runtime wiring map

This is the complete map of which settings key is consumed by which runtime component.

### Scheduler worker

| Key | Consumer | Effect |
|---|---|---|
| `security.api_key_rotation_days` | `_handle_secret_rotation_sweep` → `api_key_rotation.due_secret_references` | Flags overdue secrets, notifies owners |
| `notifications.low_stock_alert` | `_handle_low_stock_alerts` | Gates low-stock notification sweep |
| `branch.auto_close_shift` | `_handle_auto_close_shifts` | Gates auto-close of POS sessions |
| `branch.shift_end_time` | `_handle_auto_close_shifts` | Sets the cutoff time for auto-close |
| `einvoice.*` | `_handle_eta_deliver` → `eta_settings` | Configures ETA e-receipt delivery |

### Notification delivery worker

| Key | Consumer | Effect |
|---|---|---|
| `notifications.email_enabled` | `NotificationDeliveryWorker._handle_email` | Second gate: re-check at delivery time |
| `notifications.push_enabled` | `NotificationDeliveryWorker._handle_push` | Second gate: re-check at delivery time |

### Notification service

| Key | Consumer | Effect |
|---|---|---|
| `notifications.email_enabled` | `NotificationService.dispatch` | First gate: stage email event only when True |
| `notifications.push_enabled` | `NotificationService.dispatch` | First gate: stage push event only when True |
| `notifications.quiet_hours_start/end` | `notifications/digest.py::should_send_immediately` | Suppress delivery during quiet hours |
| `notifications.digest_mode` | `notifications/digest.py::should_send_immediately` | Controls realtime vs. digest delivery |

### Billing

| Key | Consumer | Effect |
|---|---|---|
| `billing.auto_renew` | `billing/services/trial_expiry.py::_should_lock` | Determines if expired trial locks the API |
| `billing.currency` | `billing/services/trial_expiry.py::_tenant_billing_config` | Sets billing currency |
| `billing.notify_before_renewal_days` | `billing/services/trial_expiry.py` | Days before renewal to send reminder |

### Identity / auth

| Key | Consumer | Effect |
|---|---|---|
| `team.require_2fa` | `identity/services/auth.py` login | Forces 2FA on login |
| `team.session_timeout_minutes` | `identity/services/auth.py::_resolve_access_ttl` | Adjusts token TTL |
| `team.allow_member_invites` | `identity/services/tenant.py::TenantService.invite` | Gates invite creation |
| `team.default_role` | `identity/services/tenant.py::TenantService.invite` | Fallback role for invites |
| `security.require_strong_passwords` | `identity/services/auth.py` | Validates password strength |
| `security.ip_allowlist` | `identity/deps.py::get_current_user` | IP-based access control |
