"""Platform metrics registry (§167) — one definition per number."""

from fastapi import APIRouter
from sqlalchemy import select

from app.modules.platform import schemas
from app.modules.platform.metrics import MetricRegistry, MetricSpec, missing_or_drifted
from app.modules.platform.models import MetricDefinition
from app.modules.platform.routers._deps import TenantCtxDep

router = APIRouter(prefix="/platform", tags=["platform"])

# ``(name, version)`` is a row's IDENTITY and every other ``MetricSpec`` field is
# a column the row must mirror, so the compared field list is derived from the
# public spec rather than duplicated from ``metrics._SYNCED_FIELDS``.
# ``tests/test_contract_reachability.py`` pins that these two stay equal.
_DEFINITION_FIELDS: tuple[str, ...] = tuple(
    field for field in MetricSpec.__dataclass_fields__ if field not in ("name", "version")
)


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
