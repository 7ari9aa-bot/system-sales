"""Apply one batch of validated import rows.

The rows are already judged (``validation``) and stored as ``import_rows``; this takes the next
batch of ``valid`` ones and writes them. It never talks to the catalog or the ledger directly:
the caller hands in ``Ports``, the four things an import may do to the shop. That keeps this
module free of other modules' classes (``test_module_boundaries``), makes the order and the
failure handling testable with fakes, and leaves the wiring to the worker, which is where
cross-module work already lives.

Crash safety. A row only becomes ``applied`` in the same transaction as its write, and a batch is
one transaction, so a crash loses at most that batch and the retry takes the same rows again. A
row that cannot be applied (a race the validator could not see, such as a SKU created a second
ago by someone else) becomes ``error`` inside its own savepoint and does not poison the rest.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.imports.fields import (
    SHEET_IMAGES,
    SHEET_ITEM_CODES,
    SHEET_PRODUCTS,
    SHEET_STOCK,
    SHEET_VARIANTS,
)
from app.modules.imports.models import ImportRow

logger = logging.getLogger(__name__)

BATCH_LIMIT = 500  # standing ceiling: a batch never holds more rows than this
# A picture row is a network download plus an object-store write, which a rolled-back batch cannot
# undo. So a batch of pictures is small: a crash orphans at most this many stored files, and the
# transaction (and its row locks) stays short while the downloads run.
IMAGE_BATCH_LIMIT = 25
# Products before variants before stock: a variant needs its product, stock needs its variant.
# Pictures go last: they are the slowest rows (each one is a download) and the least critical, so
# a shop that runs out of time still has every product, price and quantity in place.
SHEET_ORDER = (SHEET_PRODUCTS, SHEET_VARIANTS, SHEET_ITEM_CODES, SHEET_STOCK, SHEET_IMAGES)
OPENING_STOCK_REASON = "opening_stock"
REFERENCE_TYPE = "import_session"


class ApplyError(Exception):
    """A row the shop refused. ``code`` is stable; ``message`` is for the merchant."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(slots=True)
class Ports:
    """What an import may do. Each returns the ids it touched so the row can say what it became."""

    # (ref, values, action) -> product_id
    upsert_product: Callable[[AsyncSession, uuid.UUID, str, dict, str], Awaitable[uuid.UUID]]
    # (product_ref, values, action) -> variant_id
    upsert_variant: Callable[[AsyncSession, uuid.UUID, str, dict, str], Awaitable[uuid.UUID]]
    # (sku, warehouse code, quantity, session id) -> variant_id, or None when 0 (nothing to record)
    record_opening_stock: Callable[
        [AsyncSession, uuid.UUID, str, str, Decimal, uuid.UUID], Awaitable[uuid.UUID | None]
    ]
    # (sku, link) -> image id. Fetches the link, stores the bytes, attaches the picture.
    attach_image: Callable[[AsyncSession, uuid.UUID, str, str], Awaitable[uuid.UUID]]
    # (sku, EGS|GS1, code) -> identifier id. Registers the tax item code on the variant.
    attach_item_code: Callable[[AsyncSession, uuid.UUID, str, str, str], Awaitable[uuid.UUID]]


@dataclass(slots=True)
class BatchResult:
    taken: int = 0
    applied: int = 0
    skipped: int = 0
    failed: int = 0
    remaining: int = 0  # valid rows still waiting after this batch

    def as_dict(self) -> dict[str, int]:
        return {
            "taken": self.taken,
            "applied": self.applied,
            "skipped": self.skipped,
            "failed": self.failed,
            "remaining": self.remaining,
        }


async def _next_rows(
    session: AsyncSession, tenant_id: uuid.UUID, session_id: uuid.UUID, limit: int
) -> list[ImportRow]:
    """The next rows of the EARLIEST sheet that still has valid ones, locked against a twin run."""
    for sheet in SHEET_ORDER:
        rows = (
            (
                await session.execute(
                    select(ImportRow)
                    .where(
                        ImportRow.tenant_id == tenant_id,
                        ImportRow.session_id == session_id,
                        ImportRow.sheet == sheet,
                        ImportRow.status == "valid",
                    )
                    .order_by(ImportRow.row_number)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        if rows:
            return list(rows)
    return []


async def count_valid(session: AsyncSession, tenant_id: uuid.UUID, session_id: uuid.UUID) -> int:
    from sqlalchemy import func

    return (
        await session.execute(
            select(func.count())
            .select_from(ImportRow)
            .where(
                ImportRow.tenant_id == tenant_id,
                ImportRow.session_id == session_id,
                ImportRow.status == "valid",
            )
        )
    ).scalar_one()


async def apply_batch(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    session_id: uuid.UUID,
    ports: Ports,
    *,
    values_of: Callable[[ImportRow], tuple[str, dict]],
    limit: int = BATCH_LIMIT,
) -> BatchResult:
    """Apply up to ``limit`` rows (never more than ``BATCH_LIMIT``) and report what happened.

    ``values_of(row)`` returns ``(action, clean values)`` for a stored row: the parsed values the
    validator produced, kept apart from this function so the import's mapping can change without
    touching how rows are written.
    """
    limit = max(1, min(limit, BATCH_LIMIT))
    result = BatchResult()
    rows = await _next_rows(session, tenant_id, session_id, limit)
    if rows and rows[0].sheet == SHEET_IMAGES:
        rows = rows[:IMAGE_BATCH_LIMIT]
    result.taken = len(rows)

    for row in rows:
        action, values = values_of(row)
        if action == "skip":
            await _mark(session, row, "skipped", None)
            result.skipped += 1
            continue
        try:
            async with session.begin_nested():  # one bad row must not poison the other 499
                ref = await _write(session, tenant_id, session_id, row, action, values, ports)
        except ApplyError as exc:
            await _fail(session, row, exc.code, exc.message)
            result.failed += 1
            continue
        except DBAPIError as exc:
            # a race on a unique key, a value the column refuses: the savepoint has already
            # rolled this row back, so the others are untouched. The driver's text can quote
            # row data, so the merchant gets a fixed sentence and the detail goes to the log.
            logger.warning("import.row_database_error row=%s error=%s", row.id, type(exc.orig))
            await _fail(session, row, "database_error", "the shop could not store this row")
            result.failed += 1
            continue
        await _mark(session, row, "applied", ref)
        result.applied += 1

    result.remaining = await count_valid(session, tenant_id, session_id)
    return result


async def _write(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    session_id: uuid.UUID,
    row: ImportRow,
    action: str,
    values: dict,
    ports: Ports,
) -> dict:
    if row.sheet == SHEET_PRODUCTS:
        product_id = await ports.upsert_product(
            session, tenant_id, str(values["product_ref"]), values, action
        )
        return {"product_id": str(product_id), "action": _past(action)}
    if row.sheet == SHEET_VARIANTS:
        variant_id = await ports.upsert_variant(
            session, tenant_id, str(values["product_ref"]), values, action
        )
        return {"variant_id": str(variant_id), "action": _past(action)}
    if row.sheet == SHEET_STOCK:
        quantity: Decimal = values["quantity"]
        if quantity == 0:
            return {"action": "nothing_to_record"}  # the ledger refuses a movement of 0
        variant_id = await ports.record_opening_stock(
            session, tenant_id, str(values["sku"]), str(values["warehouse"]), quantity, session_id
        )
        return {"variant_id": str(variant_id), "action": "created"}
    if row.sheet == SHEET_IMAGES:
        image_id = await ports.attach_image(
            session, tenant_id, str(values["sku"]), str(values["url"])
        )
        return {"image_id": str(image_id), "action": "created"}
    if row.sheet == SHEET_ITEM_CODES:
        identifier_id = await ports.attach_item_code(
            session, tenant_id, str(values["sku"]), str(values["code_type"]), str(values["code"])
        )
        return {"identifier_id": str(identifier_id), "action": "created"}
    raise ApplyError("unsupported_sheet", f"sheet {row.sheet!r} cannot be imported yet")


def _past(action: str) -> str:
    return {"create": "created", "update": "updated"}.get(action, action)


async def _mark(session: AsyncSession, row: ImportRow, status: str, ref: dict | None) -> None:
    await session.execute(
        update(ImportRow)
        .where(ImportRow.id == row.id, ImportRow.tenant_id == row.tenant_id)
        .values(status=status, applied_ref=ref, errors=[])
        .execution_options(synchronize_session=False)
    )


async def _fail(session: AsyncSession, row: ImportRow, code: str, message: str) -> None:
    await session.execute(
        update(ImportRow)
        .where(ImportRow.id == row.id, ImportRow.tenant_id == row.tenant_id)
        .values(status="error", errors=[{"field": None, "code": code, "message": message}])
        .execution_options(synchronize_session=False)
    )
