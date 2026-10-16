"""Platform health indicator (§103) and diagnostics surface."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter
from sqlalchemy import func, select, text

from app.core.redis import get_redis
from app.modules.platform import schemas
from app.modules.platform.dr import DRService
from app.modules.platform.models import Integration, OutboxEvent
from app.modules.platform.routers._deps import TenantContext, TenantCtxDep

router = APIRouter(prefix="/platform", tags=["platform"])

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
        import sys

        _pr = sys.modules.get("app.modules.platform.router")
        _service = getattr(_pr, "DRService", DRService) if _pr is not None else DRService
        health = await _service.check_dr_health(ctx.session)
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
