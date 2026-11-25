# Settings Database & API Specification

> Source of truth: `backend/app/modules/settings/` (code is the contract; this document describes it).
> Companion to [domain-specification.md](domain-specification.md) and [registry-specification.md](registry-specification.md).

## 1. Overview

The Settings domain persists configuration overrides in three PostgreSQL tables and exposes
them through a REST API mounted at `/settings`. This document covers the database schema
(columns, constraints, indexes, RLS), the HTTP endpoints, request/response shapes, and error
handling — all derived from the actual code in `backend/app/modules/settings/`.

---

## 2. Database Tables

### 2.1 `tenant_settings` — active overrides

Stores explicitly-set configuration values. One row = "at this scope, this key was set to this
value." The absence of a row means "inherit from the parent scope." The resolver walks up the
chain at read time; this table never stores inherited values.

| Column | Type | Nullable | Default | Notes |
|---|---|---|---|---|
| `id` | UUID | NO | `gen_random_uuid()` | Primary key |
| `tenant_id` | UUID | NO | — | FK → `tenants.id` ON DELETE CASCADE; RLS-protected |
| `key` | VARCHAR(127) | NO | — | Dotted setting identifier (e.g. `pos.max_discount_pct`) |
| `scope` | VARCHAR(31) | NO | `'tenant'` | One of: `tenant`, `workspace`, `branch`, `warehouse`, `pos_profile`, `register`, `channel`, `user` |
| `scope_id` | UUID | YES | NULL | Entity ID for non-tenant scopes; NULL = tenant-level |
| `value` | JSONB | NO | — | Always `{"v": <actual_value>}` — a dict with one key for lossless type round-trip |
| `updated_by` | UUID | YES | NULL | FK → `users.id` ON DELETE SET NULL; who last set this value |
| `created_at` | TIMESTAMP(tz) | NO | `now()` | |
| `updated_at` | TIMESTAMP(tz) | NO | `now()` | Auto-updated on write |

**Constraints:**

| Name | Type | Definition |
|---|---|---|
| `uq_tenant_settings_key_scope` | UNIQUE NULLS NOT DISTINCT | `(tenant_id, key, scope, scope_id)` — at most one override per key+scope; NULL scope_id collides with itself |
| `ck_tenant_settings_scope_id` | CHECK | `(scope = 'tenant') = (scope_id IS NULL)` — tenant scope has no scope_id; every other scope must |

**Indexes:**

| Name | Columns | Purpose |
|---|---|---|
| `ix_tenant_settings_tenant_key` | `(tenant_id, key)` | Lookup by key within a tenant |
| `ix_tenant_settings_tenant_scope` | `(tenant_id, scope, scope_id)` | Lookup by scope within a tenant |

**Migrations:**
- Created in `fe2026111801_retail_operations_configuration_engine.py`
- Unique constraint upgraded to `NULLS NOT DISTINCT` and check constraint added in `fe2026111802`

### 2.2 `tenant_settings_history` — append-only audit log

Every write (create, update, reset) appends one row. The settings table knows the current value;
this table knows the full timeline.

| Column | Type | Nullable | Default | Notes |
|---|---|---|---|---|
| `id` | UUID | NO | `gen_random_uuid()` | Primary key |
| `tenant_id` | UUID | NO | — | FK → `tenants.id` ON DELETE CASCADE; RLS-protected |
| `setting_id` | UUID | YES | NULL | FK → `tenant_settings.id` ON DELETE SET NULL; nulls when the setting is deleted |
| `key` | VARCHAR(127) | NO | — | Setting key |
| `scope` | VARCHAR(31) | NO | — | Scope at the time of the change |
| `scope_id` | UUID | YES | NULL | Scope entity ID |
| `old_value` | JSONB | YES | NULL | `{"v": ...}` before the change; NULL on create |
| `new_value` | JSONB | YES | NULL | `{"v": ...}` after the change; NULL on reset/delete |
| `action` | VARCHAR(15) | NO | `'set'` | One of: `set`, `reset`, `bulk_set` |
| `changed_by` | UUID | YES | NULL | FK → `users.id` ON DELETE SET NULL |
| `change_reason` | VARCHAR(255) | YES | NULL | Free-text reason or machine tag (`preset:physical_retail`, `rollback:<id>`) |
| `created_at` | TIMESTAMP(tz) | NO | `now()` | Append-only; never updated |

**Indexes:**

| Name | Columns | Purpose |
|---|---|---|
| `ix_tenant_settings_history_tenant_key` | `(tenant_id, key, created_at)` | History per key, time-ordered |
| `ix_tenant_settings_history_tenant_time` | `(tenant_id, created_at)` | All changes, time-ordered |

### 2.3 `setting_change_requests` — approval-gated changes

Holds proposed setting changes that require a second person's approval before reaching the
runtime. Only used for settings whose `apply_mode` is `approval_required`.

| Column | Type | Nullable | Default | Notes |
|---|---|---|---|---|
| `id` | UUID | NO | `gen_random_uuid()` | Primary key |
| `tenant_id` | UUID | NO | — | FK → `tenants.id` ON DELETE CASCADE; RLS-protected |
| `changes` | JSONB | NO | — | Proposed `{key: value}` pairs |
| `applied_changes` | JSONB | YES | NULL | What was actually written when applied |
| `status` | VARCHAR(31) | NO | `'draft'` | Lifecycle state (see below) |
| `scope` | VARCHAR(31) | NO | `'tenant'` | Target scope |
| `scope_id` | UUID | YES | NULL | Target scope entity |
| `submitted_by` | UUID | YES | NULL | FK → `users.id` ON DELETE SET NULL |
| `reviewed_by` | UUID | YES | NULL | FK → `users.id` ON DELETE SET NULL |
| `reason` | VARCHAR(255) | YES | NULL | Submitter's reason |
| `review_note` | VARCHAR(255) | YES | NULL | Reviewer's note |
| `reviewed_at` | TIMESTAMP(tz) | YES | NULL | When the review happened |
| `created_at` | TIMESTAMP(tz) | NO | `now()` | |
| `updated_at` | TIMESTAMP(tz) | NO | `now()` | |

**Lifecycle states:** `draft → submitted → validating → pending_approval → approved →
applying → applied`. Terminal alternatives: `rejected`, `cancelled`, `failed`, `expired`.

**Indexes:**

| Name | Columns | Purpose |
|---|---|---|
| `ix_setting_change_requests_tenant_status` | `(tenant_id, status)` | Filter by status |
| `ix_setting_change_requests_tenant_submitted` | `(tenant_id, submitted_by)` | Filter by submitter |

**Migration:** Created in `fe2026112501_setting_change_requests.py`.

---

## 3. Row-Level Security (RLS)

All three tables are tenant-isolated via PostgreSQL Row-Level Security.

### Policy

```sql
ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;
ALTER TABLE <table> FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON <table>
  USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
```

Applied to `tenant_settings`, `tenant_settings_history`, and `setting_change_requests`.

The `app.tenant_id` session setting is bound by `bind_tenant` on every request. The
`FORCE` keyword ensures the policy applies even to table owners. No query can read or write
another tenant's rows, even with a SQL injection.

### 3.1 Exception: `audit_logs` DELETE policy (append-only invariant)

`audit_logs` is **append-only by design** (migration `fd2026100409`): `INSERT` and
`SELECT` policies only, `UPDATE` revoked from `sales_app`. The
`security.audit_retention_days` setting introduces a tenant-scoped sweep that purges
old audit rows, which requires `DELETE`. To preserve the append-only invariant as
closely as possible:

- **`UPDATE` stays revoked.** Rows are never modified — only old ones are purged.
- **`DELETE` is gated by an RLS policy with a 1-day age guard** (migration
  `fe2026112503`):

  ```sql
  CREATE POLICY audit_logs_tenant_delete ON public.audit_logs
      FOR DELETE
      USING (
          tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
          AND created_at < now() - interval '1 day'
      );
  ```

  This is a **safety net** on top of the sweep's own retention-window check. Even a
  buggy sweep can never delete rows younger than 24 hours. The `USING` clause also
  enforces tenant isolation (same `app.tenant_id` check as every other policy).

- **The sweep is the only code path that deletes audit rows**, and it is gated by the
  tenant setting (`0` = no deletion). For tenants that leave the default (365 days) or
  set `0`, the append-only invariant holds completely.

This is the **only** exception to the append-only design of `audit_logs`.

---

## 4. Relationships

```
tenants (1) ─── (N) tenant_settings
tenants (1) ─── (N) tenant_settings_history
tenants (1) ─── (N) setting_change_requests

users (1) ─── (N) tenant_settings.updated_by
users (1) ─── (N) tenant_settings_history.changed_by
users (1) ─── (N) setting_change_requests.submitted_by
users (1) ─── (N) setting_change_requests.reviewed_by

tenant_settings (1) ─── (0..N) tenant_settings_history   [setting_id, ON DELETE SET NULL]
```

- `tenant_settings.key` is NOT a foreign key to a database table — it references the in-code
  registry (`REGISTRY` dict in `registry.py`). An unknown key raises `ValidationError` at the
  service layer before any SQL runs.
- `tenant_settings_history.setting_id` uses `ON DELETE SET NULL` so the audit row survives
  even after the override is deleted (a reset action).
- All user FKs use `ON DELETE SET NULL` so deleting a user doesn't erase the audit trail.

---

## 5. Scope Graph (resolution chain)

The resolver walks the inheritance chain from the requested scope up to the tenant. The chain
is read from the database (`scope_graph.py`), never trusted from the caller:

```
register → pos_profile → warehouse → branch → workspace → tenant → default
```

Additional scopes inherit directly from tenant:
- `channel` → resolves through the warehouse that serves it, then up
- `user` → inherits straight from tenant

The parent links come from existing operational table columns:

| Scope | Table | Parent column | Parent scope |
|---|---|---|---|
| `register` | `pos_registers` | `profile_id` | `pos_profile` |
| `pos_profile` | `pos_profiles` | `warehouse_id` | `warehouse` |
| `warehouse` | `warehouses` | `location_id` | `branch` |
| `branch` | `locations` | `workspace_id` | `workspace` |

A scope_id that does not exist for the tenant raises `UnknownScopeError` (a `NotFoundError`),
not an empty chain — a typo must not silently fall back to the tenant value.

---

## 6. HTTP API

All endpoints are mounted under the `/settings` prefix in `app/main.py`. Authentication and
tenant resolution are handled by `TenantContext` (from `identity.deps`).

### Permission model

| Permission | Access |
|---|---|
| `settings:read` | All GET endpoints |
| `settings:write` | Write endpoints (set, bulk, delete, presets, change requests, rollback) |
| `settings:branch_write` | Write a `branch_delegable` key below tenant scope (branch, warehouse, pos_profile, register) |

Write routes accept any of the three permissions at the door, then `SettingsService` +
`policy.authorize_write` decides per-key per-scope which the caller may actually write.

### 6.1 Metadata endpoints

#### `GET /settings/definitions`

Returns setting definitions (metadata), optionally filtered.

**Query parameters:**
- `domain` (optional): filter to one domain (e.g. `pos`)
- `segment` (optional): filter to one business segment (`retail`, `fnb`, `services`, `wholesale`)

**Response 200:** `list[SettingDefOut]`

```json
[
  {
    "key": "pos.max_discount_pct",
    "domain": "pos",
    "type": "number",
    "default": null,
    "scopes": ["tenant", "branch", "pos_profile"],
    "allowed_values": null,
    "min_value": 0,
    "max_value": 100,
    "max_length": null,
    "permission": "settings:write",
    "audit": true,
    "apply_mode": "validated",
    "sensitivity": "normal",
    "feature_requirement": null,
    "rollback_supported": true,
    "enforced": true,
    "segments": [],
    "label_ar": "الحد الأقصى للخصم %",
    "label_en": "Max Discount %",
    "description_ar": "...",
    "description_en": "..."
  }
]
```

**Errors:**
- `400 ValidationError` — unknown segment value

#### `GET /settings/domains`

**Response 200:** `list[str]` — domain names in registration order.

#### `GET /settings/capabilities`

Returns the shop's vertical and the final answer for every capability.

**Response 200:**
```json
{
  "vertical": "apparel",
  "capabilities": {
    "variant_matrix": true,
    "lot_expiry": false,
    "fefo_picking": false,
    "prescription_required": false,
    "modifiers": false,
    "recipe_bom": false,
    "serial_tracking": false,
    "weight_scale": false
  },
  "mandatory": []
}
```

### 6.2 Resolution endpoints

#### `GET /settings/effective`

Resolves effective settings with hierarchical inheritance.

**Query parameters:**
- `scope` (default `tenant`): resolution scope
- `scope_id` (optional, UUID): entity ID for non-tenant scopes
- `domain` (optional): resolve only one domain's keys
- `keys` (optional, comma-separated): resolve only specific keys

**Response 200:** `dict[str, ResolvedSettingOut]`

```json
{
  "pos.max_discount_pct": {
    "key": "pos.max_discount_pct",
    "value": 15.0,
    "scope": "tenant",
    "scope_id": null,
    "is_inherited": false,
    "is_default": false,
    "definition": { /* SettingDefOut */ }
  }
}
```

#### `GET /settings/effective/{key}`

Resolves a single setting key.

**Path:** `key` (dotted, e.g. `pos.max_discount_pct`)

**Response 200:** `ResolvedSettingOut`

**Errors:**
- `404 NotFoundError` — setting key not in registry

### 6.3 Override endpoints

#### `GET /settings/overrides`

Lists raw stored overrides for this tenant.

**Query parameters:**
- `scope` (optional): filter by scope
- `scope_id` (optional, UUID): filter by scope entity
- `domain` (optional): filter by domain prefix (e.g. `pos`)

**Response 200:** `list[TenantSettingOut]`

```json
[
  {
    "id": "uuid",
    "key": "pos.max_discount_pct",
    "scope": "tenant",
    "scope_id": null,
    "value": 15.0,
    "updated_by": "uuid"
  }
]
```

#### `PUT /settings/{key}`

Creates or updates a setting override at a specific scope. Supports optimistic concurrency
via `expected_history_id`.

**Path:** `key` (dotted setting key)

**Request body:** `SetSettingRequest`
```json
{
  "value": 15.0,
  "scope": "tenant",
  "scope_id": null,
  "reason": "owner requested",
  "expected_history_id": "uuid"
}
```

**Response 200:** `TenantSettingOut`

**Errors:**
- `404 NotFoundError` — key not in registry
- `400 ValidationError` — value fails validation (wrong type, out of bounds, unknown scope)
- `403 PermissionDeniedError` — caller lacks the key's required permission at the requested scope
- `409 ConflictError` — optimistic concurrency check failed (another write landed first)

#### `POST /settings/bulk`

Sets multiple overrides at once at a specific scope. All-or-nothing: every key is validated
before any write.

**Request body:** `BulkSetSettingsRequest`
```json
{
  "settings": {
    "pos.max_discount_pct": 15.0,
    "pos.return_max_days": 14
  },
  "scope": "tenant",
  "scope_id": null,
  "reason": "applying preset"
}
```

**Response 200:** `list[TenantSettingOut]`

#### `DELETE /settings/{key}`

Reverts an override to its inherited value (deletes the override row).

**Path:** `key`

**Request body:** `ResetSettingRequest`
```json
{
  "scope": "tenant",
  "scope_id": null,
  "reason": "reverting to default"
}
```

**Response 200:**
```json
{"deleted": true}
```

### 6.4 Preset endpoints

#### `GET /settings/presets`

**Response 200:** `dict[str, dict[str, object]]` — preset name → key/value map.

#### `POST /settings/presets/{preset_name}`

Applies a business-type preset at tenant scope. Requires `settings:write`.

**Path:** `preset_name` (one of: `physical_retail`, `ecommerce`, `omnichannel`, `enterprise`,
`apparel_ground_shop`)

**Response 200:**
```json
{
  "preset": "physical_retail",
  "applied_count": 12
}
```

**Errors:**
- `404 NotFoundError` — preset not found
- `403 PermissionDeniedError` — caller lacks `settings:write`

### 6.5 History & audit endpoints

#### `GET /settings/history`

Returns the audit log of settings changes, newest first.

**Query parameters:**
- `key` (optional): filter by setting key
- `limit` (1–200, default 50)

**Response 200:** `list[SettingHistoryOut]`

```json
[
  {
    "id": "uuid",
    "setting_id": "uuid",
    "key": "pos.max_discount_pct",
    "scope": "tenant",
    "scope_id": null,
    "old_value": 10.0,
    "new_value": 15.0,
    "action": "set",
    "changed_by": "uuid",
    "change_reason": "owner requested",
    "created_at": "2026-11-25T10:00:00+00:00"
  }
]
```

### 6.6 Change request endpoints

#### `POST /settings/change-requests`

Creates a change request for approval-gated settings.

**Request body:** `CreateChangeRequestInput`
```json
{
  "changes": {"key": "value"},
  "scope": "tenant",
  "scope_id": null,
  "reason": "..."
}
```

**Response 200:** `ChangeRequestOut`

**Lifecycle:** For `immediate` settings, no request is created (use `PUT` directly). For
`validated` settings, the request is created and immediately applied. For
`approval_required` settings, the request stays in `pending_approval` until approved.

#### `GET /settings/change-requests`

**Query parameters:**
- `status` (optional): filter by lifecycle state

**Response 200:** `list[ChangeRequestOut]`

#### `POST /settings/change-requests/{request_id}/approve`

Approves and applies a pending change request. Requires `settings:write`.

**Request body:** `ReviewChangeRequestInput`
```json
{"review_note": "approved"}
```

**Response 200:** `ChangeRequestOut`

**Errors:**
- `400 ValidationError` — request not found or not in `pending_approval` state
- `403 PermissionDeniedError` — lacks `settings:write`

#### `POST /settings/change-requests/{request_id}/reject`

Rejects a pending change request. Requires `settings:write`.

### 6.7 Rollback endpoint

#### `POST /settings/rollback`

Rolls back a setting to a previous revision's value. Creates a NEW revision with the
restored value — does not delete history. Requires `settings:write`.

**Request body:** `RollbackInput`
```json
{
  "history_id": "uuid",
  "reason": "reverting misconfiguration"
}
```

**Response 200:** `TenantSettingOut | {"deleted": true, "message": "..."}`

The `deleted` response is returned when the target revision was a reset (the override is
deleted, reverting to inherited).

**Errors:**
- `400 ValidationError` — history revision not found, or setting does not support rollback

---

## 7. Error Response Shapes

All errors use the application's standard error envelope (`app/modules/errors`):

| HTTP Status | Error class | When |
|---|---|---|
| 400 | `ValidationError` | Bad input: unknown key, bad value, unknown scope, invalid segment, change request not in expected state |
| 403 | `PermissionDeniedError` | Caller lacks the required permission for this key at this scope |
| 404 | `NotFoundError` | Setting key or preset not found in the registry |
| 409 | `ConflictError` | Optimistic concurrency check failed (`expected_history_id` mismatch) |

---

## 8. Write Authorization (`policy.py`)

The per-key, per-scope authorization logic, called by `SettingsService` on every write:

1. **`user` scope:** a user may always write their own setting (`scope_id == user_id`); only an
   owner-grade writer may set another person's preference.
2. **Definition permission** (default `settings:write`): a holder may write the key at every
   scope the key allows.
3. **`settings:branch_write`**: a holder may write a key only when `branch_delegable=True` AND
   the scope is below tenant (branch, warehouse, pos_profile, register, channel). Never at
   tenant level.
4. Anything else is denied with `PermissionDeniedError`.

---

## 9. Event-Driven Sync

Every setting write (set, reset, bulk_set) stages a `settings.changed` event in the
transactional outbox, in the same transaction as the write. Runtime systems (POS, inventory,
agents) consume the event and invalidate their cached config.

**Event payload:**
```json
{
  "key": "pos.max_discount_pct",
  "scope": "tenant",
  "scope_id": null,
  "revision": "<history_row_id>",
  "action": "set",
  "changed_by": "<user_id>"
}
```

The `revision` (history row id) is the stable identifier consumers use for idempotency.

---

## 10. Optimistic Concurrency

`PUT /settings/{key}` accepts an optional `expected_history_id`. When provided, the service
checks that no newer write has landed since the caller last read. If another write intervened,
the server returns `409 ConflictError` instead of silently overwriting the newer value.

---

## 11. Cross-Module Read Paths

Two patterns for reading settings, chosen to avoid circular imports:

1. **`SettingsService(session, tenant_id).value(key)`** — the standard pattern used by POS,
   orders, purchasing, inventory, AI hooks, catalog, e-invoice.

2. **Direct SQL read** (`app.core.settings_read.resolve_settings`) — used in modules where
   importing `SettingsService` would create a cycle (identity → settings, billing → settings).
   Reads `tenant_settings` directly without importing the settings service.
