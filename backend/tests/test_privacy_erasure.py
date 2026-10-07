"""§172 erasure reaches the subject it was asked about (M2 fallout).

``CustomerService.get`` refuses dead rows since M2 — correct for every caller
that trades with a customer, wrong for the eraser: a merged-away or already
tombstoned row is precisely the row a data-subject request is about.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customers.models import Customer
from app.modules.customers.service import CustomerService, IdentityMergeService
from app.modules.identity.deps import TenantContext
from app.modules.privacy.service import DeletionService


async def _two_customers(db: AsyncSession, tenant_id: uuid.UUID):
    a = await CustomerService.get_or_create_by_identity(
        db, tenant_id, channel="whatsapp", external_id="e-1", name="Subject A"
    )
    b = await CustomerService.get_or_create_by_identity(
        db, tenant_id, channel="whatsapp", external_id="e-2", name="Subject B"
    )
    return a, b


async def test_a_merged_away_subject_is_still_erased(
    db: AsyncSession, tenant_ctx: TenantContext
) -> None:
    """The merge redirect must not park an erasure request open forever."""
    a, b = await _two_customers(db, tenant_ctx.tenant_id)
    await IdentityMergeService.merge(
        db,
        tenant_ctx.tenant_id,
        canonical_customer_id=a.id,
        merged_away_customer_id=b.id,
        performed_by_user_id=tenant_ctx.user.id,
    )

    report = await DeletionService.propagate_customer_deletion(
        db, tenant_ctx.tenant_id, b.id, reason="data_subject_request"
    )

    steps = {step["step"] for step in report["steps"]}
    assert "domain_tombstone" in steps
    # Reading the column directly: the row is dead on purpose, so no accessor
    # in this test may be the thing that decides whether the erase happened.
    tombstoned = await db.scalar(select(Customer.deleted_at).where(Customer.id == b.id))
    assert tombstoned is not None


async def test_erasing_a_live_subject_still_works(
    db: AsyncSession, tenant_ctx: TenantContext
) -> None:
    _a, b = await _two_customers(db, tenant_ctx.tenant_id)
    report = await DeletionService.propagate_customer_deletion(
        db, tenant_ctx.tenant_id, b.id, reason="data_subject_request"
    )
    assert {"domain_tombstone", "memories_deleted"} <= {step["step"] for step in report["steps"]}
