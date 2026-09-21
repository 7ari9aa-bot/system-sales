"""PLATFORM routes — feature flags (§76), the metric registry (§167), saved
views (§95) and the health indicator (§103).

Flags are rollout switches, not authorization. The registry is read-only: it
tells every screen what a number means so two screens cannot compute it
differently. Saved views are the cross-cutting "list layout" store every entity
screen saves into, and the health surface is what the UI badges.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select, text

from app.core.errors import NotFoundError, PermissionDeniedError, ValidationError
from app.core.redis import get_redis
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission
from app.modules.platform.flags import FeatureFlagService
from app.modules.platform.metrics import MetricRegistry
from app.modules.platform.models import (
    FeatureFlag,
    Integration,
    OutboxEvent,
    SavedView,
)

router = APIRouter(prefix="/platform", tags=["platform"])

FEATURE_MAX_LEN = 127  # matches feature_flags.feature String(127)

# §160: Platform Admin is a SEPARATE plane from Tenant RBAC.
# The platform_admin role is NOT a tenant role — it is a global claim checked
# independently of the tenant context. This means a platform admin can access
# the admin plane WITHOUT being a member of any tenant.
ADMIN_ROLE_CODE = "platform_admin"


def _require_platform_admin(ctx: TenantContext) -> None:
    """Gate: only platform_admin role may access the admin plane (§160).

    This is deliberately separate from tenant RBAC: a tenant admin has full
    RBAC inside their tenant but CANNOT access the platform admin plane.
    """
    if ADMIN_ROLE_CODE not in ctx.permission_codes:
        raise PermissionDeniedError(
            "platform admin access required — this is not a tenant permission"
        )


class FlagUpsert(BaseModel):
    """Body for ``PUT /platform/flags/{feature}``."""

    enabled: bool = True
    workspace_id: uuid.UUID | None = None
    role_code: str | None = Field(default=None, max_length=63)
    rollout_percent: int = Field(default=100, ge=0, le=100)


def _flag_payload(flag: FeatureFlag) -> dict:
    return {
        "feature": flag.feature,
        "enabled": flag.enabled,
        "workspace_id": str(flag.workspace_id) if flag.workspace_id else None,
        "role_code": flag.role_code,
        "rollout_percent": flag.rollout_percent,
    }


@router.get("/flags")
async def list_flags(ctx: TenantCtxDep):
    """Every feature flag configured for the caller's tenant."""
    flags = await FeatureFlagService.list_flags(ctx.session, ctx.tenant_id)
    return [_flag_payload(flag) for flag in flags]


@router.put("/flags/{feature}")
async def upsert_flag(
    feature: str,
    body: FlagUpsert,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """Create or replace the tenant's flag for ``feature`` (idempotent)."""
    if not feature or len(feature) > FEATURE_MAX_LEN:
        raise ValidationError(
            f"feature name must be 1-{FEATURE_MAX_LEN} characters",
            details={"feature": feature},
        )
    flag = await FeatureFlagService.set_flag(
        ctx.session,
        ctx.tenant_id,
        feature,
        enabled=body.enabled,
        workspace_id=body.workspace_id,
        role_code=body.role_code,
        rollout_percent=body.rollout_percent,
    )
    return _flag_payload(flag)


@router.get("/flags/{feature}/check")
async def check_flag(ctx: TenantCtxDep, feature: str):
    """Evaluate ``feature`` for the calling user — used to hide a UI affordance.

    A flag is NOT authorization. This endpoint only tells the client whether to
    *render* something. A disabled flag hides a button; it does not protect the
    action behind that button. The action still needs its own server-side RBAC
    check (``require_permission``) — never branch a security decision on the
    value returned here.

    The caller's user id is passed as ``stable_key`` so a per-user percentage
    rollout buckets the same user consistently across requests. Workspace-scoped
    rows evaluate to false here because the request context carries no workspace.
    """
    enabled = await FeatureFlagService.is_enabled(
        ctx.session,
        ctx.tenant_id,
        feature,
        role_code=ctx.role_code,
        stable_key=str(ctx.user.id),
    )
    return {"feature": feature, "enabled": enabled}


@router.get("/metrics")
async def list_metric_definitions(ctx: TenantCtxDep):
    """The canonical metric registry (§167) — one definition per number.

    Reads need only a tenant context. Every screen must resolve a metric through
    this registry rather than re-deriving the formula, so the same number is not
    computed differently in two places.
    """
    return MetricRegistry.definitions()


# ---------- Saved views (§95) ----------

SAVED_VIEW_VISIBILITIES = frozenset({"private", "team", "workspace"})
SAVED_VIEW_NAME_MAX = 255  # matches saved_views.name String(255)
SAVED_VIEW_ENTITY_MAX = 63  # matches saved_views.entity String(63)


class SavedViewCreate(BaseModel):
    """Body for ``POST /platform/saved-views``."""

    name: str = Field(min_length=1, max_length=SAVED_VIEW_NAME_MAX)
    entity: str = Field(min_length=1, max_length=SAVED_VIEW_ENTITY_MAX)
    # filters / sort / columns / grouping / density — stored verbatim.
    definition: dict = Field(default_factory=dict)
    visibility: str = "private"


class SavedViewUpdate(BaseModel):
    """Body for ``PATCH /platform/saved-views/{id}`` — every field optional."""

    name: str | None = Field(default=None, min_length=1, max_length=SAVED_VIEW_NAME_MAX)
    definition: dict | None = None
    visibility: str | None = None


def can_read_saved_view(view: SavedView, *, user_id: uuid.UUID) -> bool:
    """team/workspace views are tenant-visible; a private view is owner-only."""
    if view.visibility in ("team", "workspace"):
        return True
    return view.visibility == "private" and view.owner_user_id == user_id


def can_modify_saved_view(
    view: SavedView, *, user_id: uuid.UUID, permission_codes: set[str]
) -> bool:
    """Who may PATCH/DELETE a saved view.

    private   -> the owner only. It is the caller's own scratch layout, so
                 nobody else may rewrite it — not even an admin with
                 settings:write.
    team      -> the owner, or anyone holding settings:write. A team view is
                 shared, but curating what the team sees is an administrative
                 act rather than something every member should do silently.
    workspace -> settings:write only, even for the owner. This is the widest
                 blast radius: the view is visible to the whole workspace, so a
                 silent rewrite by any member would change what everyone sees.
                 Requiring a permission is what stops a shared view from being
                 a footgun; ownership alone is not enough.

    An unknown visibility is denied rather than guessed.

    Note this rule IS the authorization for these routes: a private view is a
    personal preference, not a settings change, so a blanket settings:write
    gate would (wrongly) stop an ordinary user from editing their own view.
    """
    if view.visibility == "private":
        return view.owner_user_id == user_id
    if view.visibility == "team":
        return view.owner_user_id == user_id or "settings:write" in permission_codes
    if view.visibility == "workspace":
        return "settings:write" in permission_codes
    return False


def _view_out(view: SavedView) -> dict:
    return {
        "id": str(view.id),
        "name": view.name,
        "entity": view.entity,
        "definition": view.definition or {},
        "visibility": view.visibility,
        "owner_user_id": str(view.owner_user_id) if view.owner_user_id else None,
        "created_at": view.created_at.isoformat() if view.created_at else None,
        "updated_at": view.updated_at.isoformat() if view.updated_at else None,
    }


async def _load_view(ctx: TenantContext, view_id: uuid.UUID) -> SavedView:
    """Fetch a view the caller may see; 404 when it exists but is not visible.

    A private view belonging to somebody else answers 404, not 403 — its very
    existence is private information.
    """
    view = (
        await ctx.session.execute(
            select(SavedView).where(
                SavedView.tenant_id == ctx.tenant_id, SavedView.id == view_id
            )
        )
    ).scalar_one_or_none()
    if view is None or not can_read_saved_view(view, user_id=ctx.user.id):
        raise NotFoundError("saved view not found")
    return view


@router.get("/saved-views")
async def list_saved_views(ctx: TenantCtxDep, entity: str | None = None):
    """The caller's own private views plus every team/workspace view.

    Another user's private view is filtered in the query, never returned and
    left for the client to hide.
    """
    stmt = select(SavedView).where(
        SavedView.tenant_id == ctx.tenant_id,
        or_(
            and_(
                SavedView.visibility == "private",
                SavedView.owner_user_id == ctx.user.id,
            ),
            SavedView.visibility.in_(("team", "workspace")),
        ),
    )
    if entity:
        stmt = stmt.where(SavedView.entity == entity)
    rows = (
        await ctx.session.execute(stmt.order_by(SavedView.name))
    ).scalars().all()
    return {"items": [_view_out(view) for view in rows]}


@router.post("/saved-views", status_code=201)
async def create_saved_view(ctx: TenantCtxDep, body: SavedViewCreate):
    """Create a saved view owned by the caller."""
    if body.visibility not in SAVED_VIEW_VISIBILITIES:
        raise ValidationError(
            f"visibility must be one of {sorted(SAVED_VIEW_VISIBILITIES)}",
            details={"visibility": body.visibility},
        )
    # A workspace-visible view is visible to the whole tenant, so creating one
    # is a shared-resource write rather than a personal preference.
    if body.visibility == "workspace" and "settings:write" not in ctx.permission_codes:
        raise PermissionDeniedError("creating a workspace view requires settings:write")
    view = SavedView(
        tenant_id=ctx.tenant_id,
        name=body.name,
        entity=body.entity,
        definition=body.definition,
        visibility=body.visibility,
        owner_user_id=ctx.user.id,
    )
    ctx.session.add(view)
    await ctx.session.flush()
    return _view_out(view)


@router.get("/saved-views/{view_id}")
async def get_saved_view(ctx: TenantCtxDep, view_id: uuid.UUID):
    """One saved view, if the caller may see it."""
    return _view_out(await _load_view(ctx, view_id))


@router.patch("/saved-views/{view_id}")
async def update_saved_view(ctx: TenantCtxDep, view_id: uuid.UUID, body: SavedViewUpdate):
    """Rename, re-scope or re-define a view the caller may modify."""
    view = await _load_view(ctx, view_id)
    if not can_modify_saved_view(
        view, user_id=ctx.user.id, permission_codes=ctx.permission_codes
    ):
        raise PermissionDeniedError("you may not modify this saved view")
    if body.visibility is not None and body.visibility not in SAVED_VIEW_VISIBILITIES:
        raise ValidationError(
            f"visibility must be one of {sorted(SAVED_VIEW_VISIBILITIES)}",
            details={"visibility": body.visibility},
        )
    if body.name is not None:
        view.name = body.name
    if body.definition is not None:
        view.definition = body.definition
    if body.visibility is not None:
        view.visibility = body.visibility
    await ctx.session.flush()
    return _view_out(view)


@router.delete("/saved-views/{view_id}")
async def delete_saved_view(ctx: TenantCtxDep, view_id: uuid.UUID):
    """Delete a view the caller may modify."""
    view = await _load_view(ctx, view_id)
    if not can_modify_saved_view(
        view, user_id=ctx.user.id, permission_codes=ctx.permission_codes
    ):
        raise PermissionDeniedError("you may not modify this saved view")
    await ctx.session.delete(view)
    await ctx.session.flush()
    return {"id": str(view_id), "deleted": True}


# ---------- Health (§103) ----------

HEALTH_STATUSES = ("healthy", "degraded", "down")
# Outbox lag: how long the oldest unpublished event has been waiting. A healthy
# relay drains within a poll interval; a minute behind is worth surfacing and
# ten minutes is a stuck relay.
OUTBOX_LAG_DEGRADED_SECONDS = 60
OUTBOX_LAG_DOWN_SECONDS = 600
# Consecutive webhook failures reported in integrations.webhook_health.
WEBHOOK_FAILURES_DOWN = 5
# Dead-lettered events across the worker streams.
DLQ_DEPTH_DEGRADED = 1
DLQ_DEPTH_DOWN = 50

# The DLQ stream for each worker: `<source stream>.dlq` (see DLQ_SUFFIX).
DLQ_STREAMS = (
    "message.events.dlq",
    "notification.events.dlq",
    "webhook.events.dlq",
    "platform.events.dlq",
)


def subsystem(name: str, status: str, detail: str | None = None) -> dict:
    """One subsystem row. ``detail`` is a short, non-sensitive description."""
    row: dict = {"name": name, "status": status}
    if detail:
        row["detail"] = detail
    return row


def overall_health_status(subsystems: list[dict]) -> str:
    """Worst status wins — one ``down`` makes the whole surface ``down``.

    The UI shows a single badge; it must not read "healthy" while a subsystem
    is failing, or the badge is worse than useless.
    """
    statuses = {row.get("status") for row in subsystems}
    if "down" in statuses:
        return "down"
    if "degraded" in statuses:
        return "degraded"
    return "healthy"


def build_health_response(subsystems: list[dict]) -> dict:
    """The §103 response envelope: overall status + the per-subsystem rows."""
    return {"status": overall_health_status(subsystems), "subsystems": subsystems}


def integration_health(webhook_health: dict | None) -> str:
    """Map one integration's ``webhook_health`` snapshot to a status.

    Empty or absent health is ``healthy``, not ``degraded``: an integration
    that has simply never received a webhook has not failed, and crying wolf on
    a fresh connection trains the operator to ignore the badge.
    """
    health = webhook_health or {}
    failures = health.get("consecutive_failures")
    if not isinstance(failures, int) or failures <= 0:
        return "healthy"
    if failures >= WEBHOOK_FAILURES_DOWN:
        return "down"
    return "degraded"


async def _database_subsystem(ctx: TenantContext) -> dict:
    try:
        await ctx.session.execute(text("SELECT 1"))
        return subsystem("database", "healthy")
    except Exception as exc:  # noqa: BLE001 — a health check must never raise
        return subsystem("database", "down", f"unreachable ({type(exc).__name__})")


async def _redis_subsystem() -> dict:
    try:
        await get_redis().ping()
        return subsystem("redis", "healthy")
    except Exception as exc:  # noqa: BLE001
        return subsystem("redis", "down", f"unreachable ({type(exc).__name__})")


async def _outbox_subsystem(ctx: TenantContext) -> dict:
    """Age of the oldest unpublished outbox event — the relay's backlog."""
    try:
        oldest = (
            await ctx.session.execute(
                select(func.min(OutboxEvent.created_at)).where(
                    OutboxEvent.status == "pending"
                )
            )
        ).scalar_one_or_none()
    except Exception as exc:  # noqa: BLE001
        return subsystem("outbox", "degraded", f"unknown ({type(exc).__name__})")
    if oldest is None:
        return subsystem("outbox", "healthy", "no pending events")
    lag = max(int((datetime.now(UTC) - oldest).total_seconds()), 0)
    status = "healthy"
    if lag >= OUTBOX_LAG_DOWN_SECONDS:
        status = "down"
    elif lag >= OUTBOX_LAG_DEGRADED_SECONDS:
        status = "degraded"
    return subsystem("outbox", status, f"oldest pending event is {lag}s old")


async def _dlq_subsystem() -> dict:
    """Dead-lettered event count across the worker streams (XLEN is O(1))."""
    try:
        client = get_redis()
        depth = 0
        for stream in DLQ_STREAMS:
            depth += int(await client.xlen(stream) or 0)
    except Exception as exc:  # noqa: BLE001
        return subsystem("dlq", "degraded", f"unknown ({type(exc).__name__})")
    status = "healthy"
    if depth >= DLQ_DEPTH_DOWN:
        status = "down"
    elif depth >= DLQ_DEPTH_DEGRADED:
        status = "degraded"
    return subsystem("dlq", status, f"{depth} dead-lettered events")


async def _integrations_subsystem(ctx: TenantContext) -> dict:
    """Per-integration webhook health, rolled up into one subsystem row."""
    try:
        rows = (
            await ctx.session.execute(
                select(Integration.provider, Integration.webhook_health).where(
                    Integration.tenant_id == ctx.tenant_id
                )
            )
        ).all()
    except Exception as exc:  # noqa: BLE001
        return subsystem("integrations", "degraded", f"unknown ({type(exc).__name__})")
    if not rows:
        return subsystem("integrations", "healthy", "no integrations configured")

    entries = [
        {"provider": provider, "status": integration_health(webhook_health)}
        for provider, webhook_health in rows
    ]
    failing = sum(1 for entry in entries if entry["status"] != "healthy")
    worst = overall_health_status(entries)
    detail = (
        f"{failing} of {len(entries)} integrations failing"
        if failing
        else f"{len(entries)} integrations healthy"
    )
    # Only provider + status leave this endpoint: never webhook_health itself,
    # which may carry a last_error string with a URL in it.
    return subsystem("integrations", worst, detail) | {"integrations": entries}


@router.get("/health")
async def health(ctx: TenantCtxDep) -> dict:
    """§103: per-subsystem status for the UI health indicator.

    Never raises and never 500s — a subsystem that fails is reported as
    ``down``/``degraded`` with a short reason, because a health check that
    errors tells the caller nothing. No secret, URL or connection string is
    ever included: details are fixed strings plus counts and ages.
    """
    subsystems = [
        await _database_subsystem(ctx),
        await _redis_subsystem(),
        await _outbox_subsystem(ctx),
        await _dlq_subsystem(),
        await _integrations_subsystem(ctx),
    ]
    return build_health_response(subsystems)


# ---------- Platform admin plane (§160) ----------
#
# A platform admin is NOT a tenant user. This plane exists for the operator
# who runs the deployment itself: list all tenants, see tenant health, and
# take provisioning actions (suspend, provision, etc.). It is gated by a
# platform-admin role that is separate from any tenant's RBAC.
#
# The §160 design rule: the admin plane must never expose tenant data
# (customers, messages, orders) — only tenant metadata and health. A
# platform admin can see THAT a tenant exists and WHETHER it is healthy,
# not WHAT is inside it.
# NOTE: _require_platform_admin is defined at the top of this file.


@router.get("/admin/tenants")
async def admin_list_tenants(ctx: TenantCtxDep):
    """§160: list all tenants on the deployment (metadata only, no tenant data)."""
    _require_platform_admin(ctx)
    from app.modules.identity.models import Tenant

    rows = (
        await ctx.session.execute(
            select(
                Tenant.id,
                Tenant.name,
                Tenant.status,
                Tenant.plan,
                Tenant.created_at,
            ).order_by(Tenant.created_at.desc())
        )
    ).all()
    return {
        "items": [
            {
                "id": str(row.id),
                "name": row.name,
                "status": row.status,
                "plan": row.plan,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    }


@router.get("/admin/tenants/{tenant_id}")
async def admin_get_tenant(ctx: TenantCtxDep, tenant_id: uuid.UUID):
    """§160: one tenant's metadata + health (no customer/message data)."""
    _require_platform_admin(ctx)
    from app.modules.identity.models import Tenant

    tenant = (
        await ctx.session.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        )
    ).scalar_one_or_none()
    if tenant is None:
        raise NotFoundError("tenant not found")

    # Count outbox backlog for this tenant (not the contents — just the depth)
    outbox_pending = (
        await ctx.session.execute(
            select(func.count(OutboxEvent.id)).where(
                OutboxEvent.tenant_id == tenant_id,
                OutboxEvent.status == "pending",
            )
        )
    ).scalar_one()

    return {
        "id": str(tenant.id),
        "name": tenant.name,
        "status": tenant.status,
        "plan": tenant.plan,
        "created_at": tenant.created_at.isoformat() if tenant.created_at else None,
        "health": {
            "outbox_pending": int(outbox_pending or 0),
        },
    }


@router.patch("/admin/tenants/{tenant_id}/status")
async def admin_update_tenant_status(
    ctx: TenantCtxDep,
    tenant_id: uuid.UUID,
    status: str = "active",
):
    """§160: suspend or reactivate a tenant (provisioning action)."""
    _require_platform_admin(ctx)
    if status not in ("active", "suspended", "provisioning"):
        raise ValidationError(
            "status must be one of: active, suspended, provisioning",
            details={"status": status},
        )
    from app.modules.identity.models import Tenant

    tenant = (
        await ctx.session.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        )
    ).scalar_one_or_none()
    if tenant is None:
        raise NotFoundError("tenant not found")
    tenant.status = status
    await ctx.session.flush()
    return {
        "id": str(tenant.id),
        "status": tenant.status,
    }


# ---------- §147 Break-glass support access ----------


class BreakGlassRequest(BaseModel):
    """Body for POST /platform/admin/break-glass."""

    tenant_id: uuid.UUID
    action: str = Field(min_length=1, max_length=255)
    resource_type: str = Field(min_length=1, max_length=63)
    resource_id: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=10, max_length=2000)


@router.post("/admin/break-glass")
async def admin_break_glass(
    ctx: TenantCtxDep,
    body: BreakGlassRequest,
):
    """§147: emergency access — records a security event + issues a capability token.

    The token is one-shot and expires in 15 minutes. The event is NEVER silent:
    even the platform admin's own break-glass is recorded.
    """
    _require_platform_admin(ctx)
    from app.core.break_glass import break_glass

    token = await break_glass(
        ctx.session,
        tenant_id=body.tenant_id,
        user_id=ctx.user.id,
        action=body.action,
        resource_type=body.resource_type,
        resource_id=body.resource_id,
        reason=body.reason,
        ip=None,
        user_agent=None,
    )
    return {"capability_token": token, "expires_in_minutes": 15}


class BreakGlassValidateRequest(BaseModel):
    """Body for POST /platform/admin/break-glass/validate."""

    capability_token: str
    tenant_id: uuid.UUID
    action: str


@router.post("/admin/break-glass/validate")
async def admin_validate_break_glass(
    ctx: TenantCtxDep,
    body: BreakGlassValidateRequest,
):
    """§147: validate a capability token (one-shot consumption)."""
    _require_platform_admin(ctx)
    from app.core.break_glass import validate_capability

    valid = validate_capability(
        body.capability_token,
        tenant_id=body.tenant_id,
        user_id=ctx.user.id,
        action=body.action,
    )
    return {"valid": valid}


# ---------- §68-69 Secrets management ----------


class SecretRefCreate(BaseModel):
    """Body for POST /platform/secrets."""

    provider: str = Field(min_length=1, max_length=63)
    scope: str = Field(default="tenant", max_length=63)
    vault_key: str = Field(min_length=1, max_length=255)
    value: str = Field(min_length=1)
    workspace_id: uuid.UUID | None = None


class SecretRotateRequest(BaseModel):
    """Body for POST /platform/secrets/{provider}/rotate."""

    new_value: str = Field(min_length=1)


@router.post("/secrets", status_code=201)
async def create_secret_reference(
    ctx: TenantCtxDep,
    body: SecretRefCreate,
):
    """§68: register a secret reference + store the value via SecretStorePort."""
    from app.core.secrets import get_secret_store
    from app.modules.platform.service import SecretService

    # Store the actual value in the secret store first
    store = get_secret_store()
    await store.put(body.vault_key, body.value)

    ref = await SecretService.create_reference(
        ctx.session,
        ctx.tenant_id,
        provider=body.provider,
        scope=body.scope,
        vault_key=body.vault_key,
        workspace_id=body.workspace_id,
    )
    return {
        "id": str(ref.id),
        "provider": ref.provider,
        "scope": ref.scope,
        "vault_key": ref.vault_key,
        "version": ref.version,
        "status": ref.status,
    }


@router.post("/secrets/{provider}/rotate")
async def rotate_secret(
    ctx: TenantCtxDep,
    provider: str,
    body: SecretRotateRequest,
):
    """§69: rotate a secret — old version stays for grace period."""
    from app.modules.platform.service import SecretService

    ref = await SecretService.rotate_secret(
        ctx.session,
        ctx.tenant_id,
        provider,
        body.new_value,
    )
    return {
        "id": str(ref.id),
        "provider": ref.provider,
        "version": ref.version,
        "rotated_at": ref.rotated_at.isoformat() if ref.rotated_at else None,
        "status": ref.status,
    }
