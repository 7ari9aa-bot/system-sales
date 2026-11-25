# settings

SETTINGS domain —
FIHRIST Configuration Control Plane (Retail Operations Configuration v2).

## Where things are

- `models.py`: Database models (`tenant_settings`, `tenant_settings_history`, `setting_change_requests`)
- `registry.py`: Settings Registry and definitions (`SettingDef`, types, scopes, validation, `ApplyMode`, `Sensitivity`)
- `service.py`: Hierarchical resolver, CRUD, change management, rollback (`SettingsService`)
- `presets.py`: Out-of-the-box configuration presets (`physical_retail`, `ecommerce`, `omnichannel`, `enterprise`)
- `schemas.py`: Pydantic input/output schemas
- `router.py`: REST endpoints mounted under `/settings`
- `events.py`: `settings.changed` event type for the transactional outbox (§36–§38)
- `policy.py`: Permission-based write authorization
- `scope_graph.py`: Scope hierarchy resolution from the database
- `capabilities.py`: Vertical-based capability defaults and owner overrides

## HTTP

Endpoints registered in `app/main.py`:
- `GET /settings/definitions`: Lists setting definitions and metadata (`?domain=`, `?segment=retail|fnb|services|wholesale`)
- `GET /settings/domains`: Lists registered domains
- `GET /settings/capabilities`: Shop's vertical and enabled capabilities
- `GET /settings/effective`: Resolves effective settings with hierarchical inheritance
- `GET /settings/effective/{key}`: Resolves single setting key
- `GET /settings/overrides`: Lists raw tenant overrides
- `PUT /settings/{key}`: Sets a scoped override (supports `expected_history_id` for optimistic concurrency)
- `POST /settings/bulk`: Sets multiple overrides at once
- `DELETE /settings/{key}`: Reverts an override to inherited value
- `GET /settings/presets`: Lists presets
- `POST /settings/presets/{preset_name}`: Applies a preset at tenant scope
- `GET /settings/history`: Audit log of configuration changes
- `POST /settings/change-requests`: Create a change request for approval-gated settings (§28)
- `GET /settings/change-requests`: List change requests (optional `?status=` filter)
- `POST /settings/change-requests/{id}/approve`: Approve and apply a change request
- `POST /settings/change-requests/{id}/reject`: Reject a change request
- `POST /settings/rollback`: Roll back a setting to a previous revision (§34)

## Tables

- `tenant_settings` (overrides table with full tenant isolation RLS)
- `tenant_settings_history` (append-only change audit log with RLS)
- `setting_change_requests` (change request lifecycle with RLS, §28)

## Architecture contracts (§11, §27)

Every `SettingDef` now carries:
- `apply_mode`: `immediate` | `validated` | `approval_required` — how a change reaches the runtime
- `sensitivity`: `normal` | `sensitive` | `secret` — data classification
- `feature_requirement`: optional entitlement link (§72)
- `rollback_supported`: whether this setting can be rolled back (§35)

## Event-driven sync (§36–§38)

Every setting write (set, reset, bulk_set) stages a `settings.changed` event in the
transactional outbox, in the same transaction as the write. Runtime systems (POS,
inventory, agents) consume the event and invalidate their cached config. The event
carries the key, scope, revision (history row id), and action for idempotency.

## Depends on

- Core: `app.core.db`, `app.core.model_kit`, `app.core.events.writer`, `app.core.audit`
- Auth: `app.modules.identity.deps` (TenantContext, require_permission)

## Rules for working here

- Every new setting must be defined in `registry.py` with its type, default, allowed scopes, and `apply_mode`.
- Decide a new setting's `segments` on purpose: `()` (the default) means every kind of business sees
  it; name segments only when the key is meaningless to the others (shelf stock for a services
  shop). Segments only change what the settings screen lists, never what a key resolves to, so the
  code that reads it never branches on the segment.
- Database stores overrides only; defaults stay in code.
- Scoped inheritance walks: `register -> pos_profile -> warehouse -> branch -> tenant -> default`.
- All writes are audited in `tenant_settings_history` and stage a `settings.changed` outbox event.
- Services `flush()` and never `commit()`.
- For approval-gated settings (`apply_mode = approval_required`), use `create_change_request` —
  never call `set` directly.
