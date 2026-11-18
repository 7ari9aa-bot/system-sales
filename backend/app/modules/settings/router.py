"""Settings routes — API endpoints for the FIHRIST Configuration Engine.

Provides CRUD, resolution, domain grouping, preset application, and audit history.
Gated by settings:read and settings:write permissions.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.modules.errors import NotFoundError
from app.modules.identity.deps import TenantContext, require_permission
from app.modules.settings.presets import PRESETS
from app.modules.settings.registry import (
    Scope,
    SettingDef,
    get_definition,
    list_definitions,
)
from app.modules.settings.registry import (
    domains as get_registry_domains,
)
from app.modules.settings.schemas import (
    BulkSetSettingsRequest,
    ResetSettingRequest,
    ResolvedSettingOut,
    SetSettingRequest,
    SettingDefOut,
    SettingHistoryOut,
    TenantSettingOut,
)
from app.modules.settings.service import ResolvedSetting, SettingsService

router = APIRouter(prefix="/settings", tags=["settings"])

SettingsReadCtx = Annotated[TenantContext, Depends(require_permission("settings:read"))]
SettingsWriteCtx = Annotated[TenantContext, Depends(require_permission("settings:write"))]


def _def_to_out(d: SettingDef) -> SettingDefOut:
    return SettingDefOut(
        key=d.key,
        domain=d.domain,
        type=d.type.value,
        default=d.default,
        scopes=[s.value for s in d.scopes],
        allowed_values=list(d.allowed_values) if d.allowed_values else None,
        min_value=d.min_value,
        max_value=d.max_value,
        max_length=d.max_length,
        permission=d.permission,
        audit=d.audit,
        label_ar=d.label_ar,
        label_en=d.label_en,
        description_ar=d.description_ar,
        description_en=d.description_en,
    )


def _resolved_to_out(r: ResolvedSetting) -> ResolvedSettingOut:
    return ResolvedSettingOut(
        key=r.key,
        value=r.value,
        scope=r.scope,
        scope_id=r.scope_id,
        is_inherited=r.is_inherited,
        is_default=r.is_default,
        definition=_def_to_out(r.definition),
    )


# ---------------------------------------------------------------------------
# Metadata & Definitions
# ---------------------------------------------------------------------------


@router.get("/definitions", response_model=list[SettingDefOut])
async def list_setting_definitions(
    ctx: SettingsReadCtx,
    domain: str | None = None,
) -> list[SettingDefOut]:
    """List setting metadata from the registry, optionally filtered by domain."""
    defs = list_definitions(domain=domain)
    return [_def_to_out(d) for d in defs]


@router.get("/domains", response_model=list[str])
async def list_setting_domains(ctx: SettingsReadCtx) -> list[str]:
    """Return all known setting domain names."""
    return get_registry_domains()


# ---------------------------------------------------------------------------
# Resolution (Effective Values)
# ---------------------------------------------------------------------------


@router.get("/effective", response_model=dict[str, ResolvedSettingOut])
async def resolve_effective_settings(
    ctx: SettingsReadCtx,
    scope: str = Query(default="tenant"),
    scope_id: uuid.UUID | None = Query(default=None),
    domain: str | None = Query(default=None),
    keys: str | None = Query(default=None),
) -> dict[str, ResolvedSettingOut]:
    """Resolve effective settings at the given scope with inheritance."""
    svc = SettingsService(ctx.session, ctx.tenant_id)
    scope_enum = Scope(scope)

    if keys:
        key_list = [k.strip() for k in keys.split(",") if k.strip()]
        resolved = await svc.resolve_many(key_list, scope=scope_enum, scope_id=scope_id)
    elif domain:
        resolved = await svc.resolve_domain(domain, scope=scope_enum, scope_id=scope_id)
    else:
        all_defs = list_definitions()
        all_keys = [d.key for d in all_defs]
        resolved = await svc.resolve_many(all_keys, scope=scope_enum, scope_id=scope_id)

    return {k: _resolved_to_out(v) for k, v in resolved.items()}


@router.get("/effective/{key:path}", response_model=ResolvedSettingOut)
async def resolve_effective_setting(
    key: str,
    ctx: SettingsReadCtx,
    scope: str = Query(default="tenant"),
    scope_id: uuid.UUID | None = Query(default=None),
) -> ResolvedSettingOut:
    """Resolve a single setting to its effective value."""
    try:
        get_definition(key)
    except KeyError:
        raise NotFoundError(f"setting {key!r} not found in registry") from None

    svc = SettingsService(ctx.session, ctx.tenant_id)
    resolved = await svc.resolve(key, scope=Scope(scope), scope_id=scope_id)
    return _resolved_to_out(resolved)


# ---------------------------------------------------------------------------
# Overrides (Raw Stored Values)
# ---------------------------------------------------------------------------


@router.get("/overrides", response_model=list[TenantSettingOut])
async def list_overrides(
    ctx: SettingsReadCtx,
    scope: str | None = Query(default=None),
    scope_id: uuid.UUID | None = Query(default=None),
    domain: str | None = Query(default=None),
) -> list[TenantSettingOut]:
    """List explicitly configured overrides for this tenant."""
    svc = SettingsService(ctx.session, ctx.tenant_id)
    scope_enum = Scope(scope) if scope else None
    rows = await svc.list_overrides(scope=scope_enum, scope_id=scope_id, domain=domain)
    return [
        TenantSettingOut(
            id=r.id,
            key=r.key,
            scope=r.scope,
            scope_id=r.scope_id,
            value=r.value.get("v") if isinstance(r.value, dict) else r.value,
            updated_by=r.updated_by,
        )
        for r in rows
    ]


@router.put("/{key:path}", response_model=TenantSettingOut)
async def set_setting(
    key: str,
    body: SetSettingRequest,
    ctx: SettingsWriteCtx,
) -> TenantSettingOut:
    """Create or update a setting override at a specific scope."""
    try:
        get_definition(key)
    except KeyError:
        raise NotFoundError(f"setting {key!r} not found in registry") from None

    svc = SettingsService(ctx.session, ctx.tenant_id)
    row = await svc.set(
        key,
        body.value,
        scope=Scope(body.scope),
        scope_id=body.scope_id,
        user_id=ctx.user.id,
        reason=body.reason,
    )
    return TenantSettingOut(
        id=row.id,
        key=row.key,
        scope=row.scope,
        scope_id=row.scope_id,
        value=row.value.get("v"),
        updated_by=row.updated_by,
    )


@router.post("/bulk", response_model=list[TenantSettingOut])
async def bulk_set_settings(
    body: BulkSetSettingsRequest,
    ctx: SettingsWriteCtx,
) -> list[TenantSettingOut]:
    """Set multiple setting overrides at once at a specific scope."""
    svc = SettingsService(ctx.session, ctx.tenant_id)
    rows = await svc.bulk_set(
        body.settings,
        scope=Scope(body.scope),
        scope_id=body.scope_id,
        user_id=ctx.user.id,
        reason=body.reason,
    )
    return [
        TenantSettingOut(
            id=r.id,
            key=r.key,
            scope=r.scope,
            scope_id=r.scope_id,
            value=r.value.get("v"),
            updated_by=r.updated_by,
        )
        for r in rows
    ]


@router.delete("/{key:path}")
async def reset_setting(
    key: str,
    body: ResetSettingRequest,
    ctx: SettingsWriteCtx,
) -> dict[str, bool]:
    """Revert a setting at the given scope to its inherited value."""
    try:
        get_definition(key)
    except KeyError:
        raise NotFoundError(f"setting {key!r} not found in registry") from None

    svc = SettingsService(ctx.session, ctx.tenant_id)
    deleted = await svc.reset(
        key,
        scope=Scope(body.scope),
        scope_id=body.scope_id,
        user_id=ctx.user.id,
        reason=body.reason,
    )
    return {"deleted": deleted}


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------


@router.get("/presets")
async def list_presets(ctx: SettingsReadCtx) -> dict[str, dict[str, object]]:
    """List available business configuration presets and their default keys."""
    return PRESETS


@router.post("/presets/{preset_name}")
async def apply_preset(
    preset_name: str,
    ctx: SettingsWriteCtx,
) -> dict[str, object]:
    """Apply a business-type preset to the tenant scope."""
    if preset_name not in PRESETS:
        raise NotFoundError(f"preset {preset_name!r} not found")

    svc = SettingsService(ctx.session, ctx.tenant_id)
    applied = await svc.apply_preset(preset_name, user_id=ctx.user.id)
    return {
        "preset": preset_name,
        "applied_count": len(applied),
    }


# ---------------------------------------------------------------------------
# Change History & Audit
# ---------------------------------------------------------------------------


@router.get("/history", response_model=list[SettingHistoryOut])
async def get_settings_history(
    ctx: SettingsReadCtx,
    key: str | None = Query(default=None),
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[SettingHistoryOut]:
    """Return the audit log of settings changes, newest first."""
    svc = SettingsService(ctx.session, ctx.tenant_id)
    rows = await svc.history(key=key, limit=limit)
    return [
        SettingHistoryOut(
            id=r.id,
            setting_id=r.setting_id,
            key=r.key,
            scope=r.scope,
            scope_id=r.scope_id,
            old_value=r.old_value.get("v") if isinstance(r.old_value, dict) else r.old_value,
            new_value=r.new_value.get("v") if isinstance(r.new_value, dict) else r.new_value,
            action=r.action,
            changed_by=r.changed_by,
            change_reason=r.change_reason,
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        for r in rows
    ]
