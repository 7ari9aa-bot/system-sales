"""Read what the shop already holds for the keys a file mentions.

One query per kind of key, never one per row: a 100,000-row file must not become 100,000 round
trips. Keys are looked up in chunks so the ``IN`` list stays small. Everything here is read-only
and runs under the tenant's own RLS context.

This is a read-model: it names the few columns it needs by table and column, and imports no other
module's classes. Importing ``catalog`` and ``inventory`` models would couple this module to both
for the sake of four columns (spec §137, ``test_module_boundaries``). The cost is that a renamed
column breaks here at run time instead of import time, which ``test_imports_lookup`` guards.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Iterator

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.imports.validation import Existing

CHUNK = 500  # the same ceiling as an import batch
OPENING_STOCK_REASON = "opening_stock"
BARCODE_TYPE = "barcode"


def _chunks[T](values: Iterable[T], size: int = CHUNK) -> Iterator[list[T]]:
    batch: list[T] = []
    for value in values:
        batch.append(value)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


_PRODUCT_SLUGS = text(
    "SELECT slug FROM products WHERE tenant_id = :t AND slug IN :keys"
).bindparams(bindparam("keys", expanding=True))

_SKU_OWNERS = text(
    "SELECT v.sku, p.slug FROM product_variants v JOIN products p ON p.id = v.product_id "
    "WHERE v.tenant_id = :t AND v.sku IN :keys"
).bindparams(bindparam("keys", expanding=True))

_BARCODE_OWNERS = text(
    "SELECT i.value, v.sku FROM product_identifiers i "
    "JOIN product_variants v ON v.id = i.variant_id "
    "WHERE i.tenant_id = :t AND i.type = :kind AND i.value IN :keys"
).bindparams(bindparam("keys", expanding=True))

_WAREHOUSES = text("SELECT code FROM warehouses WHERE tenant_id = :t AND is_active")

# A picture is attached to a PRODUCT (optionally bound to one variant). The SKU in an import row
# names a variant, so the pair we compare is (that variant's SKU, link): a gallery entry bound to
# the variant, or a product-level one on the variant's product. Either means "already there".
_IMAGES_ATTACHED = text(
    "SELECT DISTINCT v.sku, i.url FROM product_images i "
    "JOIN product_variants v ON v.tenant_id = i.tenant_id "
    "AND (i.variant_id = v.id OR (i.variant_id IS NULL AND i.product_id = v.product_id)) "
    "WHERE i.tenant_id = :t AND v.sku IN :keys"
).bindparams(bindparam("keys", expanding=True))

# A tax item code lives in product_identifiers (type egs / gs1). Two questions, both by the keys in
# the file: who already holds this (type, code), and which of these SKUs already carry a code of
# a type. Raw SQL for the same reason as the rest of this file: a read-model, no foreign tables.
_CODE_OWNERS = text(
    "SELECT i.type, i.value, v.sku FROM product_identifiers i "
    "JOIN product_variants v ON v.tenant_id = i.tenant_id AND v.id = i.variant_id "
    "WHERE i.tenant_id = :t AND i.type IN ('egs', 'gs1') AND i.value IN :keys"
).bindparams(bindparam("keys", expanding=True))

_CODES_OF_SKUS = text(
    "SELECT i.type, v.sku, i.value FROM product_identifiers i "
    "JOIN product_variants v ON v.tenant_id = i.tenant_id AND v.id = i.variant_id "
    "WHERE i.tenant_id = :t AND i.type IN ('egs', 'gs1') AND v.sku IN :keys"
).bindparams(bindparam("keys", expanding=True))

_OPENING_DONE = text(
    "SELECT DISTINCT v.sku, w.code FROM inventory_movements m "
    "JOIN product_variants v ON v.id = m.variant_id JOIN warehouses w ON w.id = m.warehouse_id "
    "WHERE m.tenant_id = :t AND m.reason = :reason AND v.sku IN :keys"
).bindparams(bindparam("keys", expanding=True))

_KNOWN_SKUS = text(
    "SELECT sku FROM product_variants WHERE tenant_id = :t AND sku IN :keys"
).bindparams(bindparam("keys", expanding=True))


async def load_existing(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    product_refs: Iterable[str],
    skus: Iterable[str],
    barcodes: Iterable[str],
) -> Existing:
    """Fill ``Existing`` for exactly the keys the file mentions."""
    existing = Existing()

    for batch in _chunks(sorted(set(product_refs))):
        rows = await session.execute(_PRODUCT_SLUGS, {"t": tenant_id, "keys": batch})
        existing.product_slugs.update(rows.scalars())

    for batch in _chunks(sorted(set(skus))):
        rows = await session.execute(_SKU_OWNERS, {"t": tenant_id, "keys": batch})
        existing.sku_owner.update({sku: slug for sku, slug in rows.all()})

    for batch in _chunks(sorted(set(barcodes))):
        rows = await session.execute(
            _BARCODE_OWNERS, {"t": tenant_id, "kind": BARCODE_TYPE, "keys": batch}
        )
        existing.barcode_owner.update({value: sku or "" for value, sku in rows.all()})

    existing.warehouse_codes.update(
        (await session.execute(_WAREHOUSES, {"t": tenant_id})).scalars()
    )
    return existing


async def load_opening_stock_done(
    session: AsyncSession, tenant_id: uuid.UUID, skus: Iterable[str]
) -> set[tuple[str, str]]:
    """(sku, warehouse code) pairs that already carry an ``opening_stock`` ledger row."""
    done: set[tuple[str, str]] = set()
    for batch in _chunks(sorted(set(skus))):
        rows = await session.execute(
            _OPENING_DONE, {"t": tenant_id, "reason": OPENING_STOCK_REASON, "keys": batch}
        )
        done.update((sku, code) for sku, code in rows.all() if sku)
    return done


async def known_variant_skus(
    session: AsyncSession, tenant_id: uuid.UUID, skus: Iterable[str]
) -> set[str]:
    """Which of these SKUs already exist as variants (so stock may reference them)."""
    found: set[str] = set()
    for batch in _chunks(sorted(set(skus))):
        rows = await session.execute(_KNOWN_SKUS, {"t": tenant_id, "keys": batch})
        found.update(rows.scalars())
    return found


async def load_attached_images(
    session: AsyncSession, tenant_id: uuid.UUID, skus: Iterable[str]
) -> set[tuple[str, str]]:
    """(sku, link) pairs the shop already has, so re-running a file does not duplicate photos."""
    done: set[tuple[str, str]] = set()
    for batch in _chunks(sorted(set(skus))):
        rows = await session.execute(_IMAGES_ATTACHED, {"t": tenant_id, "keys": batch})
        done.update((sku, url) for sku, url in rows.all() if sku and url)
    return done


def default_warehouse(existing: Existing, chosen: str | None) -> str | None:
    """The warehouse a stock row falls back to when its own cell is blank.

    An explicit choice wins. Otherwise, a shop with exactly one active warehouse has an obvious
    answer; with several there is none, and the row is refused instead of guessing.
    """
    if chosen:
        return chosen
    if len(existing.warehouse_codes) == 1:
        return next(iter(existing.warehouse_codes))
    return None


async def load_item_code_owners(
    session: AsyncSession, tenant_id: uuid.UUID, codes: Iterable[str]
) -> dict[tuple[str, str], str]:
    """``(EGS|GS1, code) -> SKU`` for the codes in this file that some variant already holds."""
    owners: dict[tuple[str, str], str] = {}
    for batch in _chunks(sorted(set(codes))):
        rows = await session.execute(_CODE_OWNERS, {"t": tenant_id, "keys": batch})
        owners.update({(kind.upper(), value): sku for kind, value, sku in rows.all() if sku})
    return owners


async def load_codes_by_sku(
    session: AsyncSession, tenant_id: uuid.UUID, skus: Iterable[str]
) -> dict[tuple[str, str], str]:
    """``(EGS|GS1, SKU) -> code`` for variants that already carry a code of that type."""
    held: dict[tuple[str, str], str] = {}
    for batch in _chunks(sorted(set(skus))):
        rows = await session.execute(_CODES_OF_SKUS, {"t": tenant_id, "keys": batch})
        held.update({(kind.upper(), sku): value for kind, sku, value in rows.all() if sku})
    return held
