"""MARKETING domain service — campaigns, touchpoint capture, conversion
attribution, leads.

Rules owned here:
- Enum-like values (campaign provider, conversion type, lead status) are
  validated in the service, never at the DB.
- ``record_conversion`` runs first/last-touch attribution: every conversion is
  credited to both the earliest and the latest touchpoint of its customer that
  happened before the conversion (weight 1.0 each, credited_value = value).
  A conversion with no touchpoints stands alone.
- Touchpoints get a client-side ``created_at`` on insert: ``now()`` as a
  server default is transaction-scoped in Postgres, so touchpoints captured in
  the same transaction (backfills, lead forms) would otherwise tie and make
  first/last attribution ambiguous.
- Every method takes (session, tenant_id) and NEVER commits — the caller owns
  the transaction (``await session.flush()`` only).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.modules.marketing.models import Attribution, Campaign, Conversion, Lead, Touchpoint

_ALLOWED_PROVIDERS = {"facebook", "google", "tiktok", "snapchat", "manual"}
_ALLOWED_CONVERSION_TYPES = {"purchase", "signup", "lead", "custom"}
_ALLOWED_LEAD_STATUSES = {"new", "contacted", "qualified", "converted", "lost"}


def _now() -> datetime:
    return datetime.now(UTC)


class MarketingService:
    """All marketing business rules; static methods taking (session, tenant_id)."""

    # -------------------------------------------------------- campaigns ----

    @staticmethod
    async def create_campaign(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        name: str,
        provider: str = "manual",
        external_id: str | None = None,
        objective: str | None = None,
        budget: float | None = None,
    ) -> Campaign:
        if provider not in _ALLOWED_PROVIDERS:
            raise ValidationError(
                f"provider must be one of {sorted(_ALLOWED_PROVIDERS)}",
                details={"provider": provider},
            )
        campaign = Campaign(
            tenant_id=tenant_id,
            name=name,
            provider=provider,
            external_id=external_id,
            objective=objective,
            budget=budget,
        )
        session.add(campaign)
        await session.flush()
        return campaign

    @staticmethod
    async def get_campaign(
        session: AsyncSession, tenant_id: UUID, campaign_id: UUID
    ) -> Campaign:
        campaign = (
            await session.execute(
                select(Campaign).where(
                    Campaign.id == campaign_id, Campaign.tenant_id == tenant_id
                )
            )
        ).scalar_one_or_none()
        if campaign is None:
            raise NotFoundError(f"campaign {campaign_id} not found")
        return campaign

    @staticmethod
    async def list_campaigns(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Campaign]:
        stmt = (
            select(Campaign)
            .where(Campaign.tenant_id == tenant_id)
            .order_by(Campaign.created_at.desc(), Campaign.id.desc())
            .limit(limit)
            .offset(offset)
        )
        if status is not None:
            stmt = stmt.where(Campaign.status == status)
        return list((await session.execute(stmt)).scalars().all())

    # ------------------------------------------------------ touchpoints ----

    @staticmethod
    async def record_touchpoint(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        customer_id: UUID | None = None,
        source: str | None = None,
        medium: str | None = None,
        campaign_id: UUID | None = None,
        ad_set_id: UUID | None = None,
        ad_id: UUID | None = None,
        click_id: str | None = None,
        landing_url: str | None = None,
        session_key: str | None = None,
    ) -> Touchpoint:
        """Capture one marketing contact point (ad click / UTM visit)."""
        touchpoint = Touchpoint(
            tenant_id=tenant_id,
            customer_id=customer_id,
            source=source,
            medium=medium,
            campaign_id=campaign_id,
            ad_set_id=ad_set_id,
            ad_id=ad_id,
            click_id=click_id,
            landing_url=landing_url,
            session_key=session_key,
            # Client-side clock so touchpoints captured within one transaction
            # still order deterministically for first/last attribution.
            created_at=_now(),
        )
        session.add(touchpoint)
        await session.flush()
        return touchpoint

    # ------------------------------------------------------ conversions ----

    @staticmethod
    async def record_conversion(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        customer_id: UUID | None = None,
        order_id: UUID | None = None,
        type: str = "purchase",  # noqa: A002 - API parity with the model column
        value: float | None = None,
        currency: str = "EGP",
        occurred_at: datetime | None = None,
    ) -> Conversion:
        if type not in _ALLOWED_CONVERSION_TYPES:
            raise ValidationError(
                f"type must be one of {sorted(_ALLOWED_CONVERSION_TYPES)}",
                details={"type": type},
            )
        conversion = Conversion(
            tenant_id=tenant_id,
            customer_id=customer_id,
            order_id=order_id,
            type=type,
            value=value,
            currency=currency,
            occurred_at=occurred_at or _now(),
        )
        session.add(conversion)
        await session.flush()
        await MarketingService._attribute(session, tenant_id, conversion)
        return conversion

    @staticmethod
    async def _attribute(
        session: AsyncSession, tenant_id: UUID, conversion: Conversion
    ) -> list[Attribution]:
        """First-touch + last-touch attribution for one conversion.

        Uses the customer's touchpoints that happened before the conversion,
        ordered by created_at (earliest = first touch, latest = last touch).
        Each gets weight 1.0 and credited_value = conversion.value. Without a
        customer or touchpoints, no attribution rows are created.
        """
        if conversion.customer_id is None:
            return []

        occurred_at = conversion.occurred_at or _now()
        touchpoints: list[Touchpoint] = list(
            (
                await session.execute(
                    select(Touchpoint)
                    .where(
                        Touchpoint.tenant_id == tenant_id,
                        Touchpoint.customer_id == conversion.customer_id,
                        Touchpoint.created_at <= occurred_at,
                    )
                    .order_by(Touchpoint.created_at.asc(), Touchpoint.id.asc())
                )
            )
            .scalars()
            .all()
        )
        if not touchpoints:
            return []

        credited = float(conversion.value) if conversion.value is not None else None
        rows = [
            Attribution(
                tenant_id=tenant_id,
                conversion_id=conversion.id,
                touchpoint_id=touchpoints[0].id,  # earliest
                model="first_touch",
                weight=1.0,
                credited_value=credited,
            ),
            Attribution(
                tenant_id=tenant_id,
                conversion_id=conversion.id,
                touchpoint_id=touchpoints[-1].id,  # latest
                model="last_touch",
                weight=1.0,
                credited_value=credited,
            ),
        ]
        session.add_all(rows)
        await session.flush()
        return rows

    # ------------------------------------------------------------ leads ----

    @staticmethod
    async def create_lead(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        name: str | None = None,
        phone: str | None = None,
        email: str | None = None,
        source: str | None = None,
        campaign_id: UUID | None = None,
    ) -> Lead:
        lead = Lead(
            tenant_id=tenant_id,
            name=name,
            phone=phone,
            email=email,
            source=source,
            status="new",
            campaign_id=campaign_id,
        )
        session.add(lead)
        await session.flush()
        return lead

    @staticmethod
    async def update_lead_status(
        session: AsyncSession, tenant_id: UUID, lead_id: UUID, status: str
    ) -> Lead:
        if status not in _ALLOWED_LEAD_STATUSES:
            raise ValidationError(
                f"status must be one of {sorted(_ALLOWED_LEAD_STATUSES)}",
                details={"status": status},
            )
        lead = (
            await session.execute(
                select(Lead).where(Lead.id == lead_id, Lead.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        if lead is None:
            raise NotFoundError(f"lead {lead_id} not found")
        lead.status = status
        await session.flush()
        return lead
