"""``import.run``: applies one batch of a merchant's validated import, then queues the next.

The job runner executes a handler inside ONE transaction and commits when it returns, so a loop
over a 100,000-row file would be one transaction holding row locks for as long as it takes (and
would lose everything on a crash at row 99,000). Instead each run applies at most 500 rows and,
if valid rows remain, queues a fresh ``import.run`` job for the same session. A crash loses one
batch; the retry finds the same rows still ``valid`` and takes them again; and a sale that needs
the same variant waits at most one batch, not the whole file.

The job table has no payload column, so the job points at its session through ``correlation_id``.

Cross-module work (catalog, inventory) lives here, in the worker layer, and is handed to
``imports.apply`` as ``Ports``. The module itself imports none of it (``test_module_boundaries``).
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError
from app.modules.imports.apply import BATCH_LIMIT, REFERENCE_TYPE, ApplyError, Ports, apply_batch
from app.modules.imports.models import ImportSession
from app.modules.imports.verdicts import values_of
from app.modules.platform.models import Job
from app.workers.job_runner import register_job_handler

logger = logging.getLogger(__name__)

JOB_KIND = "import.run"
_WAREHOUSE_BY_CODE = text(
    "SELECT id FROM warehouses WHERE tenant_id = :t AND code = :code AND is_active"
)
_VARIANT_BY_SKU = text("SELECT id FROM product_variants WHERE tenant_id = :t AND sku = :sku")
_PRODUCT_BY_SLUG = text("SELECT id FROM products WHERE tenant_id = :t AND slug = :slug")


def _refused(exc: Exception) -> ApplyError:
    """A domain refusal as a merchant-readable row error; anything else is a real bug."""
    return ApplyError(type(exc).__name__.removesuffix("Error").lower() or "refused", str(exc))


async def _upsert_product(
    session: AsyncSession, tenant_id: uuid.UUID, ref: str, values: dict, action: str
) -> uuid.UUID:
    from app.modules.catalog.service import CatalogService

    try:
        product_id = (
            await session.execute(_PRODUCT_BY_SLUG, {"t": tenant_id, "slug": ref})
        ).scalar_one_or_none()
        if product_id is None:
            product = await CatalogService.create_product(
                session,
                tenant_id,
                title=str(values["title"]),
                slug=ref,
                description=values.get("description"),  # type: ignore[arg-type]
            )
        else:
            fields: dict[str, object] = {"title": values["title"]}
            if values.get("description"):
                fields["description"] = values["description"]
            product = await CatalogService.update_product(session, tenant_id, product_id, **fields)
        if values.get("status") and product.status != values["status"]:
            product = await CatalogService.update_product(
                session, tenant_id, product.id, status=values["status"]
            )
        return product.id
    except DomainError as exc:
        raise _refused(exc) from exc


async def _upsert_variant(
    session: AsyncSession, tenant_id: uuid.UUID, ref: str, values: dict, action: str
) -> uuid.UUID:
    from app.modules.catalog.service import CatalogService

    options = {
        name: str(values[key])
        for name, key in (("color", "color"), ("size", "size"))
        if values.get(key)
    }
    sku = values.get("sku")
    try:
        product_id = (
            await session.execute(_PRODUCT_BY_SLUG, {"t": tenant_id, "slug": ref})
        ).scalar_one_or_none()
        if product_id is None:
            raise ApplyError("unknown_product", f"product '{ref}' does not exist")
        variant_id = None
        if sku:
            variant_id = (
                await session.execute(_VARIANT_BY_SKU, {"t": tenant_id, "sku": sku})
            ).scalar_one_or_none()
        if variant_id is None:
            variant = await CatalogService.add_variant(
                session,
                tenant_id,
                product_id,
                sku=sku,
                option_values=options or None,
                price=values["price"],
            )
        else:
            # A blank colour/size cell must not wipe the options the variant already has.
            fields: dict[str, object] = {"price": values["price"]}
            if options:
                fields["option_values"] = options
            variant = await CatalogService.update_variant(session, tenant_id, variant_id, **fields)
        barcode = values.get("barcode")
        if barcode:
            held = await CatalogService.list_identifiers(session, tenant_id, variant.id)
            if not any(i.type == "barcode" and i.value == barcode for i in held):
                await CatalogService.add_identifier(
                    session, tenant_id, variant.id, "barcode", str(barcode)
                )
        return variant.id
    except DomainError as exc:
        raise _refused(exc) from exc


async def _record_opening_stock(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    sku: str,
    warehouse_code: str,
    quantity: Decimal,
    session_id: uuid.UUID,
) -> uuid.UUID | None:
    from app.modules.inventory.service import InventoryService

    variant_id = (
        await session.execute(_VARIANT_BY_SKU, {"t": tenant_id, "sku": sku})
    ).scalar_one_or_none()
    if variant_id is None:
        raise ApplyError("unknown_sku", f"no variant with SKU '{sku}'")
    warehouse_id = (
        await session.execute(_WAREHOUSE_BY_CODE, {"t": tenant_id, "code": warehouse_code})
    ).scalar_one_or_none()
    if warehouse_id is None:
        raise ApplyError("unknown_warehouse", f"no active warehouse '{warehouse_code}'")
    try:
        await InventoryService.move(
            session,
            tenant_id,
            variant_id,
            warehouse_id,
            direction="in",
            quantity=int(quantity),
            reason="opening_stock",
            reference_type=REFERENCE_TYPE,
            reference_id=session_id,
        )
    except DomainError as exc:
        raise _refused(exc) from exc
    return variant_id


PORTS = Ports(
    upsert_product=_upsert_product,
    upsert_variant=_upsert_variant,
    record_opening_stock=_record_opening_stock,
)


async def enqueue_import(
    session: AsyncSession, tenant_id: uuid.UUID, session_id: uuid.UUID, user_id: uuid.UUID | None
) -> Job:
    """Queue the first ``import.run`` job for a session (the route hands this to ``start``)."""
    from app.modules.platform.services.jobs import JobService

    return await JobService.create(
        session,
        tenant_id,
        kind=JOB_KIND,
        actor_user_id=user_id,
        correlation_id=str(session_id),
    )


async def run_batch(session: AsyncSession, job: Job, *, limit: int = BATCH_LIMIT) -> dict:
    """One batch for the session this job points at; queue the next job if rows remain."""
    from app.modules.platform.services.jobs import JobService

    try:
        session_id = uuid.UUID(str(job.correlation_id))
    except ValueError:
        raise RuntimeError(f"import.run job {job.id} has no session in correlation_id") from None

    imp = (
        await session.execute(
            select(ImportSession)
            .where(ImportSession.tenant_id == job.tenant_id, ImportSession.id == session_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if imp is None:
        raise RuntimeError(f"import session {session_id} not found")
    if imp.status in ("cancelled", "completed", "failed"):
        return {"skipped": True, "reason": f"session is {imp.status}"}
    if imp.status != "running":
        imp.status = "running"

    batch = await apply_batch(
        session, job.tenant_id, session_id, PORTS, values_of=values_of, limit=limit
    )

    totals = dict(imp.stats or {})
    for key in ("applied", "skipped", "failed"):
        totals[key] = int(totals.get(key, 0)) + getattr(batch, key)
    totals["remaining"] = batch.remaining

    if batch.remaining > 0 and batch.taken > 0:
        nxt = await JobService.create(
            session,
            job.tenant_id,
            kind=JOB_KIND,
            actor_user_id=job.actor_user_id,
            correlation_id=str(session_id),
        )
        await session.execute(
            update(ImportSession).where(ImportSession.id == session_id).values(job_id=nxt.id)
        )
    else:
        imp.status = "completed"
    imp.stats = totals
    await session.flush()
    logger.info("import.run session=%s %s", session_id, batch.as_dict())
    return {"session_id": str(session_id), **batch.as_dict()}


@register_job_handler(JOB_KIND)
async def _import_run(session: AsyncSession, job: Job) -> dict:
    return await run_batch(session, job)
