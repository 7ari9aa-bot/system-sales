"""PLATFORM routes — feature flags (§76), the metric registry (§167), saved
views (§95), the health indicator (§103), the outbox ledger and the audit
trail (package 2.2 read surfaces), the webhook DLQ (§24) and the security
trail (§67).

Flags are rollout switches, not authorization. The registry is read-only: it
tells every screen what a number means so two screens cannot compute it
differently. Saved views are the cross-cutting "list layout" store every entity
screen saves into, and the health surface is what the UI badges. The outbox
ledger and audit trail are the operator-visible halves of "no event is lost"
(§19) and "every sensitive action is answerable" (§66) — both reads, never
writes; their writers live in their own modules.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select, text

from app.core.errors import NotFoundError, PermissionDeniedError, ValidationError
from app.core.redis import get_redis
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission
from app.modules.platform import schemas
from app.modules.platform.dr import DRService
from app.modules.platform.flags import FeatureFlagService
from app.modules.platform.metrics import MetricRegistry, MetricSpec, missing_or_drifted
from app.modules.platform.models import (
    WEBHOOK_EVENT_STATUSES,
    AuditLog,
    FeatureFlag,
    Integration,
    MetricDefinition,
    OutboxEvent,
    SavedView,
    SecurityEvent,
    WebhookEvent,
)
from app.modules.platform.tenant_restore import TenantRestoreJob, TenantRestoreService

router = APIRouter(prefix="/platform", tags=["platform"])

FEATURE_MAX_LEN = 127  # matches feature_flags.feature String(127)

# Query/header params are declared `Annotated[type, Query(...)] = <value>`, never
# `name: type = Query(...)` / `= Header(...)` — see the parameter-declaration rule
# in app/modules/analytics/router.py and the full-app gate in
# tests/test_route_parameter_declarations.py.

# The paging knobs every paged platform list shares. One ceiling declared once,
# so a fourth list route cannot be born with a wider one (P7: an unclamped
# `limit` is `LIMIT -1`, which PostgreSQL answers with EVERY row, and a negative
# `offset` is a database error raised as a 500). `tests/test_platform_http_surface.py`
# pins that each paged route refuses both.
PageLimit = Annotated[int, Query(ge=1, le=schemas.PAGE_LIMIT_MAX)]
PageOffset = Annotated[int, Query(ge=0)]


# §160: Platform Admin is a SEPARATE plane from Tenant RBAC.
# The claim is global (users.is_platform_admin, minted into the JWT at login)
# and checked independently of the tenant context — a tenant admin has full
# RBAC inside their tenant but CANNOT touch this plane.
def _require_platform_admin(ctx: TenantContext) -> None:
    """Gate: only the global is_platform_admin JWT claim opens the admin plane.

    Deliberately NOT a permission code: ctx.permission_codes come from the
    caller's TENANT role, so gating on a "platform_admin" code would be both
    unreachable (nothing seeds a cross-tenant permission) and dangerous — an
    operator granting that code to a tenant role would turn a plain tenant
    user into a cross-tenant admin able to mint break-glass capabilities for
    ANY tenant. The claim cannot be granted per-tenant.
    """
    if not ctx.user.is_platform_admin:
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


@router.get("/flags", response_model=schemas.FlagListOut)
async def list_flags(ctx: TenantCtxDep):
    """Every feature flag configured for the caller's tenant.

    Ordered by ``feature``, which is unique per tenant
    (``uq_feature_flags_tenant_feature``) — a total order, so the list is
    reproducible without a page. Flags are tenant configuration, not a growing
    user dataset, so this route carries no ``limit``: the row count is bounded by
    the number of switches an operator can name.
    """
    flags = await FeatureFlagService.list_flags(ctx.session, ctx.tenant_id)
    return {"items": [_flag_payload(flag) for flag in flags]}


@router.put("/flags/{feature}", response_model=schemas.FlagOut)
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


@router.get("/flags/{feature}/check", response_model=schemas.FlagCheckOut)
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


@router.get("/metrics", response_model=schemas.MetricListOut)
async def list_metric_definitions(ctx: TenantCtxDep):
    """The canonical metric registry (§167) — one definition per number.

    Reads need only a tenant context. Every screen must resolve a metric through
    this registry rather than re-deriving the formula, so the same number is not
    computed differently in two places.

    SOURCE: the in-code ``MetricRegistry`` (the authority), NOT the
    ``metric_definitions`` table. A tenant that wants the definitions IT was
    measured under — with version history and any convergence gap — reads
    ``GET /platform/metrics/definitions``, which answers from the table.

    The payload is the module's ``{items}`` envelope: the registry has no
    ``updated_at`` to carry and no gap to report, so its rows are
    ``MetricSpecOut`` rather than ``MetricDefinitionRowOut``.
    """
    return {"items": MetricRegistry.definitions()}


# ``(name, version)`` is a row's IDENTITY and every other ``MetricSpec`` field is
# a column the row must mirror, so the compared field list is derived from the
# public spec rather than duplicated from ``metrics._SYNCED_FIELDS``.
# ``tests/test_contract_reachability.py`` pins that these two stay equal.
_DEFINITION_FIELDS: tuple[str, ...] = tuple(
    field for field in MetricSpec.__dataclass_fields__ if field not in ("name", "version")
)


@router.get("/metrics/definitions", response_model=schemas.MetricDefinitionsOut)
async def list_tenant_metric_definitions(ctx: TenantCtxDep):
    """§167: THIS tenant's metric definitions, read from ``metric_definitions``.

    The registry above is the authority; the table is its tenant-visible audit
    copy, written by the provisioning seed (``identity/bootstrap.py``) and
    converged for existing tenants by ``scripts/backfill_metric_definitions.py``.
    Those are both WRITE halves — until this route existed nothing could read a
    row back, so the table held data with no consumer and the only "definitions"
    endpoints answered from Python.

    The two sources agree only when the push actually reached this tenant, so
    the payload reports the gap instead of hiding it:

    * ``items``   — every row the tenant holds, newest version first, so the
      superseded definitions it was once measured under stay visible (history
      the in-code registry physically cannot carry).
    * ``missing`` — registry entries with no row at this ``(name, version)``: a
      tenant provisioned before the seed existed and never backfilled.
    * ``drifted`` — rows that no longer mirror the registry entry they name.

    Two deliberate departures from the module's paging convention. It is not
    paginated because ``missing``/``drifted`` are DERIVED from the rows read: a
    page boundary would report the rows left off it as absent from the tenant,
    inventing a gap the backfill script would then "fix". And its envelope is
    not a bare ``{items}`` because the two extra lists ARE the contract — this
    is the surface that tells an operator the seed never reached them.

    Read-only like its siblings (``GET /flags``, ``GET /metrics``): reads need a
    tenant context, not a write permission. The WHERE clause carries the caller's
    tenant and the tenant GUC is bound for RLS as defence in depth.
    """
    rows = (
        (
            await ctx.session.execute(
                select(MetricDefinition)
                .where(MetricDefinition.tenant_id == ctx.tenant_id)
                .order_by(MetricDefinition.name, MetricDefinition.version.desc())
            )
        )
        .scalars()
        .all()
    )

    existing = {
        (row.name, row.version): {field: getattr(row, field) for field in _DEFINITION_FIELDS}
        for row in rows
    }
    gap = missing_or_drifted(existing)

    return {
        "items": [
            {
                "name": row.name,
                "version": row.version,
                "definition": row.definition,
                "source": row.source,
                "filters": row.filters,
                "timezone_rule": row.timezone_rule,
                "currency_rule": row.currency_rule,
                "refund_treatment": row.refund_treatment,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
            for row in rows
        ],
        "missing": sorted({spec.name for spec in gap if (spec.name, spec.version) not in existing}),
        "drifted": sorted({spec.name for spec in gap if (spec.name, spec.version) in existing}),
    }


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
            select(SavedView).where(SavedView.tenant_id == ctx.tenant_id, SavedView.id == view_id)
        )
    ).scalar_one_or_none()
    if view is None or not can_read_saved_view(view, user_id=ctx.user.id):
        raise NotFoundError("saved view not found")
    return view


@router.get("/saved-views", response_model=schemas.SavedViewListOut)
async def list_saved_views(
    ctx: TenantCtxDep,
    entity: str | None = None,
    limit: PageLimit = schemas.PAGE_LIMIT_DEFAULT,
    offset: PageOffset = 0,
):
    """The caller's own private views plus every team/workspace view.

    Another user's private view is filtered in the query, never returned and
    left for the client to hide.

    Paged, and ordered by ``(name, id)`` rather than ``name`` alone.
    ``saved_views.name`` carries no unique constraint — a tenant can hold two
    views called "Default", one for customers and one for orders, and PostgreSQL
    owes nothing for their relative order. On a single unbounded read that is
    invisible; the moment a page exists it is not: the tied pair can swap places
    between two reads, so one of them crosses the page boundary and the caller
    either sees it twice or never. ``id`` (the primary key) is the tie-break that
    makes ``ORDER BY`` a total order, exactly as the webhook and security-event
    lists already do.

    ``total`` is the size of the WHOLE filtered list, so a client that receives
    ``len(items) < total`` knows it is looking at one page rather than at
    everything it has.
    """
    conditions = [
        SavedView.tenant_id == ctx.tenant_id,
        or_(
            and_(
                SavedView.visibility == "private",
                SavedView.owner_user_id == ctx.user.id,
            ),
            SavedView.visibility.in_(("team", "workspace")),
        ),
    ]
    if entity:
        conditions.append(SavedView.entity == entity)
    total = (
        await ctx.session.execute(select(func.count(SavedView.id)).where(*conditions))
    ).scalar_one()
    rows = (
        (
            await ctx.session.execute(
                select(SavedView)
                .where(*conditions)
                .order_by(SavedView.name, SavedView.id)
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return {
        "items": [_view_out(view) for view in rows],
        "total": int(total),
        "limit": limit,
        "offset": offset,
    }


@router.post("/saved-views", response_model=schemas.SavedViewOut, status_code=201)
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


@router.get("/saved-views/{view_id}", response_model=schemas.SavedViewOut)
async def get_saved_view(ctx: TenantCtxDep, view_id: uuid.UUID):
    """One saved view, if the caller may see it."""
    return _view_out(await _load_view(ctx, view_id))


@router.patch("/saved-views/{view_id}", response_model=schemas.SavedViewOut)
async def update_saved_view(ctx: TenantCtxDep, view_id: uuid.UUID, body: SavedViewUpdate):
    """Rename, re-scope or re-define a view the caller may modify."""
    view = await _load_view(ctx, view_id)
    if not can_modify_saved_view(view, user_id=ctx.user.id, permission_codes=ctx.permission_codes):
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


@router.delete("/saved-views/{view_id}", response_model=schemas.SavedViewDeletedOut)
async def delete_saved_view(ctx: TenantCtxDep, view_id: uuid.UUID):
    """Delete a view the caller may modify."""
    view = await _load_view(ctx, view_id)
    if not can_modify_saved_view(view, user_id=ctx.user.id, permission_codes=ctx.permission_codes):
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
    """Age of the oldest unpublished outbox event and count of stranded publishing events."""
    try:
        # Check for stranded 'publishing' events (older than 5 minutes - silent failure trap)
        stuck_cutoff = datetime.now(UTC) - timedelta(minutes=5)
        stuck_count = (
            await ctx.session.execute(
                select(func.count(OutboxEvent.id)).where(
                    OutboxEvent.status == "publishing",
                    OutboxEvent.updated_at < stuck_cutoff,
                )
            )
        ).scalar_one() or 0

        oldest = (
            await ctx.session.execute(
                select(func.min(OutboxEvent.created_at)).where(OutboxEvent.status == "pending")
            )
        ).scalar_one_or_none()
    except Exception as exc:  # noqa: BLE001
        return subsystem("outbox", "degraded", f"unknown ({type(exc).__name__})")

    if stuck_count > 0:
        return subsystem("outbox", "degraded", f"{stuck_count} event(s) stuck in publishing state")

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


async def _dr_subsystem(ctx: TenantContext) -> dict:
    """§70 → §103: disaster-recovery readiness as one subsystem row.

    The DR policy and its restore-test history are infra metadata, not tenant
    data, so they belong on the same health surface as the outbox and DLQ. A
    restore test that is overdue (or has never run) is ``degraded`` — not
    ``down``: the system is running fine today, it is a recovery-capability
    warning. Details carry only the recorded status and whether the test is
    overdue; no timings or runbook strings leave here.
    """
    try:
        health = await DRService.check_dr_health(ctx.session)
    except Exception as exc:  # noqa: BLE001 — a health check must never raise
        return subsystem("dr", "degraded", f"unknown ({type(exc).__name__})")
    if health.get("healthy"):
        return subsystem("dr", "healthy", "restore test passed and is not overdue")
    if health.get("restore_test_overdue"):
        return subsystem("dr", "degraded", "restore test overdue")
    return subsystem("dr", "degraded", "last restore test did not pass")


@router.get(
    "/health",
    response_model=schemas.PlatformHealthOut,
    # `subsystem()` OMITS `detail` rather than sending it null, and the
    # per-provider rows ride ONLY on the integrations entry; excluding nulls keeps
    # the declared model from inventing keys the surface never had.
    response_model_exclude_none=True,
)
async def health(ctx: TenantCtxDep):
    """§103: per-subsystem status for the UI health indicator.

    Never raises and never 500s — a subsystem that fails is reported as
    ``down``/``degraded`` with a short reason, because a health check that
    errors tells the caller nothing. No secret, URL or connection string is
    ever included: details are fixed strings plus counts and ages.

    Not a ``{items}`` list: this is a status surface, and the frontend's badge
    reads the rolled-up ``status`` beside the rows
    (``frontend/src/lib/queries.ts`` ``PlatformHealth``), so the envelope is
    pinned as-is.
    """
    subsystems = [
        await _database_subsystem(ctx),
        await _redis_subsystem(),
        await _outbox_subsystem(ctx),
        await _dlq_subsystem(),
        await _integrations_subsystem(ctx),
        await _dr_subsystem(ctx),
    ]
    return build_health_response(subsystems)


@router.get("/diagnostics", response_model=schemas.FullDiagnosticsOut)
async def system_diagnostics(ctx: TenantCtxDep) -> schemas.FullDiagnosticsOut:
    """Comprehensive system-wide diagnostic suite with root-cause analysis for every subsystem."""
    from app.modules.platform.diagnostics import SystemDiagnosticsService

    report = await SystemDiagnosticsService.run_full_diagnostics(ctx.session, ctx.tenant_id)
    return schemas.FullDiagnosticsOut.model_validate(report)


@router.post("/diagnostics/remediate", response_model=schemas.RemediationResultOut)
async def remediate_system_issues(ctx: TenantCtxDep) -> schemas.RemediationResultOut:
    """Instant auto-remediation for common silent failures (stuck events, workers)."""
    from app.modules.platform.diagnostics import SystemDiagnosticsService

    result = await SystemDiagnosticsService.auto_remediate(ctx.session, ctx.tenant_id)
    return schemas.RemediationResultOut.model_validate(result)


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


@router.get("/admin/tenants", response_model=schemas.TenantListOut)
async def admin_list_tenants(
    ctx: TenantCtxDep,
    limit: PageLimit = schemas.PAGE_LIMIT_DEFAULT,
    offset: PageOffset = 0,
):
    """§160: list all tenants on the deployment (metadata only, no tenant data).

    The one cross-tenant list on this plane, and until now the one unbounded
    read of it: a deployment's whole tenant count was the size of the dump an
    operator's accidental ``GET`` pulled. Paged with the module's shared ceiling.

    Ordered ``(created_at, id)`` DESC, not ``created_at`` DESC. Tenants
    provisioned together share one ``now()`` — the seed and any bulk provisioning
    run produce stretches of identical timestamps — and an un-tied ORDER BY lets
    PostgreSQL break those ties differently on each read, so across pages one
    tenant is listed twice while another is never listed at all. ``id`` (the
    primary key) is the tie-break that makes the sort a total order.
    """
    _require_platform_admin(ctx)
    from app.modules.identity.models import Tenant

    total = (await ctx.session.execute(select(func.count(Tenant.id)))).scalar_one()
    rows = (
        await ctx.session.execute(
            select(
                Tenant.id,
                Tenant.name,
                Tenant.lifecycle_state,
                Tenant.is_active,
                Tenant.created_at,
            )
            .order_by(Tenant.created_at.desc(), Tenant.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return {
        "items": [
            {
                "id": str(row.id),
                "name": row.name,
                "lifecycle_state": row.lifecycle_state,
                "is_active": row.is_active,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
        "total": int(total),
        "limit": limit,
        "offset": offset,
    }


@router.get("/admin/tenants/{tenant_id}", response_model=schemas.TenantDetailOut)
async def admin_get_tenant(ctx: TenantCtxDep, tenant_id: uuid.UUID):
    """§160: one tenant's metadata + health (no customer/message data)."""
    _require_platform_admin(ctx)
    from app.modules.identity.models import Tenant

    tenant = (
        await ctx.session.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    if tenant is None:
        raise NotFoundError("tenant not found")

    # Count outbox backlog for this tenant (not the contents — just the depth).
    # `outbox_events` is a system table with no tenant column: §19 put tenancy
    # inside the envelope, so the filter reads meta->>'tenant_id' — the same key
    # the relay refuses to publish without. A comparison on OutboxEvent.tenant_id
    # does not even reach SQL; the attribute does not exist. `ix_outbox_status_created`
    # carries the status half of this predicate; nothing indexes the envelope.
    outbox_pending = (
        await ctx.session.execute(
            select(func.count(OutboxEvent.id)).where(
                OutboxEvent.meta["tenant_id"].as_string() == str(tenant_id),
                OutboxEvent.status == "pending",
            )
        )
    ).scalar_one()

    return {
        "id": str(tenant.id),
        "name": tenant.name,
        "lifecycle_state": tenant.lifecycle_state,
        "is_active": tenant.is_active,
        "status_reason": tenant.status_reason,
        "created_at": tenant.created_at.isoformat() if tenant.created_at else None,
        "health": {
            "outbox_pending": int(outbox_pending or 0),
        },
    }


@router.patch("/admin/tenants/{tenant_id}/status", response_model=schemas.TenantStatusOut)
async def admin_update_tenant_status(
    ctx: TenantCtxDep,
    tenant_id: uuid.UUID,
    status: str,
    reason: str | None = None,
    x_break_glass_token: Annotated[str | None, Header()] = None,
):
    """§160/§48: move a tenant's lifecycle state (suspend, reactivate, ...).

    §147: this is a cross-tenant privileged action, so platform-admin rights
    alone are NOT enough — the caller must present a one-shot break-glass
    capability scoped to this tenant and ``tenant_status_change``.

    The mutation runs through TenantLifecycleService.transition — the single
    writer that validates the state machine, keeps ``is_active`` consistent
    and writes the before/after audit + security trail (§66/§67). Request
    validation happens BEFORE the capability is consumed: a bad request must
    not destroy the one-shot token.
    """
    _require_platform_admin(ctx)
    from app.modules.identity.models import Tenant
    from app.modules.identity.service import STATE_POLICIES, TenantLifecycleService

    if status not in STATE_POLICIES:
        raise ValidationError(
            "unknown tenant lifecycle state",
            details={"status": status, "allowed": sorted(STATE_POLICIES)},
        )
    tenant = (
        await ctx.session.execute(select(Tenant).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    if tenant is None:
        raise NotFoundError("tenant not found")

    from app.core.break_glass import validate_capability

    elevated = await validate_capability(
        x_break_glass_token or "",
        tenant_id=tenant_id,
        user_id=ctx.user.id,
        action="tenant_status_change",
    )
    if not elevated:
        raise PermissionDeniedError(
            "tenant status changes require a break-glass capability scoped to "
            "this tenant (POST /platform/admin/break-glass with "
            "action=tenant_status_change)"
        )
    tenant = await TenantLifecycleService.transition(
        ctx.session,
        tenant_id,
        status,
        reason=reason,
        actor_user_id=ctx.user.id,
    )
    return {
        "id": str(tenant.id),
        "lifecycle_state": tenant.lifecycle_state,
        "is_active": tenant.is_active,
    }


@router.post("/webhook-events/{event_id}/retry", response_model=schemas.WebhookRetryOut)
async def admin_retry_webhook_event(ctx: TenantCtxDep, event_id: uuid.UUID):
    """§24: replay a failed or dead-lettered inbound webhook ingress row.

    Stages a ``webhook.event.retry`` event on the webhook.events stream; the
    WebhookWorker then re-runs the EXACT ingest block the channel webhook
    router runs (``IngestService.process_webhook_event``) under the row's
    tenant — the per-message idempotency keys make the replay safe.

    webhook_events is FORCE-RLS, so the row is loaded under the request's
    tenant context: the admin operates on the ACTIVE tenant's rows (X-Tenant-Id
    selects the tenant). FAILED rows (budget left) and DEAD rows (budget spent
    — the DLQ: replay is exactly what it exists for) can be retried; the row
    must have resolved a tenant — an un-attributed ingress has nothing to
    re-ingest and no tenant scope to run it under. The replay re-runs the
    ingest block WITHOUT re-verifying a provider signature, so only rows whose
    signature was verified at ingress are ever replayed (fail-closed, §22).
    """
    _require_platform_admin(ctx)
    from app.core.events.writer import add_outbox_event

    row = await _load_webhook_event(ctx, event_id)
    if not row.signature_valid:
        # Fail-closed: the retry path bypasses the signature check (the raw
        # provider headers are not stored), so the row's recorded
        # ``signature_valid`` flag is the ONLY proof this payload was
        # provider-signed. The ingress router stamps True exactly when
        # ``adapter.check_signature`` passed; a row without that proof must
        # never be turned back into messages by an authenticated surface.
        raise ValidationError(
            "webhook event was never signature-verified — refusing to replay",
            details={"event_id": str(event_id)},
        )
    if row.tenant_id is None:
        raise ValidationError(
            "webhook event has no resolved tenant — nothing to re-ingest",
            details={"event_id": str(event_id)},
        )
    if row.processing_status not in ("failed", "dead"):
        raise ValidationError(
            "only failed or dead-lettered webhook events can be retried",
            details={"event_id": str(event_id), "status": row.processing_status},
        )
    await add_outbox_event(
        ctx.session,
        aggregate_type="webhook",
        aggregate_id=row.id,
        event_type="webhook.event.retry",
        tenant_id=row.tenant_id,
        payload={"webhook_event_id": str(row.id)},
    )
    _audit_webhook_dlq_op(
        ctx,
        row,
        action="webhook_event.retry_scheduled",
        before={"processing_status": row.processing_status},
        after={"retry": "scheduled"},
    )
    return {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "status": row.processing_status,
        "retry": "scheduled",
    }


# ---------------------------------------------------------------------------
# §24 — the DLQ surface: Inspect / Ignore / Mark resolved (retry + replay
# above). Rows are NEVER deleted; a closed case changes status and is audited.
# ---------------------------------------------------------------------------

# Which statuses each close-out accepts — the law against silent drift.
_WEBHOOK_IGNORE_FROM: frozenset[str] = frozenset({"pending", "processing", "failed", "dead"})
_WEBHOOK_RESOLVE_FROM: frozenset[str] = frozenset({"failed", "dead", "ignored"})


async def _load_webhook_event(ctx: TenantContext, event_id: uuid.UUID) -> WebhookEvent:
    row = (
        await ctx.session.execute(select(WebhookEvent).where(WebhookEvent.id == event_id))
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("webhook event not found")
    return row


def _audit_webhook_dlq_op(
    ctx: TenantContext,
    row: WebhookEvent,
    *,
    action: str,
    before: dict | None,
    after: dict | None,
) -> None:
    """§66/§67: every DLQ decision leaves a paper trail (who, which row,
    from what to what, and the operator's reason)."""
    ctx.session.add(
        AuditLog(
            tenant_id=row.tenant_id or ctx.tenant_id,
            actor_user_id=ctx.user.id,
            action=action,
            resource_type="webhook_event",
            resource_id=str(row.id),
            before=before,
            after=after,
        )
    )


def _webhook_event_summary(row: WebhookEvent) -> dict:
    return {
        "id": str(row.id),
        "provider": row.provider,
        "external_event_id": row.external_event_id,
        "tenant_id": str(row.tenant_id) if row.tenant_id else None,
        "received_at": row.received_at.isoformat() if row.received_at else None,
        "signature_valid": row.signature_valid,
        "processing_status": row.processing_status,
        "attempts": row.attempts,
        "last_error": row.last_error,
        "processed_at": row.processed_at.isoformat() if row.processed_at else None,
    }


@router.get("/webhook-events", response_model=schemas.WebhookEventListOut)
async def admin_list_webhook_events(
    ctx: TenantCtxDep,
    status: str | None = None,
    provider: str | None = None,
    limit: PageLimit = schemas.PAGE_LIMIT_DEFAULT,
    offset: PageOffset = 0,
):
    """§24 Inspect: the active tenant's ingress ledger — newest first, with
    the full DLQ vocabulary (dead/ignored/resolved included). The raw payload
    body is deliberately NOT listed; fetch a row for that.

    The reference paging route of this module: a bounded page, a ``total`` so a
    caller can tell a full page from the whole list, and an
    ``(received_at, id)`` DESC sort. ``received_at`` alone is not a total order —
    a burst of deliveries lands inside one clock tick — so ``id`` is the
    tie-break that keeps page 2 from repeating page 1.
    """
    _require_platform_admin(ctx)
    if status is not None and status not in WEBHOOK_EVENT_STATUSES:
        raise ValidationError(
            "unknown webhook event status",
            details={"status": status, "allowed": sorted(WEBHOOK_EVENT_STATUSES)},
        )
    conditions = []
    if status is not None:
        conditions.append(WebhookEvent.processing_status == status)
    if provider is not None:
        conditions.append(WebhookEvent.provider == provider)
    total = (
        await ctx.session.execute(select(func.count(WebhookEvent.id)).where(*conditions))
    ).scalar_one()
    rows = (
        (
            await ctx.session.execute(
                select(WebhookEvent)
                .where(*conditions)
                .order_by(WebhookEvent.received_at.desc(), WebhookEvent.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return {
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "items": [_webhook_event_summary(row) for row in rows],
    }


@router.get("/webhook-events/{event_id}", response_model=schemas.WebhookEventDetailOut)
async def admin_inspect_webhook_event(ctx: TenantCtxDep, event_id: uuid.UUID):
    """§24 Inspect: the full ingress row — envelope, attempts trail AND the
    raw payload, the evidence a replay/ignore/resolve decision is made on."""
    _require_platform_admin(ctx)
    row = await _load_webhook_event(ctx, event_id)
    return {**_webhook_event_summary(row), "payload": row.payload}


@router.post("/webhook-events/{event_id}/ignore", response_model=schemas.WebhookCloseOut)
async def admin_ignore_webhook_event(
    ctx: TenantCtxDep, event_id: uuid.UUID, reason: str | None = None
):
    """§24 Ignore: close a DLQ case as not-worth-processing. The row stays
    (nothing disappears) with status → ignored, and the decision is audited."""
    _require_platform_admin(ctx)
    row = await _load_webhook_event(ctx, event_id)
    if row.processing_status not in _WEBHOOK_IGNORE_FROM:
        raise ValidationError(
            "cannot ignore a webhook event in this state",
            details={
                "event_id": str(event_id),
                "status": row.processing_status,
                "allowed_from": sorted(_WEBHOOK_IGNORE_FROM),
            },
        )
    before = row.processing_status
    row.processing_status = "ignored"
    _audit_webhook_dlq_op(
        ctx,
        row,
        action="webhook_event.ignored",
        before={"processing_status": before, "reason": reason},
        after={"processing_status": "ignored"},
    )
    return {"id": str(row.id), "status": "ignored"}


@router.post("/webhook-events/{event_id}/resolve", response_model=schemas.WebhookCloseOut)
async def admin_resolve_webhook_event(
    ctx: TenantCtxDep, event_id: uuid.UUID, reason: str | None = None
):
    """§24 Mark resolved: the underlying issue was fixed out-of-band (or the
    effect was applied manually) — close the case as resolved. Audited."""
    _require_platform_admin(ctx)
    row = await _load_webhook_event(ctx, event_id)
    if row.processing_status not in _WEBHOOK_RESOLVE_FROM:
        raise ValidationError(
            "cannot resolve a webhook event in this state",
            details={
                "event_id": str(event_id),
                "status": row.processing_status,
                "allowed_from": sorted(_WEBHOOK_RESOLVE_FROM),
            },
        )
    before = row.processing_status
    row.processing_status = "resolved"
    _audit_webhook_dlq_op(
        ctx,
        row,
        action="webhook_event.resolved",
        before={"processing_status": before, "reason": reason},
        after={"processing_status": "resolved"},
    )
    return {"id": str(row.id), "status": "resolved"}


# ---------- §147 Break-glass support access ----------


class BreakGlassRequest(BaseModel):
    """Body for POST /platform/admin/break-glass."""

    tenant_id: uuid.UUID
    action: str = Field(min_length=1, max_length=255)
    resource_type: str = Field(min_length=1, max_length=63)
    resource_id: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=10, max_length=2000)


@router.post("/admin/break-glass", response_model=schemas.BreakGlassOut)
async def admin_break_glass(
    ctx: TenantCtxDep,
    body: BreakGlassRequest,
    request: Request,
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
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return {"capability_token": token, "expires_in_minutes": 15}


class BreakGlassValidateRequest(BaseModel):
    """Body for POST /platform/admin/break-glass/validate."""

    capability_token: str
    tenant_id: uuid.UUID
    action: str


@router.post("/admin/break-glass/validate", response_model=schemas.BreakGlassValidateOut)
async def admin_validate_break_glass(
    ctx: TenantCtxDep,
    body: BreakGlassValidateRequest,
):
    """§147: pre-flight check whether a capability token is valid.

    Read-only on purpose: a *check* must not burn the one-shot token — the
    capability is consumed by the protected action itself (GETDEL there).
    """
    _require_platform_admin(ctx)
    from app.core.break_glass import peek_capability

    valid = await peek_capability(
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


@router.post("/secrets", response_model=schemas.SecretReferenceOut, status_code=201)
async def create_secret_reference(
    body: SecretRefCreate,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """§68: register a secret reference + store the value via SecretStorePort.

    Gated by settings:write like every other credential surface (flags,
    integrations): registering a secret is a configuration action, not
    something any tenant member may do.
    """
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
        actor_user_id=ctx.user.id,
    )
    return {
        "id": str(ref.id),
        "provider": ref.provider,
        "scope": ref.scope,
        "vault_key": ref.vault_key,
        "version": ref.version,
        "status": ref.status,
    }


@router.post("/secrets/{provider}/rotate", response_model=schemas.SecretRotatedOut)
async def rotate_secret(
    provider: str,
    body: SecretRotateRequest,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """§69: rotate a secret — old version stays for grace period.

    Gated by ``settings:write`` exactly like the sibling ``POST /secrets``
    (registration): rotating a live channel credential is a configuration
    action, not something any tenant member — least of all frontline staff —
    may do. §115 counts a missing API-side check as broken authorization even
    where no screen exposes the call, which is the case here: the frontend has
    no secrets surface at all today, so this dependency is the ONLY thing
    standing between a member role and a live provider credential.
    """
    from app.modules.platform.service import SecretService

    ref = await SecretService.rotate_secret(
        ctx.session,
        ctx.tenant_id,
        provider,
        body.new_value,
        actor_user_id=ctx.user.id,
    )
    return {
        "id": str(ref.id),
        "provider": ref.provider,
        "version": ref.version,
        "rotated_at": ref.rotated_at.isoformat() if ref.rotated_at else None,
        "status": ref.status,
    }


# ---------------------------------------------------------------------------
# §164: tenant-scoped restore
#
# A tenant that destroyed its own data (the §164 "3000 customers" incident)
# restores it HERE — on the tenant plane, not the §160 admin plane, because
# the job reads and revives tenant data. §143 tombstones keep soft-deleted
# rows in place, so extraction/validation/execution run against the live
# tables under the caller's RLS-bound session (the service re-binds to the
# job's target tenant regardless); no other tenant's rows can be read or
# revived, and a full production PITR is never overwritten for one tenant.
# ---------------------------------------------------------------------------


class TenantRestoreJobCreate(BaseModel):
    """Body for ``POST /platform/tenant-restores``."""

    backup_point: datetime
    entity_types: list[str] = Field(min_length=1)


def _restore_job_payload(job: TenantRestoreJob) -> dict:
    return {
        "id": str(job.id),
        "target_tenant_id": str(job.target_tenant_id),
        "backup_point": job.backup_point.isoformat() if job.backup_point else None,
        "entity_types": job.entity_types,
        "status": job.status,
        "extraction_results": job.extraction_results,
        "validation_results": job.validation_results,
        "restore_results": job.restore_results,
        "last_error": job.last_error,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


@router.post("/tenant-restores", response_model=schemas.TenantRestoreJobOut, status_code=201)
async def create_tenant_restore_job(
    body: TenantRestoreJobCreate,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """§164: open a restore job for the CALLER's tenant (never another's).

    ``backup_point`` is the incident watermark: rows tombstoned at or after
    it are the restore candidates; rows already dead before it predate the
    incident and stay dead.
    """
    job = await TenantRestoreService.create_restore_job(
        ctx.session,
        ctx.tenant_id,
        target_tenant_id=ctx.tenant_id,
        backup_point=body.backup_point,
        entity_types=body.entity_types,
    )
    return _restore_job_payload(job)


@router.get("/tenant-restores/{job_id}", response_model=schemas.TenantRestoreJobOut)
async def get_tenant_restore_job(ctx: TenantCtxDep, job_id: uuid.UUID):
    """One restore job's status + extraction/validation/restore manifests."""
    job = await TenantRestoreService.get_restore_job(ctx.session, ctx.tenant_id, job_id)
    return _restore_job_payload(job)


@router.post("/tenant-restores/{job_id}/extract", response_model=schemas.TenantRestoreJobOut)
async def extract_tenant_restore_job(
    job_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """§164 step 2: stage the tenant's tombstoned rows into the job manifest.

    Tombstones live in the live tables, so the request session doubles as
    the recovery session; the full-PITR variant injects an isolated one.
    """
    job = await TenantRestoreService.extract_tenant_data(
        ctx.session,
        ctx.tenant_id,
        job_id,
        recovery_session=ctx.session,
    )
    return _restore_job_payload(job)


@router.post("/tenant-restores/{job_id}/validate", response_model=schemas.TenantRestoreJobOut)
async def validate_tenant_restore_job(
    job_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """§164 step 3: re-check staged rows against current state.

    Any conflict (row already live, id collision, tenant mismatch, failed
    extraction) FAILS the job; only a clean validation unlocks execute.
    """
    job = await TenantRestoreService.validate_against_current(ctx.session, ctx.tenant_id, job_id)
    return _restore_job_payload(job)


@router.post("/tenant-restores/{job_id}/execute", response_model=schemas.TenantRestoreJobOut)
async def execute_tenant_restore_job(
    job_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("settings:write")),
):
    """§164 step 4: revive the staged tombstoned rows in one transaction.

    Refuses to run unless validation passed. Writes an audit row and stages
    ``tenant.restore.completed`` on the outbox in the same transaction.
    """
    job = await TenantRestoreService.execute_restore(ctx.session, ctx.tenant_id, job_id)
    return _restore_job_payload(job)


# ---------------------------------------------------------------------------
# §67: the security-event read surface
#
# `security_events` had nine production writers and ZERO readers — the Wave C
# lesson ("built, tested in isolation, never called") in its purest form. This
# is the operator-visible half. Deliberations:
#
# * Gated by `settings:read` — the code every other admin-facing read uses;
#   no new permission strings are invented here.
# * Tenant isolation is EXPLICIT (`tenant_id == ctx.tenant_id`) on top of the
#   table's FORCE RLS. Pre-auth NULL-tenant rows (login failures recorded
#   before any tenant is known) are NOT returned: RLS makes them visible to
#   every tenant, so a tenant endpoint that passed them through would leak
#   one tenant's probing patterns to another. They belong to a future
#   platform-admin plane, which must make that exposure decision openly.
# * `details` is redacted through app.core.field_auth (§146): PII keys are
#   nulled without `pii:read`, secret keys (`vault_key`, tokens) ALWAYS.
# ---------------------------------------------------------------------------


@router.get("/security-events", response_model=schemas.SecurityEventListOut)
async def list_security_events(
    ctx: TenantContext = Depends(require_permission("settings:read")),
    event_type: str | None = None,
    limit: PageLimit = schemas.PAGE_LIMIT_DEFAULT,
    offset: PageOffset = 0,
):
    """§67: this tenant's security trail, newest first. Read-only.

    It already sorted on ``(created_at, id)`` DESC — the tie-break the comment
    below explains — but had a ``limit`` and no ``offset``, so the trail was
    unreadable past its first page: a caller asking for ``offset=50`` was not
    refused, it was handed page 1 again and had no way to know. It also had no
    ``total``, so "the tenant has 4 000 login failures" and "the tenant has 50"
    were the same answer.
    """
    from app.core.field_auth import redact_fields

    conditions = [SecurityEvent.tenant_id == ctx.tenant_id]
    if event_type:
        conditions.append(SecurityEvent.event_type == event_type)
    total = (
        await ctx.session.execute(select(func.count(SecurityEvent.id)).where(*conditions))
    ).scalar_one()
    stmt = (
        select(SecurityEvent)
        .where(*conditions)
        # created_at alone is not a total order: security events written in one
        # transaction share now(), so an un-tied ORDER BY lets `limit` drop an
        # arbitrary row and lets equal-timestamp pages reorder. id (a uuid4) is
        # the deterministic tie-break — the same contract the notifications list
        # surface already uses, so the two reads do not disagree.
        .order_by(SecurityEvent.created_at.desc(), SecurityEvent.id.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await ctx.session.execute(stmt)).scalars().all()
    return {
        "items": [
            {
                "id": str(event.id),
                "event_type": event.event_type,
                "actor_user_id": str(event.actor_user_id) if event.actor_user_id else None,
                "ip": event.ip,
                "details": redact_fields(
                    dict(event.details or {}), permission_codes=ctx.permission_codes
                ),
                "created_at": event.created_at.isoformat() if event.created_at else None,
            }
            for event in rows
        ],
        "total": int(total),
        "limit": limit,
        "offset": offset,
    }


# ---------------------------------------------------------------------------
# §19: the outbox read surface (package 2.2)
#
# ``add_outbox_event`` has writers in every module and the relay drains the
# table, but nothing could LOOK at what was staged: diagnostics counts backlog
# depth and nothing more, so "no event was lost" (this package's goal) was an
# unobservable claim. This is the operator-visible ledger.
#
# * outbox_events is a SYSTEM table with no tenant column: §19 puts tenancy
#   inside the envelope (``meta["tenant_id"]`` — the key the relay refuses to
#   publish without). The read filters on exactly that key, and because the
#   table has NO RLS backstop, the explicit predicate IS the isolation — the
#   tests pin that another tenant's row is a 404, not a 403.
# * Gated by `settings:read`, the code every other admin-facing read in this
#   module uses; no new permission strings.
# * DELIBERATELY no manual retry endpoint here: a re-staged event gets a NEW
#   outbox id, so consumers' ``processed_events`` dedupe (keyed on
#   ``meta["outbox_id"]``) would miss it and the effect would run twice.
#   Retries belong to the relay's durable backoff (``not_before``); a row
#   stranded mid-publish is reclaimed by POST /platform/diagnostics/remediate
#   under its own audit trail.
# ---------------------------------------------------------------------------

_OUTBOX_STATUSES: frozenset[str] = frozenset({"pending", "publishing", "published", "failed"})


def _outbox_event_summary(row: OutboxEvent) -> dict:
    return {
        "id": str(row.id),
        "aggregate_type": row.aggregate_type,
        "aggregate_id": str(row.aggregate_id),
        "stream": row.stream,
        "status": row.status,
        "attempts": int(row.attempts or 0),
        "last_error": row.last_error,
        "not_before": row.not_before.isoformat() if row.not_before else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "published_at": row.published_at.isoformat() if row.published_at else None,
    }


@router.get("/outbox-events", response_model=schemas.OutboxEventListOut)
async def list_outbox_events(
    ctx: TenantContext = Depends(require_permission("settings:read")),
    status: str | None = None,
    limit: PageLimit = schemas.PAGE_LIMIT_DEFAULT,
    offset: PageOffset = 0,
):
    """§19: this tenant's staged relay events, newest first. Read-only.

    A bounded page with a ``total``, and a ``(created_at, id)`` DESC sort —
    events staged in one transaction share ``now()``, so ``id`` is the
    tie-break that keeps page 2 from repeating page 1. The payload body is
    deliberately NOT listed; fetch a row for that.
    """
    if status is not None and status not in _OUTBOX_STATUSES:
        raise ValidationError(
            "unknown outbox event status",
            details={"status": status, "allowed": sorted(_OUTBOX_STATUSES)},
        )
    conditions = [OutboxEvent.meta["tenant_id"].as_string() == str(ctx.tenant_id)]
    if status is not None:
        conditions.append(OutboxEvent.status == status)
    total = (
        await ctx.session.execute(select(func.count(OutboxEvent.id)).where(*conditions))
    ).scalar_one()
    rows = (
        (
            await ctx.session.execute(
                select(OutboxEvent)
                .where(*conditions)
                .order_by(OutboxEvent.created_at.desc(), OutboxEvent.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return {
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "items": [_outbox_event_summary(row) for row in rows],
    }


@router.get("/outbox-events/{event_id}", response_model=schemas.OutboxEventDetailOut)
async def inspect_outbox_event(
    event_id: uuid.UUID,
    ctx: TenantContext = Depends(require_permission("settings:read")),
):
    """§19: the full relay row — envelope, attempts AND the payload/meta the
    relay carried, the evidence a lost/duplicated event is investigated with.

    Tenant isolation rides the same ``meta["tenant_id"]`` predicate as the
    list: another tenant's event id answers 404.
    """
    row = (
        await ctx.session.execute(
            select(OutboxEvent).where(
                OutboxEvent.id == event_id,
                OutboxEvent.meta["tenant_id"].as_string() == str(ctx.tenant_id),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise NotFoundError("outbox event not found")
    return {
        **_outbox_event_summary(row),
        "payload": dict(row.payload or {}),
        "meta": dict(row.meta or {}),
    }


# ---------------------------------------------------------------------------
# §66: the audit-log read surface (package 2.2)
#
# ``AuditService.write`` has callers across the app (every DLQ decision, tenant
# status change, secret rotation, retention write...) and ZERO readers — the
# Wave C lesson ("built, tested in isolation, never called") again. Deliberations
# mirror the §67 surface above:
#
# * Tenant isolation is EXPLICIT (``tenant_id == ctx.tenant_id``). Platform-
#   level rows with a NULL tenant are NOT returned: they carry actions taken
#   outside any tenant, and exposing them through a tenant endpoint is an
#   exposure decision that belongs to the platform-admin plane.
# * Gated by `settings:read`; no new permission strings.
# * The filters stay narrow: ``action``/``resource_type``/``source`` are exact
#   matches (no wildcards to widen the read), ``source`` is bounded to the
#   §66 vocabulary, and the period is a validated ``since``/``until`` pair.
# * The §66 lineage fields (``source`` / ``request_id`` / ``correlation_id``)
#   are part of the response. A row written outside a request scope has NULL
#   ids — they render as JSON null, never as a string "null".
# ---------------------------------------------------------------------------

_AUDIT_SOURCES: frozenset[str] = frozenset({"human", "ai", "automation", "system", "integration"})


@router.get("/audit-logs", response_model=schemas.AuditLogListOut)
async def list_audit_logs(
    ctx: TenantContext = Depends(require_permission("settings:read")),
    action: Annotated[str | None, Query(max_length=127)] = None,
    resource_type: Annotated[str | None, Query(max_length=63)] = None,
    source: str | None = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    limit: PageLimit = schemas.PAGE_LIMIT_DEFAULT,
    offset: PageOffset = 0,
):
    """§66: this tenant's audited actions, newest first, with lineage.

    A bounded page with a ``total`` and a ``(created_at, id)`` DESC sort —
    rows written in one request share the transaction clock, so ``id`` is the
    tie-break. The period is inclusive/exclusive at the bounds the caller
    names (``since <= created_at < until``); a reversed range is a 400, not a
    silently empty page.
    """
    if source is not None and source not in _AUDIT_SOURCES:
        raise ValidationError(
            "unknown audit source",
            details={"source": source, "allowed": sorted(_AUDIT_SOURCES)},
        )
    if since is not None and until is not None and since > until:
        raise ValidationError(
            "audit period is reversed — since must not be after until",
            details={"since": since.isoformat(), "until": until.isoformat()},
        )
    conditions = [AuditLog.tenant_id == ctx.tenant_id]
    if action:
        conditions.append(AuditLog.action == action)
    if resource_type:
        conditions.append(AuditLog.resource_type == resource_type)
    if source is not None:
        conditions.append(AuditLog.source == source)
    if since is not None:
        conditions.append(AuditLog.created_at >= since)
    if until is not None:
        conditions.append(AuditLog.created_at < until)
    total = (
        await ctx.session.execute(select(func.count(AuditLog.id)).where(*conditions))
    ).scalar_one()
    rows = (
        (
            await ctx.session.execute(
                select(AuditLog)
                .where(*conditions)
                .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return {
        "total": int(total),
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "id": str(entry.id),
                "actor_user_id": str(entry.actor_user_id) if entry.actor_user_id else None,
                "action": entry.action,
                "resource_type": entry.resource_type,
                "resource_id": entry.resource_id,
                "before": entry.before,
                "after": entry.after,
                "source": entry.source,
                "request_id": entry.request_id,
                "correlation_id": entry.correlation_id,
                "created_at": entry.created_at.isoformat() if entry.created_at else None,
            }
            for entry in rows
        ],
    }
