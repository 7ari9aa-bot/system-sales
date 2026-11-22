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
from contextvars import ContextVar
from decimal import Decimal

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError
from app.modules.imports.apply import BATCH_LIMIT, REFERENCE_TYPE, ApplyError, Ports, apply_batch
from app.modules.imports.fields import SHEET_VARIANTS
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


#: The shop's own taxonomy, read ONCE per batch run instead of once per row.
#:
#: Every row used to ask the database for the whole category list and the whole brand list to
#: match a name, so a 10,000-row file made 20,000 list queries. Worse, the list is capped at 200:
#: a shop with more categories than that could not match one of its own names and the import
#: created a second copy of it. Both maps are now built once for the run (paging past the cap)
#: and reused for every row in it, and a name created mid-run joins the map so the next row that
#: says the same thing reuses it.
_TAXONOMY_MAPS: ContextVar[dict[str, dict[str, uuid.UUID]] | None] = ContextVar(
    "import_taxonomy_maps", default=None
)
_TAXONOMY_PAGE = 1000


def _name_key(name: object) -> str:
    """Case- and space-insensitive: "بناطيل " and "بناطيل" are the same shelf."""
    return str(name or "").strip().casefold()


async def _load_taxonomy(
    session: AsyncSession, tenant_id: uuid.UUID
) -> dict[str, dict[str, uuid.UUID]]:
    """Every category and brand the shop already has, keyed by normalised name.

    Paged to the end: the 200-row default is a page size for a picker, not the truth about how
    many categories a shop owns, and matching against a truncated list is what forked them.
    """
    from app.modules.catalog.service import CatalogService

    maps: dict[str, dict[str, uuid.UUID]] = {"category": {}, "brand": {}}
    listers = (
        ("category", CatalogService.list_categories),
        ("brand", CatalogService.list_brands),
    )
    for kind, lister in listers:
        offset = 0
        while True:
            page = await lister(session, tenant_id, limit=_TAXONOMY_PAGE, offset=offset)
            for row in page:
                maps[kind].setdefault(_name_key(row.name), row.id)
            if len(page) < _TAXONOMY_PAGE:
                break
            offset += _TAXONOMY_PAGE
    return maps


async def _taxonomy_id(
    session: AsyncSession, tenant_id: uuid.UUID, *, catalog, kind: str, name: object
) -> uuid.UUID | None:
    """The shop's own category/brand id for a name in the file, created when it is new.

    A merchant's spreadsheet says "بناطيل", not a uuid. Matching is case- and space-insensitive
    (the same rule the shop's own pickers use) so an import never forks "بناطيل" and " بناطيل ".
    Inside a run this reads the prefetched map; called on its own (a test, a one-off) it falls
    back to listing the shop's taxonomy the way it used to.
    """
    wanted = str(name or "").strip()
    if not wanted:
        return None
    maps = _TAXONOMY_MAPS.get()
    table = maps.setdefault(kind, {}) if maps is not None else None
    if table is not None:
        found = table.get(_name_key(wanted))
        if found is not None:
            return found
    else:
        rows = (
            await catalog.list_brands(session, tenant_id)
            if kind == "brand"
            else await catalog.list_categories(session, tenant_id)
        )
        for row in rows:
            if _name_key(row.name) == _name_key(wanted):
                return row.id
    made = (
        await catalog.create_brand(session, tenant_id, name=wanted)
        if kind == "brand"
        else await catalog.create_category(session, tenant_id, name=wanted)
    )
    if table is not None:
        table[_name_key(wanted)] = made.id
    return made.id


async def _upsert_product(
    session: AsyncSession, tenant_id: uuid.UUID, ref: str, values: dict, action: str
) -> uuid.UUID:
    from app.modules.catalog.service import CatalogService

    try:
        product_id = (
            await session.execute(_PRODUCT_BY_SLUG, {"t": tenant_id, "slug": ref})
        ).scalar_one_or_none()
        created = product_id is None
        if created:
            product = await CatalogService.create_product(
                session,
                tenant_id,
                title=str(values["title"]),
                slug=ref,
                description=values.get("description"),  # type: ignore[arg-type]
                season=values.get("season"),  # type: ignore[arg-type]
                material=values.get("material"),  # type: ignore[arg-type]
            )
        else:
            fields: dict[str, object] = {"title": values["title"]}
            if values.get("description"):
                fields["description"] = values["description"]
            # A blank cell keeps what the product already says; a filled one is the merchant's word.
            for key in ("season", "material"):
                if values.get(key):
                    fields[key] = values[key]
            product = await CatalogService.update_product(session, tenant_id, product_id, **fields)

        # The file's own words become the shop's taxonomy: an import that leaves every product
        # uncategorised makes the catalog unusable the moment it lands.
        classify: dict[str, object] = {}
        category_id = await _taxonomy_id(
            session, tenant_id, catalog=CatalogService, kind="category", name=values.get("category")
        )
        if category_id is not None:
            classify["category_id"] = category_id
        brand_id = await _taxonomy_id(
            session, tenant_id, catalog=CatalogService, kind="brand", name=values.get("brand")
        )
        if brand_id is not None:
            classify["brand_id"] = brand_id

        # A stated status is the merchant's decision, always. A blank status on a product this
        # import just created means they meant to sell it — it used to land as a draft and never
        # reach the till. An existing product keeps the status it has (re-importing a price list
        # must not resurrect something the shop archived on purpose).
        stated = values.get("status")
        if stated:
            classify["status"] = stated
        elif created:
            classify["status"] = "active"
        if classify:
            product = await CatalogService.update_product(
                session, tenant_id, product.id, **classify
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
        level = values.get("reorder_level")
        if level is not None:
            from app.modules.inventory.stock_view import StockLevelService

            await StockLevelService.set_reorder_level(
                session, tenant_id, variant.id, int(level)
            )
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


_DECLARED_COST = text(
    "SELECT parsed->'values'->>'cost' AS cost FROM import_rows "
    "WHERE tenant_id = :t AND session_id = :s AND sheet = :sheet "
    "AND status IN ('valid','applied') "
    "AND parsed->'values'->>'sku' = :sku ORDER BY row_number LIMIT 1"
)


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
    # The cost the file declared for this SKU travels with the stock it arrives with: a FIFO
    # layer is the only place a cost lives here, so an opening balance recorded without it would
    # value every sale at zero and make the profit report a guess.
    declared = (
        await session.execute(
            _DECLARED_COST, {"t": tenant_id, "s": session_id, "sheet": SHEET_VARIANTS, "sku": sku}
        )
    ).scalar_one_or_none()
    cost_value = Decimal(str(declared)) if declared not in (None, "") else None
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
            cost_value=cost_value,
        )
        if cost_value is not None:
            # The movement records what the stock cost; the FIFO layer is what the valuation and
            # the profit report actually read, so the two are written together.
            await InventoryService.ValuationService.create_cost_layer(
                session,
                tenant_id,
                variant_id=variant_id,
                warehouse_id=warehouse_id,
                quantity=int(quantity),
                unit_cost=cost_value,
                source_type=REFERENCE_TYPE,
                source_id=session_id,
            )
    except DomainError as exc:
        raise _refused(exc) from exc
    return variant_id


MAX_IMAGE_BYTES = 10 * 1024 * 1024  # the same ceiling as a picture uploaded by hand
_IMAGE_SIGNATURES = {
    "image/jpeg": lambda d: d.startswith(b"\xff\xd8\xff"),
    "image/png": lambda d: d.startswith(b"\x89PNG\r\n\x1a\n"),
    "image/gif": lambda d: d.startswith((b"GIF87a", b"GIF89a")),
    "image/webp": lambda d: len(d) >= 12 and d.startswith(b"RIFF") and d[8:12] == b"WEBP",
    "image/bmp": lambda d: d.startswith(b"BM"),
}
_VARIANT_PRODUCT = text(
    "SELECT id, product_id FROM product_variants WHERE tenant_id = :t AND sku = :sku"
)


async def _attach_image(
    session: AsyncSession, tenant_id: uuid.UUID, sku: str, url: str
) -> uuid.UUID:
    """Download one picture, keep it in our own storage, and attach it to the SKU's product.

    The link is fetched by ``storage.fetch``, which refuses non-public hosts on every redirect
    hop and caps the size, so a merchant cannot point the worker at our own network. The bytes
    are then checked against the picture's signature (the same rule as an upload by hand), so a
    page that merely ends in ``.jpg`` is refused. The stored copy is what the catalog shows: the
    merchant's link may be gone next month.
    """
    import hashlib

    from app.core.storage import FetchedMedia, get_storage
    from app.modules.catalog.service import CatalogService

    storage = get_storage()
    if not storage.configured:
        raise ApplyError("storage_unavailable", "image storage is not set up for this shop yet")
    found = (await session.execute(_VARIANT_PRODUCT, {"t": tenant_id, "sku": sku})).one_or_none()
    if found is None:
        raise ApplyError("unknown_sku", f"no variant with SKU '{sku}'")
    variant_id, product_id = found
    try:
        fetched = await storage.fetch(url, max_bytes=MAX_IMAGE_BYTES)
    except DomainError as exc:
        raise ApplyError("image_unreachable", "the image link could not be downloaded") from exc
    except Exception as exc:  # network, TLS, timeout: a fixed sentence, the detail goes to the log
        logger.warning("import.image_fetch_failed error=%s", type(exc).__name__)
        raise ApplyError("image_unreachable", "the image link could not be downloaded") from exc

    kind = (fetched.content_type or "").split(";", 1)[0].strip().lower()
    check = _IMAGE_SIGNATURES.get(kind)
    if check is None:
        raise ApplyError("not_an_image", "the link is not a JPEG, PNG, GIF, WebP or BMP picture")
    if not fetched.data or not check(fetched.data):
        raise ApplyError("not_an_image", "the file at the link is not a real picture")

    media = FetchedMedia(
        data=fetched.data,
        content_type=kind,
        checksum=hashlib.sha256(fetched.data).hexdigest(),
    )
    stored = await storage.store(media, prefix=f"product-images/{tenant_id}", original_url=url)
    if not stored.durable or not stored.storage_key:
        raise ApplyError("storage_unavailable", "the picture could not be saved; try again later")
    try:
        image = await CatalogService.add_image(
            session,
            tenant_id,
            product_id,
            url=f"s3://{stored.storage_key}",
            alt=None,
            variant_id=variant_id,
        )
    except Exception:
        # the row rolls back, so the object we just wrote would be orphaned
        await storage.delete_objects([stored.storage_key])
        raise
    return image.id


async def _attach_item_code(
    session: AsyncSession, tenant_id: uuid.UUID, sku: str, code_type: str, code: str
) -> uuid.UUID:
    """Register the tax item code on the variant, through the catalog (it owns uniqueness)."""
    from app.modules.catalog.service import CatalogService

    variant_id = (
        await session.execute(_VARIANT_BY_SKU, {"t": tenant_id, "sku": sku})
    ).scalar_one_or_none()
    if variant_id is None:
        raise ApplyError("unknown_sku", f"no variant with SKU '{sku}'")
    try:
        row = await CatalogService.add_identifier(
            session, tenant_id, variant_id, code_type.lower(), code
        )
    except DomainError as exc:
        raise _refused(exc) from exc
    return row.id


PORTS = Ports(
    upsert_product=_upsert_product,
    upsert_variant=_upsert_variant,
    record_opening_stock=_record_opening_stock,
    attach_image=_attach_image,
    attach_item_code=_attach_item_code,
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

    # Read the shop's categories and brands once for the whole batch (see _TAXONOMY_MAPS).
    token = _TAXONOMY_MAPS.set(await _load_taxonomy(session, job.tenant_id))
    try:
        batch = await apply_batch(
            session, job.tenant_id, session_id, PORTS, values_of=values_of, limit=limit
        )
    finally:
        _TAXONOMY_MAPS.reset(token)

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
