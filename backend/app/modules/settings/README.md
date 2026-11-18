# settings

SETTINGS domain — FIHRIST Configuration Engine (Retail Operations Configuration v1).

## Where things are

- `models.py`: Database models (`tenant_settings`, `tenant_settings_history`)
- `registry.py`: Settings Registry and definitions (`SettingDef`, types, scopes, validation)
- `service.py`: Hierarchical resolver and CRUD (`SettingsService`)
- `presets.py`: Out-of-the-box configuration presets (`physical_retail`, `ecommerce`, `omnichannel`, `enterprise`)
- `schemas.py`: Pydantic input/output schemas
- `router.py`: REST endpoints mounted under `/settings`

## HTTP

Endpoints registered in `app/main.py`:
- `GET /settings/definitions`: Lists setting definitions and metadata (`?domain=`, `?segment=retail|fnb|services|wholesale`)
- `GET /settings/domains`: Lists registered domains
- `GET /settings/effective`: Resolves effective settings with hierarchical inheritance
- `GET /settings/effective/{key}`: Resolves single setting key
- `GET /settings/overrides`: Lists raw tenant overrides
- `PUT /settings/{key}`: Sets a scoped override
- `POST /settings/bulk`: Sets multiple overrides at once
- `DELETE /settings/{key}`: Reverts an override to inherited value
- `GET /settings/presets`: Lists presets
- `POST /settings/presets/{preset_name}`: Applies a preset at tenant scope
- `GET /settings/history`: Audit log of configuration changes

## Tables

- `tenant_settings` (overrides table with full tenant isolation RLS)
- `tenant_settings_history` (append-only change audit log with RLS)

## Depends on

- Core: `app.core.db`, `app.core.model_kit`
- Auth: `app.modules.identity.deps` (TenantContext, require_permission)

## Rules for working here

- Every new setting must be defined in `registry.py` with its type, default, and allowed scopes.
- Decide a new setting's `segments` on purpose: `()` (the default) means every kind of business sees
  it; name segments only when the key is meaningless to the others (shelf stock for a services
  shop). Segments only change what the settings screen lists, never what a key resolves to, so the
  code that reads it never branches on the segment.
- Database stores overrides only; defaults stay in code.
- Scoped inheritance walks: `register -> pos_profile -> warehouse -> branch -> tenant -> default`.
- All writes are audited in `tenant_settings_history`.
- Services `flush()` and never `commit()`.
