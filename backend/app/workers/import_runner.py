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


def _sniff(data: bytes) -> str | None:
    """The picture type the BYTES say they are, whatever a header or a file name claims."""
    return next((kind for kind, check in _IMAGE_SIGNATURES.items() if check(data)), None)


# The archive is read back from storage once per batch, not once per picture: 25 rows of one batch
# would otherwise download the same (up to 200 MB) file 25 times. Keyed by storage key, emptied at
# the start of every batch, so a worker never holds an archive between two jobs.
_archive_cache: dict[str, bytes] = {}


async def _archive_bytes(storage, key: str) -> bytes:
    from app.modules.imports import imagezip

    if key not in _archive_cache:
        _archive_cache.clear()
        fetched = await storage.read_object(key, max_bytes=imagezip.MAX_ZIP_BYTES)
        _archive_cache[key] = fetched.data
    return _archive_cache[key]


async def _picture_bytes(
    session: AsyncSession,
    storage,
    session_id: uuid.UUID,
    tenant_id: uuid.UUID,
    picture: str,
    source: str,
) -> bytes:
    """The picture's bytes: downloaded from a link, or read out of the merchant's archive."""
    from app.core.errors import ValidationError
    from app.modules.imports import imagezip

    if source == "zip":
        key = (
            await session.execute(
                text("SELECT file_key FROM import_sessions WHERE tenant_id = :t AND id = :s"),
                {"t": tenant_id, "s": session_id},
            )
        ).scalar_one_or_none()
        if not key:
            raise ApplyError("no_archive", "the pictures archive is no longer available")
        try:
            archive = await _archive_bytes(storage, key)
            entry = imagezip.catalog_of(archive).find(picture)
            if entry is None:
                raise ApplyError("not_in_archive", f"'{picture}' is not in the pictures archive")
            return imagezip.read_entry(archive, entry)
        except ApplyError:
            raise
        except ValidationError as exc:
            raise ApplyError(
                "image_unreadable", "the picture could not be read from the archive"
            ) from exc
        except Exception as exc:  # storage read failed: a fixed sentence, the detail to the log
            logger.warning("import.archive_read_failed error=%s", type(exc).__name__)
            raise ApplyError(
                "storage_unavailable", "the archive could not be read; try again later"
            ) from exc
    try:
        return (await storage.fetch(picture, max_bytes=MAX_IMAGE_BYTES)).data
    except DomainError as exc:
        raise ApplyError("image_unreachable", "the image link could not be downloaded") from exc
    except Exception as exc:  # network, TLS, timeout: a fixed sentence, the detail goes to the log
        logger.warning("import.image_fetch_failed error=%s", type(exc).__name__)
        raise ApplyError("image_unreachable", "the image link could not be downloaded") from exc


async def _attach_image(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    sku: str,
    picture: str,
    source: str,
    session_id: uuid.UUID,
) -> uuid.UUID:
    """Get one picture (a link or a file in the archive), keep it in our storage, attach it.

    A link is fetched by ``storage.fetch``, which refuses non-public hosts on every redirect hop
    and caps the size, so a merchant cannot point the worker at our own network. Whatever the
    source, the bytes are then checked against the picture's SIGNATURE (never a file name or a
    server's content type), so a page that merely ends in ``.jpg`` is refused. The stored copy is
    what the catalog shows: the merchant's link may be gone next month.
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
    data = await _picture_bytes(session, storage, session_id, tenant_id, picture, source)

    kind = _sniff(data) if data else None
    if kind is None:
        raise ApplyError("not_an_image", "the file is not a JPEG, PNG, GIF, WebP or BMP picture")

    media = FetchedMedia(data=data, content_type=kind, checksum=hashlib.sha256(data).hexdigest())
    stored = await storage.store(
        media, prefix=f"product-images/{tenant_id}", original_url=picture if source == "url" else ""
    )
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


PORTS = Ports(
    upsert_product=_upsert_product,
    upsert_variant=_upsert_variant,
    record_opening_stock=_record_opening_stock,
    attach_image=_attach_image,
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
    if imp.status == "completed" and imp.file_key:
        await _drop_archive(session, imp)
    logger.info("import.run session=%s %s", session_id, batch.as_dict())
    return {"session_id": str(session_id), **batch.as_dict()}


async def _drop_archive(session: AsyncSession, imp: ImportSession) -> None:
    """The kept pictures archive is only needed while the import runs; remove it at the end.

    A failed delete never fails the import (the pictures are already in). ``drop_image_archive``
    clears the key before it deletes, so nothing ever points at a file that may be gone, and a
    leftover object is the storage retention sweep's to collect.
    """
    from app.core.storage import get_storage
    from app.modules.imports import service

    _archive_cache.clear()
    try:
        await service.drop_image_archive(session, imp, storage=get_storage())
    except Exception as exc:
        logger.warning("import.archive_cleanup_failed error=%s", type(exc).__name__)


@register_job_handler(JOB_KIND)
async def _import_run(session: AsyncSession, job: Job) -> dict:
    return await run_batch(session, job)
