"""Vision verification (spec §12.4) — live business truth per candidate.

A match is not a recommendation until the catalog agrees: the product must be
in a status checkout would sell, and the customer needs active variants that
actually have stock. Reads catalog/inventory cross-module with
parameter-bound ``sa.text()`` SQL (the customers/timeline read-model
precedent — a NEW cross-module import site would raise the boundary ratchet,
tests/test_module_boundaries.py), and the sellable vocabulary is read through
tools' existing orders.service import site so this verifier can never drift
from the checkout gate.

Returns business-level dicts only — SQL rows never leave this module.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.tools import sellable_product_statuses

# One round trip per verification batch: sellable status, then a per-variant
# stock rollup (all warehouses), then the count of active variants whose
# available (on_hand - reserved) is positive. A product with no variants
# verifies as sellable with zero available variants.
_VERIFICATION_SQL = sa.text(
    """
    SELECT p.id AS product_id,
           (p.status = ANY(:sellable)) AS sellable,
           COUNT(v.variant_id) FILTER (WHERE v.available > 0) AS available_variants
    FROM products p
    LEFT JOIN (
        SELECT v.id AS variant_id,
               v.product_id AS product_id,
               COALESCE(SUM(b.on_hand - b.reserved), 0) AS available
        FROM product_variants v
        LEFT JOIN inventory_balances b
            ON b.variant_id = v.id AND b.tenant_id = :tenant_id
        WHERE v.tenant_id = :tenant_id AND v.is_active
        GROUP BY v.id, v.product_id
    ) v ON v.product_id = p.id
    WHERE p.tenant_id = :tenant_id AND p.id = ANY(:product_ids)
    GROUP BY p.id, p.status
    """
)


async def verify_products(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    product_ids: list[uuid.UUID],
) -> dict[uuid.UUID, dict]:
    """Verify a batch of candidate products against the live catalog.

    Returns ``{product_id: {"verified": bool, "available_variants": int}}``
    — ``verified`` mirrors the sell gate (draft/archived never verify), and
    ``available_variants`` counts active variants with stock. Products that
    do not exist simply come back absent from the mapping.
    """
    if not product_ids:
        return {}
    rows = (
        await session.execute(
            _VERIFICATION_SQL,
            {
                "tenant_id": str(tenant_id),
                "sellable": sorted(sellable_product_statuses()),
                "product_ids": product_ids,
            },
        )
    ).all()
    return {
        row.product_id: {
            "verified": bool(row.sellable),
            "available_variants": int(row.available_variants),
        }
        for row in rows
    }
