# Settings Domain Specification

> Source of truth: `backend/app/modules/settings/` (code is the contract; this document describes it).

## 1. Overview

The Settings domain is a **hierarchical configuration system** that lets each
tenant override factory defaults at progressively narrower scopes. Every
setting the platform knows about is defined once in the **registry** (code,
not the database). The database stores **overrides** only — the absence of a
row means "inherit from the parent scope."

### Design principles

1. **Postgres is the only source of truth.** The registry defines what exists;
   the `tenant_settings` table stores what a tenant changed. Redis and the
   frontend never own business facts.
2. **Every change goes through a service.** `SettingsService` owns all writes;
   routers parse and authorise, never writing rows directly.
3. **Events go through the outbox** in the same transaction as the change.
4. **Tenant isolation** is enforced by RLS (`app.tenant_id` GUC, bound by
   `bind_tenant`).
5. **Services never commit.** The caller owns the transaction; `SettingsService`
   only `flush()`.

## 2. Scope hierarchy

Settings resolve through an inheritance chain. A value at a narrower scope
shadows the same key at a broader scope; the resolver walks up the chain until
it finds an override or falls back to the registry default.

```
TENANT (root)
  ├── WORKSPACE
  │     ├── BRANCH
  │     │     ├── WAREHOUSE
  │     │     │     ├── POS_PROFILE
  │     │     │     │     └── REGISTER
  │     │     └── ...
  │     └── ...
  ├── CHANNEL  (inherits directly from TENANT)
  └── USER     (inherits directly from TENANT)
```

Each `SettingDef` declares which scopes **may** override it. A scope not in
the list is silently ignored by the resolver.

## 3. Setting types

| Type | Python | JSON | Validation |
|---|---|---|---|
| `bool` | `bool` | `true/false` | Accepts any JSON boolean |
| `number` | `int/float/Decimal` | number | `min_value` / `max_value` bounds |
| `string` | `str` | string | Non-empty unless default is `""` |
| `enum` | `str` | string | Must be in `allowed_values` |
| `list` | `list[str]` | array of strings | Each item validated |

## 4. Sensitivity classifications

| Level | Meaning | UI behaviour |
|---|---|---|
| `NORMAL` | Visible and editable through the standard settings UI | Shown in full |
| `SENSITIVE` | Access is restricted; value is masked in some views | Masked unless the user has elevated permission |
| `SECRET` | Stored in the secrets store, never in the settings table | UI shows connection status only, never the value |

## 5. Apply modes

| Mode | When | Example |
|---|---|---|
| `IMMEDIATE` | Applied right after validation | UI prefs, display, inventory policies |
| `VALIDATED` | Domain validation required before acceptance | POS rules, return windows |
| `APPROVAL_REQUIRED` | A second person must approve | Sensitive cross-branch policies, high-risk financial caps |

## 6. Storage

| Table | Purpose | Writes |
|---|---|---|
| `tenant_settings` | Active overrides per (tenant, key, scope, scope_id) | `SettingsService.set` / `bulk_set` |
| `tenant_settings_history` | Append-only audit trail (who, what, before/after, when) | Triggered by every write |
| `setting_change_requests` | Pending approval flows for `APPROVAL_REQUIRED` settings | `SettingsService.request_change` |

All three tables are tenant-scoped (`TenantMixin`) with RLS.

## 7. Business segments

A setting can be restricted to specific business types (`retail`, `fnb`,
`services`, `wholesale`). A setting with `segments=()` (empty tuple) applies to
all segments. The `capabilities` module maps the tenant's vertical to the set
of segments it operates in, and the settings UI only shows keys whose segments
intersect the tenant's capabilities.

## 8. Read paths

### Primary: `SettingsService.resolve` / `resolve_all`
The canonical resolver. Walks the scope chain, loads overrides from
`tenant_settings`, and returns the effective value with metadata (`is_default`,
`is_inherited`, `source_scope`).

### Cross-module: `app.core.settings_read`
A read-only resolver in `app.core` (not `app.modules.settings`) for modules
that sit on the far side of the import cycle (identity, deps). It provides the
same inheritance walk and type coercion but imports only `registry` and
`scope_graph` — neither of which imports `identity` — so it does not grow the
cyclic SCC.

### Direct SQL
Some high-coupling modules read settings with parameter-bound SQL against
`tenant_settings` to avoid importing `settings.service` at all (e.g.
`identity/services/hierarchy.py` reads organization settings this way).

## 9. Write paths

All writes go through `SettingsService`:

| Method | Purpose |
|---|---|
| `set(tenant_id, key, value, scope, scope_id)` | Set one override |
| `bulk_set(tenant_id, settings, scope, scope_id)` | Set several overrides in one transaction |
| `reset(tenant_id, key, scope, scope_id)` | Remove an override (fall back to parent/default) |
| `request_change(...)` | Create a `SettingChangeRequest` for `APPROVAL_REQUIRED` keys |

Every write:
1. Validates the value against the `SettingDef` (type, bounds, allowed_values).
2. Checks the user's permissions (`authorize_write` in `policy.py`).
3. Writes the override to `tenant_settings`.
4. Appends a row to `tenant_settings_history`.
5. Emits a `setting.changed` event through the outbox (same transaction).

## 10. Change management

Settings with `apply_mode=APPROVAL_REQUIRED` cannot be applied directly.
Instead:

1. The requester calls `request_change`, which creates a row in
   `setting_change_requests` with status `pending`.
2. A second authorised user reviews and approves/rejects.
3. On approval, the override is written to `tenant_settings` and the request
   is marked `approved` with `reviewed_at` / `reviewed_by`.

## 11. Capabilities and vertical

The tenant's `business.vertical` setting drives the **capabilities** system
(`settings/capabilities.py`): each vertical enables a set of business segments,
and each segment gates which settings the UI shows. Changing the vertical is a
domain-level decision that re-evaluates the entire settings surface.

`business.type` is derived from the vertical via `core/shop_type.py`.

## 12. Event types

| Event | Emitted on | Payload |
|---|---|---|
| `setting.changed` | Any successful write to `tenant_settings` | `key`, `scope`, `scope_id`, `old_value`, `new_value`, `changed_by` |
| `setting.change_requested` | A change request is created | `key`, `request_id`, `requested_by` |
| `setting.change_approved` | A change request is approved | `key`, `request_id`, `reviewed_by` |
| `setting.change_rejected` | A change request is rejected | `key`, `request_id`, `reviewed_by` |

All events go through the outbox in the same transaction as the write.
