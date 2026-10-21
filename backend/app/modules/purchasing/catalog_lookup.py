"""The one catalog fact purchasing needs: which of these variant ids exist for the tenant.

Kept out of `service.py` because the architecture guard forbids a domain service from importing
another module's models, even inside a function. The import stays function-scope so purchasing
does not gain a module-load edge to catalog.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def existing_variant_ids(
    session: AsyncSession, tenant_id: UUID, variant_ids: Iterable[UUID]
) -> set[UUID]:
    from app.modules.catalog.models import ProductVariant

    wanted = set(variant_ids)
    if not wanted:
        return set()
    rows = await session.execute(
        select(ProductVariant.id).where(
            ProductVariant.tenant_id == tenant_id, ProductVariant.id.in_(wanted)
        )
    )
    return set(rows.scalars())
