"""Settings routes — API endpoints for the FIHRIST Configuration Engine.

Provides CRUD, resolution, domain grouping, preset application, SLO status,
and audit history. Gated by settings:read and settings:write permissions.
"""

from __future__ import annotations

import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.core.audit import write_audit_row
from app.modules.errors import NotFoundError, PermissionDeniedError, ValidationError
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission
from app.modules.settings.capabilities import shop_capabilities
from app.modules.settings.presets import PRESET_DEFS, PRESETS, preset_chain, resolve_preset
from app.modules.settings.registry import (
    SEGMENTS,
    Scope,
    Sensitivity,
    SettingDef,
    get_definition,
    list_definitions,
)
from app.modules.settings.registry import (
    domains as get_registry_domains,
)
from app.modules.settings.schemas import (
    BulkSetSettingsRequest,
    ChangeRequestOut,
    CreateChangeRequestInput,
    MigrationLogOut,
    ResetSettingRequest,
    ResolvedSettingOut,
    RestoreSnapshotInput,
    ReviewChangeRequestInput,
    RollbackInput,
    RunMigrationsOut,
    SetSettingRequest,
    SettingDefOut,
    SettingHistoryOut,
    SettingsPreviewOut,
    TenantSettingOut,
)
from app.modules.settings.service import ResolvedSetting, SettingsService

router = APIRouter(prefix="/settings", tags=["settings"])

SettingsReadCtx = Annotated[TenantContext, Depends(require_permission("settings:read"))]

MASKED_VALUE = "******"


def _can_read_sensitive(ctx: TenantContext) -> bool:
    """Whether the caller may see the *value* of SENSITIVE settings."""
    return "settings:read_sensitive" in ctx.permission_codes


def _mask_if_sensitive(defn: SettingDef, value: object, can_read_sensitive: bool) -> object:
    """Mask the value of a SENSITIVE setting when the caller lacks read_sensitive."""
    if defn.sensitivity is Sensitivity.SENSITIVE and not can_read_sensitive:
        return MASKED_VALUE
    return value


class _AnySettingsPermission:
    """Door for the write routes: any settings permission gets in.

    The door is deliberately wide. WHICH key may be written at WHICH scope by WHOM is decided
    per setting by ``SettingsService`` (``policy.authorize_write``), so a manager holding only
    ``settings:branch_write`` reaches a branch-level write and is refused a tenant-level one,
    and a cashier can still save their own preference. Gating on ``settings:write`` alone would
    lock the manager out before the per-key rule ever ran.
    """

    _CODES = ("settings:write", "settings:branch_write", "settings:read")

    async def __call__(self, ctx: TenantCtxDep) -> TenantContext:
        if not any(code in ctx.permission_codes for code in self._CODES):
            raise PermissionDeniedError("missing permission: settings:read")
        return ctx


SettingsWriteCtx = Annotated[TenantContext, Depends(_AnySettingsPermission())]


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
        apply_mode=d.apply_mode.value,
        sensitivity=d.sensitivity.value,
        feature_requirement=d.feature_requirement,
        rollback_supported=d.rollback_supported,
        enforced=d.enforced,
        segments=list(d.segments),
        label_ar=d.label_ar,
        label_en=d.label_en,
        description_ar=d.description_ar,
        description_en=d.description_en,
    )


def _resolved_to_out(r: ResolvedSetting, *, can_read_sensitive: bool = True) -> ResolvedSettingOut:
    return ResolvedSettingOut(
        key=r.key,
        value=_mask_if_sensitive(r.definition, r.value, can_read_sensitive),
        scope=r.scope,
        scope_id=r.scope_id,
        is_inherited=r.is_inherited,
        is_default=r.is_default,
        latest_history_id=r.latest_history_id,
        definition=_def_to_out(r.definition),
    )


# ---------------------------------------------------------------------------
# Metadata & Definitions
# ---------------------------------------------------------------------------


@router.get("/definitions", response_model=list[SettingDefOut])
async def list_setting_definitions(
    ctx: SettingsReadCtx,
    domain: str | None = None,
    segment: str | None = None,
) -> list[SettingDefOut]:
    """List setting metadata, optionally for one domain and/or one business segment."""
    if segment is not None and segment not in SEGMENTS:
        raise ValidationError(f"unknown segment {segment!r}; expected one of {list(SEGMENTS)}")
    defs = list_definitions(domain=domain, segment=segment)
    return [_def_to_out(d) for d in defs]


@router.get("/domains", response_model=list[str])
async def list_setting_domains(ctx: SettingsReadCtx) -> list[str]:
    """Return all known setting domain names."""
    return get_registry_domains()


# ---------------------------------------------------------------------------
# Resolution (Effective Values)
# ---------------------------------------------------------------------------


@router.get("/capabilities")
async def get_shop_capabilities(ctx: SettingsReadCtx) -> dict[str, object]:
    """The shop's vertical and what it can do, as its owner has set them (final answers)."""
    return await shop_capabilities(ctx.session, ctx.tenant_id)


@router.get("/effective", response_model=dict[str, ResolvedSettingOut])
async def resolve_effective_settings(
    ctx: SettingsReadCtx,
    scope: Annotated[str, Query()] = "tenant",
    scope_id: Annotated[uuid.UUID | None, Query()] = None,
    domain: Annotated[str | None, Query()] = None,
    keys: Annotated[str | None, Query()] = None,
) -> dict[str, ResolvedSettingOut]:
    """Resolve effective settings at the given scope with inheritance."""
    from app.modules.settings.slo import record_settings_resolve

    t0 = time.monotonic()
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

    await record_settings_resolve(duration_seconds=time.monotonic() - t0)
    can_read = _can_read_sensitive(ctx)
    return {k: _resolved_to_out(v, can_read_sensitive=can_read) for k, v in resolved.items()}


@router.get("/effective/{key:path}", response_model=ResolvedSettingOut)
async def resolve_effective_setting(
    key: str,
    ctx: SettingsReadCtx,
    scope: Annotated[str, Query()] = "tenant",
    scope_id: Annotated[uuid.UUID | None, Query()] = None,
) -> ResolvedSettingOut:
    """Resolve a single setting to its effective value."""
    try:
        get_definition(key)
    except KeyError:
        raise NotFoundError(f"setting {key!r} not found in registry") from None

    svc = SettingsService(ctx.session, ctx.tenant_id)
    resolved = await svc.resolve(key, scope=Scope(scope), scope_id=scope_id)
    return _resolved_to_out(resolved, can_read_sensitive=_can_read_sensitive(ctx))


# ---------------------------------------------------------------------------
# Overrides (Raw Stored Values)
# ---------------------------------------------------------------------------


@router.get("/overrides", response_model=list[TenantSettingOut])
async def list_overrides(
    ctx: SettingsReadCtx,
    scope: Annotated[str | None, Query()] = None,
    scope_id: Annotated[uuid.UUID | None, Query()] = None,
    domain: Annotated[str | None, Query()] = None,
) -> list[TenantSettingOut]:
    """List explicitly configured overrides for this tenant."""
    svc = SettingsService(ctx.session, ctx.tenant_id)
    scope_enum = Scope(scope) if scope else None
    rows = await svc.list_overrides(scope=scope_enum, scope_id=scope_id, domain=domain)
    can_read = _can_read_sensitive(ctx)
    out = []
    for r in rows:
        raw = r.value.get("v") if isinstance(r.value, dict) else r.value
        try:
            defn = get_definition(r.key)
            out_val = _mask_if_sensitive(defn, raw, can_read)
        except KeyError:
            out_val = raw
        out.append(
            TenantSettingOut(
                id=r.id,
                key=r.key,
                scope=r.scope,
                scope_id=r.scope_id,
                value=out_val,
                updated_by=r.updated_by,
            )
        )
    return out


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
        permissions=ctx.permission_codes,
        expected_history_id=body.expected_history_id,
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
        permissions=ctx.permission_codes,
        expected_history_ids=body.expected_history_ids,
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


@router.post("/preview", response_model=SettingsPreviewOut)
async def preview_settings(
    body: BulkSetSettingsRequest,
    ctx: SettingsWriteCtx,
) -> SettingsPreviewOut:
    """Dry run of a save: every key checked, nothing written.

    The settings screen shows this diff before the owner commits, so a key that is invalid,
    forbidden at this scope, or needs approval is visible BEFORE the request is sent — not
    as a 400/403 after half the form was filled in.
    """
    svc = SettingsService(ctx.session, ctx.tenant_id)
    result = await svc.preview(
        body.settings,
        scope=Scope(body.scope),
        scope_id=body.scope_id,
        user_id=ctx.user.id,
        permissions=ctx.permission_codes,
    )
    return SettingsPreviewOut(**result)


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
        permissions=ctx.permission_codes,
    )
    return {"deleted": deleted}


# ---------------------------------------------------------------------------
# Presets
# ---------------------------------------------------------------------------


@router.get("/presets")
async def list_presets(ctx: SettingsReadCtx) -> dict[str, dict[str, object]]:
    """List available business configuration presets with composition metadata."""
    out: dict[str, dict[str, object]] = {}
    for name, defn in PRESET_DEFS.items():
        out[name] = {
            "values": resolve_preset(name),
            "extends": defn.extends,
            "chain": preset_chain(name),
            "label_ar": defn.label_ar,
            "label_en": defn.label_en,
            "description_ar": defn.description_ar,
            "description_en": defn.description_en,
        }
    return out


@router.post("/presets/{preset_name}/preview")
async def preview_preset(
    preset_name: str,
    ctx: SettingsReadCtx,
) -> dict[str, object]:
    """Dry-run: show what would change if the preset were applied, without writing."""
    if preset_name not in PRESETS:
        raise NotFoundError(f"preset {preset_name!r} not found")
    svc = SettingsService(ctx.session, ctx.tenant_id)
    return await svc.preview_preset(preset_name)


@router.post("/presets/{preset_name}")
async def apply_preset(
    preset_name: str,
    ctx: SettingsWriteCtx,
) -> dict[str, object]:
    """Apply a business-type preset to the tenant scope (atomic, with audit)."""
    if preset_name not in PRESETS:
        raise NotFoundError(f"preset {preset_name!r} not found")
    if "settings:write" not in ctx.permission_codes:
        raise PermissionDeniedError("applying a preset requires settings:write")

    svc = SettingsService(ctx.session, ctx.tenant_id)
    result = await svc.apply_preset(
        preset_name, user_id=ctx.user.id, permissions=ctx.permission_codes
    )
    return {
        "preset": preset_name,
        "applied_count": len(result["applied"]),
        "pending_approval": result["pending_approval"],
    }


# ---------------------------------------------------------------------------
# SLO Status (§168)
# ---------------------------------------------------------------------------


@router.get("/slo")
async def get_settings_slo(ctx: SettingsReadCtx) -> dict[str, object]:
    """Return the current SLO status for the settings control plane.

    Admin-only: requires ``settings:read``. Reads the live metrics counters
    and outbox gauges, and returns the compliance verdict for each SLO.
    """
    from app.modules.settings.slo import get_slo_status

    return await get_slo_status()


# ---------------------------------------------------------------------------
# Change History & Audit
# ---------------------------------------------------------------------------


@router.get("/history", response_model=list[SettingHistoryOut])
async def get_settings_history(
    ctx: SettingsReadCtx,
    key: Annotated[str | None, Query()] = None,
    source: Annotated[str | None, Query()] = None,
    action: Annotated[str | None, Query()] = None,
    changed_by: Annotated[uuid.UUID | None, Query()] = None,
    since: Annotated[str | None, Query()] = None,
    until: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[SettingHistoryOut]:
    """Return the audit log of settings changes, newest first, with filters (§174).

    Filter by ``key``, ``source`` (api/preset/restore/migration/rollback/change_request),
    ``action`` (set/reset), ``changed_by`` (user id), and/or a time range
    (``since`` / ``until`` as ISO 8601 timestamps).
    """
    from datetime import UTC
    from datetime import datetime as dt

    since_dt = None
    if since:
        try:
            since_dt = dt.fromisoformat(since)
            if since_dt.tzinfo is None:
                since_dt = since_dt.replace(tzinfo=UTC)
        except ValueError:
            raise ValidationError(f"invalid 'since' timestamp: {since!r}") from None

    until_dt = None
    if until:
        try:
            until_dt = dt.fromisoformat(until)
            if until_dt.tzinfo is None:
                until_dt = until_dt.replace(tzinfo=UTC)
        except ValueError:
            raise ValidationError(f"invalid 'until' timestamp: {until!r}") from None

    svc = SettingsService(ctx.session, ctx.tenant_id)
    rows = await svc.history(
        key=key,
        source=source,
        action=action,
        changed_by=changed_by,
        since=since_dt,
        until=until_dt,
        limit=limit,
    )
    can_read = _can_read_sensitive(ctx)
    out = []
    for r in rows:
        try:
            defn = get_definition(r.key)
        except KeyError:
            defn = None
        if defn is not None:
            old_raw = r.old_value.get("v") if isinstance(r.old_value, dict) else r.old_value
            new_raw = r.new_value.get("v") if isinstance(r.new_value, dict) else r.new_value
            old_val = _mask_if_sensitive(defn, old_raw, can_read)
            new_val = _mask_if_sensitive(defn, new_raw, can_read)
        else:
            old_val = r.old_value.get("v") if isinstance(r.old_value, dict) else r.old_value
            new_val = r.new_value.get("v") if isinstance(r.new_value, dict) else r.new_value
        out.append(
            SettingHistoryOut(
                id=r.id,
                setting_id=r.setting_id,
                key=r.key,
                scope=r.scope,
                scope_id=r.scope_id,
                old_value=old_val,
                new_value=new_val,
                action=r.action,
                changed_by=r.changed_by,
                change_reason=r.change_reason,
                source=r.source,
                created_at=r.created_at.isoformat() if r.created_at else "",
            )
        )
    return out


# ---------------------------------------------------------------------------
# Change Requests (§27–§30)
# ---------------------------------------------------------------------------


@router.post("/change-requests", response_model=ChangeRequestOut)
async def create_change_request(
    body: CreateChangeRequestInput,
    ctx: SettingsWriteCtx,
) -> ChangeRequestOut:
    """Create a change request for approval-gated settings."""
    svc = SettingsService(ctx.session, ctx.tenant_id)
    req = await svc.create_change_request(
        body.changes,
        scope=Scope(body.scope),
        scope_id=body.scope_id,
        user_id=ctx.user.id,
        reason=body.reason,
        permissions=ctx.permission_codes,
    )
    return _change_request_to_out(req)


@router.get("/change-requests", response_model=list[ChangeRequestOut])
async def list_change_requests(
    ctx: SettingsReadCtx,
    status: Annotated[str | None, Query()] = None,
) -> list[ChangeRequestOut]:
    """List change requests, optionally filtered by status."""
    svc = SettingsService(ctx.session, ctx.tenant_id)
    rows = await svc.list_change_requests(status=status)
    return [_change_request_to_out(r) for r in rows]


@router.post("/change-requests/{request_id}/approve", response_model=ChangeRequestOut)
async def approve_change_request(
    request_id: uuid.UUID,
    body: ReviewChangeRequestInput,
    ctx: SettingsWriteCtx,
) -> ChangeRequestOut:
    """Approve a pending change request and apply it."""
    if "settings:write" not in ctx.permission_codes:
        raise PermissionDeniedError("approving a change request requires settings:write")
    svc = SettingsService(ctx.session, ctx.tenant_id)
    req = await svc.approve_change_request(
        request_id,
        reviewer_id=ctx.user.id,
        review_note=body.review_note,
        permissions=ctx.permission_codes,
    )
    return _change_request_to_out(req)


@router.post("/change-requests/{request_id}/reject", response_model=ChangeRequestOut)
async def reject_change_request(
    request_id: uuid.UUID,
    body: ReviewChangeRequestInput,
    ctx: SettingsWriteCtx,
) -> ChangeRequestOut:
    """Reject a pending change request."""
    if "settings:write" not in ctx.permission_codes:
        raise PermissionDeniedError("rejecting a change request requires settings:write")
    svc = SettingsService(ctx.session, ctx.tenant_id)
    req = await svc.reject_change_request(
        request_id,
        reviewer_id=ctx.user.id,
        review_note=body.review_note,
    )
    return _change_request_to_out(req)


# ---------------------------------------------------------------------------
# Rollback (§34)
# ---------------------------------------------------------------------------


@router.post("/rollback", response_model=TenantSettingOut | None)
async def rollback_setting(
    body: RollbackInput,
    ctx: SettingsWriteCtx,
) -> dict | None:
    """Roll back a setting to a previous revision's value.

    Creates a NEW revision with the restored value — does not delete history.
    For APPROVAL_REQUIRED settings, a change request is created instead.
    """
    if "settings:write" not in ctx.permission_codes:
        raise PermissionDeniedError("rollback requires settings:write")
    svc = SettingsService(ctx.session, ctx.tenant_id)
    result = await svc.rollback(
        body.history_id,
        user_id=ctx.user.id,
        reason=body.reason,
        permissions=ctx.permission_codes,
        bypass_approval=body.bypass_approval,
    )
    if result is None:
        return {"deleted": True, "message": "Setting reverted to inherited value"}
    # A change request was created for APPROVAL_REQUIRED settings.
    from app.modules.settings.models import SettingChangeRequest

    if isinstance(result, SettingChangeRequest):
        return {
            "change_request_id": str(result.id),
            "status": result.status,
            "message": "Rollback submitted as a change request for approval",
        }
    row = result
    return TenantSettingOut(
        id=row.id,
        key=row.key,
        scope=row.scope,
        scope_id=row.scope_id,
        value=row.value.get("v"),
        updated_by=row.updated_by,
    )


# ---------------------------------------------------------------------------
# Config Migrations (P4)
# ---------------------------------------------------------------------------


@router.get("/migrations", response_model=list[MigrationLogOut])
async def list_config_migrations(
    ctx: SettingsReadCtx,
) -> list[MigrationLogOut]:
    """List config migrations already applied to this tenant."""
    from app.modules.settings.models import SettingMigrationLog

    rows = (
        (
            await ctx.session.execute(
                select(SettingMigrationLog)
                .where(SettingMigrationLog.tenant_id == ctx.tenant_id)
                .order_by(SettingMigrationLog.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [
        MigrationLogOut(
            id=r.id,
            migration_id=r.migration_id,
            description=r.description,
            applied_by=r.applied_by,
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        for r in rows
    ]


@router.post("/migrations/run", response_model=RunMigrationsOut)
async def run_config_migrations(
    ctx: SettingsWriteCtx,
) -> RunMigrationsOut:
    """Run all pending config migrations for this tenant. Idempotent."""
    if "settings:write" not in ctx.permission_codes:
        raise PermissionDeniedError("running config migrations requires settings:write")
    from app.modules.settings.config_migrations import run_pending

    applied = await run_pending(ctx.session, ctx.tenant_id, applied_by=ctx.user.id)
    from app.modules.settings.config_migrations import latest_version

    return RunMigrationsOut(applied=applied, current_version=latest_version())


# ---------------------------------------------------------------------------
# Tenant-Scoped Restore (§164)
# ---------------------------------------------------------------------------


@router.post("/restore")
async def restore_snapshot(
    body: RestoreSnapshotInput,
    ctx: SettingsWriteCtx,
) -> dict[str, int]:
    """Restore all tenant-level settings to their state before a timestamp (§164).

    Requires ``settings:write``. Tenant-scoped by RLS — only touches this
    tenant's overrides. Each change is recorded in history with a restore
    reason, and an audit log entry is written.
    """
    if "settings:write" not in ctx.permission_codes:
        raise PermissionDeniedError("restore requires settings:write")
    from datetime import UTC
    from datetime import datetime as dt

    try:
        snapshot_before = dt.fromisoformat(body.snapshot_before)
        if snapshot_before.tzinfo is None:
            snapshot_before = snapshot_before.replace(tzinfo=UTC)
    except ValueError:
        raise ValidationError(f"invalid ISO timestamp: {body.snapshot_before!r}") from None

    svc = SettingsService(ctx.session, ctx.tenant_id)
    result = await svc.restore_to_snapshot(
        snapshot_before,
        user_id=ctx.user.id,
        reason=body.reason,
        permissions=ctx.permission_codes,
        bypass_approval=body.bypass_approval,
    )
    # Audit the restore operation itself.
    await write_audit_row(
        ctx.session,
        ctx.tenant_id,
        ctx.user.id,
        "settings.restore",
        "tenant_settings",
        str(ctx.tenant_id),
        before={"snapshot_before": body.snapshot_before},
        after=result,
    )
    return result


def _change_request_to_out(r) -> ChangeRequestOut:
    """Convert a SettingChangeRequest ORM row to the API output schema."""
    return ChangeRequestOut(
        id=r.id,
        changes=r.changes,
        applied_changes=r.applied_changes,
        status=r.status,
        scope=r.scope,
        scope_id=r.scope_id,
        submitted_by=r.submitted_by,
        reviewed_by=r.reviewed_by,
        reason=r.reason,
        review_note=r.review_note,
        created_at=r.created_at.isoformat() if r.created_at else "",
        updated_at=r.updated_at.isoformat() if r.updated_at else "",
    )
