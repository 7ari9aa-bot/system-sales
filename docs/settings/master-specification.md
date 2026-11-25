# Settings Master Specification

> **Status:** live — the executive index for the Settings Configuration Control Plane.
> **Last updated:** 2026-11-25 · **Source:** `backend/app/modules/settings/`

## 0. Purpose

This is the **one document that ties the settings specification together**. It is not a
replacement for the three companion documents — it is the map that tells you which one to
read and a P0–P4 progress report derived from the actual code.

| Document | What it covers | Read when… |
|---|---|---|
| [domain-specification.md](domain-specification.md) | Architecture, scope hierarchy, types, sensitivity, apply modes, read paths | You need to understand how settings resolve and why the system is built this way |
| [registry-specification.md](registry-specification.md) | Every setting key: type, default, scopes, constraints, segments, enforced status | You need the full table of 127 keys (auto-generated from `registry.py`) |
| [database-api-specification.md](database-api-specification.md) | Tables, columns, constraints, RLS, HTTP endpoints, request/response shapes, errors | You are building a client or touching the database schema |
| [frontend-specification.md](frontend-specification.md) | Settings screens, navigation by P1–P3, `/settings/effective` consumption, per-screen status | You are changing a settings screen or migrating to the unified API |
| [runtime-testing-specification.md](runtime-testing-specification.md) | Workers, outbox, event bus, scheduler, settings→runtime wiring map, testing strategy, CI checks, run commands | You are debugging a worker, adding a scheduler job, or writing a settings test |

> The code is the contract. If any document and the code disagree, the code wins.

---

## 1. What exists (from the code)

### Files and responsibilities

| File | Lines (approx) | Responsibility |
|---|---|---|
| `registry.py` | ~2346 | Static registry: every `SettingDef` with type, scope, default, validation, labels |
| `service.py` | ~850 | Hierarchical resolver, CRUD, change requests, rollback — sole writer to `tenant_settings` |
| `models.py` | ~180 | 3 tables: `tenant_settings`, `tenant_settings_history`, `setting_change_requests` |
| `router.py` | ~500 | 17 REST endpoints under `/settings` |
| `schemas.py` | ~130 | Pydantic input/output schemas |
| `policy.py` | ~55 | Per-key, per-scope write authorization |
| `scope_graph.py` | ~150 | Inheritance chain resolution from the database |
| `presets.py` | ~140 | 5 business-type presets |
| `capabilities.py` | ~220 | 8 vertical-based capabilities + owner overrides |
| `events.py` | ~60 | `settings.changed` event for the transactional outbox |

### Key numbers

| Metric | Value |
|---|---|
| Total setting keys | 127 |
| Domains | 18 |
| Enforced keys (read by a service) | ~90+ (tracked by `ENFORCED_KEYS`) |
| Presets | 5 |
| Capabilities | 8 |
| Verticals | 4 (`general`, `apparel`, `pharmacy`, `restaurant`) |
| Scopes | 8 (`tenant`, `workspace`, `branch`, `warehouse`, `pos_profile`, `register`, `channel`, `user`) |
| Tables | 3 (all RLS-protected) |
| HTTP endpoints | 17 |

---

## 2. P0–P4 Implementation Map

Each item below is derived from the actual code — the file that implements it or the gap
where it should be. Status: ✅ implemented · 🟡 partial · ❌ missing.

### P0 — Architecture Foundation ✅

| Item | Status | Evidence |
|---|---|---|
| Static registry (`SettingDef` for every key) | ✅ | `registry.py` — 127 definitions |
| Scope hierarchy with DB-driven chain resolution | ✅ | `scope_graph.py` — `resolve_chain` reads parent links from `pos_registers`, `pos_profiles`, `warehouses`, `locations` |
| Hierarchical resolver (walk chain → pick first override → fall back to default) | ✅ | `service.py` — `resolve_many`, `_pick` |
| Value validation and coercion per type | ✅ | `registry.py` — `SettingDef.validate()` |
| Per-key write authorization (`settings:write`, `settings:branch_write`) | ✅ | `policy.py` — `authorize_write` |
| Audit trail (append-only history) | ✅ | `models.py` — `TenantSettingHistory`; `service.py` — `_record` |
| Transactional outbox event on every write | ✅ | `events.py` — `settings.changed`; `service.py` — `add_outbox_event` in `_record` |
| Rollback to a previous revision | ✅ | `service.py` — `rollback` (creates a NEW revision, does not delete history) |
| RLS on all three tables | ✅ | Migrations `fe2026111801`, `fe2026112501` — `ENABLE ROW LEVEL SECURITY` + `FORCE` + `tenant_isolation` policy |
| Optimistic concurrency (`expected_history_id`) | ✅ | `service.py` — `set` with `expected_history_id` → `ConflictError` |
| Unique constraint with `NULLS NOT DISTINCT` | ✅ | Migration `fe2026111802` — prevents duplicate tenant-level rows |

### P1 — Business Configuration ✅

| Item | Status | Evidence |
|---|---|---|
| Business profile (legal name, tax ID, address, phone, email) | ✅ | `registry.py` — `business.*` (11 keys); consumed by `pos/receipt_settings.py`, `pos/eta_adapter.py` |
| Business type & vertical (segment selection) | ✅ | `registry.py` — `business.type`, `business.vertical`; consumed by `core/shop_type.py` |
| POS / cashier settings (discount, returns, payments, drawer) | ✅ | `registry.py` — `pos.*` (16 keys); consumed by `pos/service.py` |
| Inventory settings (reserve, FIFO, locations, stocktake) | ✅ | `registry.py` — `inventory.*` (12 keys); consumed by `orders/service.py`, `inventory/services/*` |
| Orders lifecycle (reserve_on, deduct_stock_on, backorder) | ✅ | `registry.py` — `orders.*` (3 keys); consumed by `orders/service.py` |
| Purchasing (approvals, partial/over receipt, centralized) | ✅ | `registry.py` — `purchasing.*` (5 keys); consumed by `purchasing/service.py` |
| Catalog (SKU, barcode, tax rate, out-of-stock) | ✅ | `registry.py` — `catalog.*` (5 keys); consumed by `catalog/services/*`, `ai/agents/customer/tools/catalog.py` |
| E-invoice / ETA (15 keys) | ✅ | `registry.py` — `einvoice.*`; consumed by `pos/eta_adapter.py`, `einvoice/providers/eta/delivery.py` |
| Print & receipt settings | ✅ | `registry.py` — `print.*` (8 keys); consumed by `pos/receipt_settings.py` |
| Capabilities (vertical → owner switches) | ✅ | `capabilities.py` — 8 capabilities; `registry.py` — `capability.*` keys |
| Presets (5 business-type starting configurations) | ✅ | `presets.py` — `physical_retail`, `ecommerce`, `omnichannel`, `enterprise`, `apparel_ground_shop` |
| Reports access control (`managers_see_profit`) | ✅ | `registry.py` — `reports.managers_see_profit`; consumed by `core/profit_report.py` |

### P2 — Communication & Intelligence ✅ (partial)

| Item | Status | Evidence |
|---|---|---|
| Customer AI agent settings (enabled, dialect, formality, handoff) | ✅ | `registry.py` — `customer_agent.*` (8 keys); consumed by `ai/hooks.py`, `ai/agents/customer/tools/*` |
| Analytics AI agent settings (enabled, period, confidence) | ✅ | `registry.py` — `analytics_agent.*` (4 keys); consumed by `ai/agents/sales_intelligence/agent.py` |
| Organization settings (multi-branch, max branches, fiscal year) | ✅ | `registry.py` — `organization.*` (5 keys) |
| Branch operational settings (auto-close shift, variance notify) | ✅ | `registry.py` — `branch.*` (4 keys); consumed by `pos/service.py`, `purchasing/service.py` |
| `organization.default_language` → frontend i18n | ✅ | Read by `core/organization_settings.py`; enforced |
| `organization.brand_color` → frontend CSS | ✅ | Read by `core/organization_settings.py`; enforced |
| `organization.fiscal_year_start_month` → reports | ✅ | Read by `core/organization_settings.py`; enforced |
| `print.barcode_format` → receipt barcode format | ✅ | Read by `pos/receipt_settings.py::receipt_settings`; enforced |
| `print.invoice_prefix` → POS invoice numbering | ✅ | Read by `pos/receipt_settings.py::receipt_settings`; enforced |

### P3 — Platform Management ✅ (settings wired, some consumers missing)

| Item | Status | Evidence |
|---|---|---|
| Team settings (default_role, require_2fa, session_timeout, allow_invites) | ✅ registered | `registry.py` — `team.*` (4 keys) |
| `team.require_2fa` → auth login enforcement | ✅ | `identity/services/auth.py` — direct SQL read |
| `team.session_timeout_minutes` → token TTL | ✅ | `identity/services/auth.py::_resolve_access_ttl`; enforced |
| `team.default_role` → invite default | ✅ | `identity/services/tenant.py::TenantService.invite`; enforced |
| `team.allow_member_invites` → invite gate | ✅ | `identity/services/tenant.py::TenantService.invite`; enforced |
| Security settings (passwords, API rotation, audit retention, IP allowlist) | ✅ registered | `registry.py` — `security.*` (4 keys) |
| `security.require_strong_passwords` → auth validation | ✅ | `identity/services/auth.py` — direct SQL read; enforced |
| `security.api_key_rotation_days` → secrets rotation | ✅ | `core/api_key_rotation.py` — reads via `settings_read` resolver; `scheduler_worker._handle_secret_rotation_sweep` calls `due_secret_references` and notifies owners; enforced |
| `security.audit_retention_days` → audit retention sweep | ✅ | `scheduler_worker._handle_audit_retention_sweep` deletes `audit_logs` older than the window daily; 0 = skip; enforced |
| `security.ip_allowlist` → middleware gate | ✅ | `identity/deps.py` `get_current_user`; enforced |
| Notification settings (low stock, order received, quiet hours, digest) | ✅ registered | `registry.py` — `notifications.*` (7 keys) |
| `notifications.low_stock_alert` → scheduler worker | ✅ | Consumed by `scheduler_worker` |
| `notifications.order_received` → order worker | ✅ | Consumed by `orders/service.py` |
| `notifications.quiet_hours_*` / `digest_mode` → digest service | ✅ | `notifications/digest.py` — direct SQL read |
| `notifications.email_enabled` → email dispatch | ✅ | `notifications/service.py::dispatch` + `NotificationDeliveryWorker` second gate; enforced |
| `notifications.push_enabled` → push dispatch | ✅ | `notifications/service.py::dispatch` + `NotificationDeliveryWorker` second gate; enforced |
| Billing settings (auto_renew, currency, renewal reminder) | ✅ registered | `registry.py` — `billing.*` (3 keys) |
| `billing.auto_renew` → trial expiry lock | ✅ | `billing/services/trial_expiry.py` — direct SQL read; enforced |
| `billing.notify_before_renewal_days` → renewal reminder | ✅ | `billing/services/trial_expiry.py::_tenant_billing_config`; enforced |
| `billing.currency` → billing config | ✅ | `billing/services/trial_expiry.py::_tenant_billing_config`; enforced |
| Frontend unified consumption of `/settings/effective` | 🟡 | `useSettings` shared hook + `UnifiedSettings` page (`/settings/all`) consume all settings via `/settings/effective`, grouped by domain; legacy per-domain screens still exist |

### P4 — Advanced Governance 🟡 (partial)

| Item | Status | Evidence |
|---|---|---|
| Change requests (approval-gated settings) | ✅ | `models.py` — `SettingChangeRequest`; `service.py` — `create_change_request`, `approve`, `reject`; `router.py` — 4 endpoints |
| Change request lifecycle (draft → applied) | ✅ | `models.py` — `CHANGE_REQUEST_STATES` (11 states); `service.py` — full lifecycle |
| `reviewed_at` column in change requests | ✅ | `models.py` — `TIMESTAMP(timezone=True)` column; set by `approve_change_request` and `reject_change_request` |
| Config migration framework | ✅ | `config_migrations.py` — `ConfigMigration`, `MIGRATIONS`, `run_pending` (idempotent); `models.py` — `SettingMigrationLog`; `router.py` — `GET /settings/migrations`, `POST /settings/migrations/run` |
| Tenant-scoped restore (§164) | ✅ | `service.py` — `restore_to_snapshot`; `router.py` — `POST /settings/restore` (admin-gated, audit-logged, RLS-isolated) |
| SLO framework (§168) | ❌ | No SLO monitoring or alerting for settings |
| Extended/dynamic presets | ❌ | Presets are static in `presets.py`; no runtime preset creation |
| SecretStore integration for `sensitivity=secret` settings | ✅ | `core/secrets.py` — `EnvelopeSecretStore` + rotation; no setting uses `secret` sensitivity yet |
| Guard test: enforced keys | ✅ | `tests/test_settings_enforced_keys.py` — bidirectional check |
| Guard test: registry spec in sync | ✅ | `tests/test_registry_spec_in_sync.py` — `--check` mode |

---

## 3. Scope hierarchy

```
TENANT (root — no scope_id)
  ├── WORKSPACE
  │     └── BRANCH
  │           └── WAREHOUSE
  │                 └── POS_PROFILE
  │                       └── REGISTER
  ├── CHANNEL  (resolves through the serving warehouse)
  └── USER     (personal — inherits directly from tenant)
```

A value at a narrower scope shadows the same key at a broader scope. When no override
exists at any scope, the registry default is returned.

---

## 4. Read paths

| Pattern | Used by | When |
|---|---|---|
| `SettingsService(session, tenant_id).value(key)` | POS, orders, inventory, purchasing, catalog, AI, e-invoice | Standard — no cycle risk |
| `app.core.settings_read.resolve_settings` | identity, billing, notifications | Avoids cyclic imports (identity → settings) |

See [domain-specification.md §8](domain-specification.md) for the full consumer map.

---

## 5. Generation and CI

The registry specification is auto-generated:

```bash
cd backend
python scripts/dev/gen_registry_spec.py          # regenerate docs/settings/registry-specification.md
python scripts/dev/gen_registry_spec.py --check   # CI: exit 1 if doc drifts from code
```

The CI test `tests/test_registry_spec_in_sync.py` runs `--check` on every push. A PR that
changes `registry.py` without regenerating the spec fails CI.

---

## 6. What is done and what is left

### Done ✅

- 127 setting keys across 18 domains, all defined in a static registry
- 3 RLS-protected tables with full audit trail
- 17 HTTP endpoints with hierarchical resolution, optimistic concurrency, and rollback
- Change request lifecycle for approval-gated settings
- 5 business-type presets and 8 vertical-based capabilities
- `settings.changed` outbox event for cache invalidation
- ~90+ keys actively consumed by services (enforced)
- Guard tests for enforced keys and registry spec sync

### Remaining 🟡 / ❌

| Area | What is left | Priority |
|---|---|---|
| ~~Unwired keys~~ | `security.audit_retention_days` now wired to `audit_retention_sweep` | ✅ P3 |
| Notification delivery worker | Consumes `notification.email` / `notification.push` from outbox; Resend email adapter + FCM push adapter + fake providers for tests | P3 |
| API key rotation | `core/api_key_rotation.py` reads via `settings_read` resolver; `scheduler_worker._handle_secret_rotation_sweep` sweeps per tenant every 24h and notifies owners | ✅ P3 |
| Frontend | `useSettings` shared hook + `UnifiedSettings` page (`/settings/all`) now consume `/settings/effective` for all domains; legacy per-domain screens still migrate incrementally (see [frontend-specification.md](frontend-specification.md)) | 🟡 P3 |
| Config migrations | Versioned settings schema migration framework | P4 |
| Tenant restore | §164 tenant-scoped restore from backup | P4 |
| SLO framework | §168 SLO monitoring for settings | P4 |
| Dynamic presets | Runtime preset creation based on vertical | P4 |
