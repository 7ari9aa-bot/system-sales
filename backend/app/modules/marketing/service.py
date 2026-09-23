"""MARKETING domain service — campaigns, touchpoint capture, conversion
attribution, leads.

Rules owned here:
- Enum-like values (campaign provider, conversion type, lead status) are
  validated in the service, never at the DB.
- ``record_conversion`` is deduped by the database on
  ``(tenant_id, order_id, type)``: an order converts once per type. A replayed
  event raises ``ConflictError`` (a 409 at the edge); pass ``idempotent=True`` to
  get the already-recorded conversion back instead.
- ``_attribute`` writes first-touch AND last-touch, each crediting the full
  conversion value. Those are two VIEWS of one order, not twice its worth: every
  money rollup filters on a single model (analytics quotes ``last_touch``), and
  ``AttributionService.attribution_report`` is the only sanctioned way to present
  more than one model.
- Touchpoints get a client-side ``created_at`` on insert: ``now()`` as a
  server default is transaction-scoped in Postgres, so touchpoints captured in
  the same transaction (backfills, lead forms) would otherwise tie and make
  first/last attribution ambiguous.
- Every method takes (session, tenant_id) and NEVER commits — the caller owns
  the transaction (``await session.flush()`` only).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationError
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
        before_created_at: datetime | None = None,
        before_id: UUID | None = None,
    ) -> list[Campaign]:
        """Keyset-aware listing: pass before_created_at + before_id to page."""
        stmt = select(Campaign).where(Campaign.tenant_id == tenant_id)
        if status is not None:
            stmt = stmt.where(Campaign.status == status)
        if before_created_at is not None and before_id is not None:
            stmt = stmt.where(
                tuple_(Campaign.created_at, Campaign.id)
                < tuple_(before_created_at, before_id)
            )
        stmt = (
            stmt.order_by(Campaign.created_at.desc(), Campaign.id.desc())
            .limit(limit)
            .offset(offset)
        )
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
        value: Decimal | float | None = None,
        currency: str | None = None,
        occurred_at: datetime | None = None,
        idempotent: bool = False,
    ) -> Conversion:
        """Record one conversion; the DB decides whether it is a new one.

        ``(tenant_id, order_id, type)`` is unique, so a replayed order event
        cannot double-count. Default is a refusal (``ConflictError`` -> 409);
        a caller that retries on purpose passes ``idempotent=True`` and gets the
        row that already exists.
        """
        if type not in _ALLOWED_CONVERSION_TYPES:
            raise ValidationError(
                f"type must be one of {sorted(_ALLOWED_CONVERSION_TYPES)}",
                details={"type": type},
            )
        # §47: ROAS divides conversions by ad spend, so the money column has to
        # say what it is denominated in. The tenant trades in one currency, and
        # a conversion recorded against its orders is in that currency.
        from app.core.tenancy import resolve_tenant_currency

        if order_id is not None and idempotent:
            existing = await MarketingService._find_conversion(
                session, tenant_id, order_id=order_id, type=type
            )
            if existing is not None:
                return existing

        conversion = Conversion(
            tenant_id=tenant_id,
            customer_id=customer_id,
            order_id=order_id,
            type=type,
            value=value,
            currency=(currency or await resolve_tenant_currency(session, tenant_id)).upper(),
            occurred_at=occurred_at or _now(),
        )
        try:
            async with session.begin_nested():
                session.add(conversion)
                await session.flush()
        except IntegrityError:
            # The unique key on (tenant, order, type) fired: either a replay this
            # caller should have marked idempotent, or a genuine double-count.
            existing = (
                await MarketingService._find_conversion(
                    session, tenant_id, order_id=order_id, type=type
                )
                if order_id is not None
                else None
            )
            if existing is not None and idempotent:
                return existing
            raise ConflictError(
                f"conversion already recorded for order {order_id} ({type})",
                details={"order_id": str(order_id), "type": type},
            ) from None
        await MarketingService._attribute(session, tenant_id, conversion)
        return conversion

    @staticmethod
    async def _find_conversion(
        session: AsyncSession, tenant_id: UUID, *, order_id: UUID, type: str
    ) -> Conversion | None:
        return (
            await session.execute(
                select(Conversion).where(
                    Conversion.tenant_id == tenant_id,
                    Conversion.order_id == order_id,
                    Conversion.type == type,
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def list_campaign_conversions(
        session: AsyncSession,
        tenant_id: UUID,
        campaign_id: UUID,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[tuple[Conversion, list[str]]]:
        """Conversions this campaign touched, with the models that credit it.

        Reachability only — a campaign is credited through its touchpoints, so
        the walk is conversion -> attribution -> touchpoint -> campaign.
        ``attribution_models`` names WHICH view credits it, because the models
        are alternative views and listing them together is not a sum.
        """
        await MarketingService.get_campaign(session, tenant_id, campaign_id)

        conversions = list(
            (
                await session.execute(
                    select(Conversion)
                    .join(Attribution, Attribution.conversion_id == Conversion.id)
                    .join(Touchpoint, Touchpoint.id == Attribution.touchpoint_id)
                    .where(
                        Conversion.tenant_id == tenant_id,
                        Attribution.tenant_id == tenant_id,
                        Touchpoint.tenant_id == tenant_id,
                        Touchpoint.campaign_id == campaign_id,
                    )
                    .distinct()
                    .order_by(Conversion.created_at.desc(), Conversion.id.desc())
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        if not conversions:
            return []

        credit_rows = (
            await session.execute(
                select(Attribution.conversion_id, Attribution.model)
                .join(Touchpoint, Touchpoint.id == Attribution.touchpoint_id)
                .where(
                    Attribution.tenant_id == tenant_id,
                    Touchpoint.tenant_id == tenant_id,
                    Touchpoint.campaign_id == campaign_id,
                    Attribution.conversion_id.in_([c.id for c in conversions]),
                )
                .distinct()
            )
        ).all()
        models_by_conversion: dict[UUID, list[str]] = {}
        for conversion_id, model in credit_rows:
            models_by_conversion.setdefault(conversion_id, []).append(model)

        return [
            (c, sorted(models_by_conversion.get(c.id, []))) for c in conversions
        ]

    @staticmethod
    async def _attribute(
        session: AsyncSession, tenant_id: UUID, conversion: Conversion
    ) -> list[Attribution]:
        """First-touch + last-touch attribution for one conversion.

        Uses the customer's touchpoints that happened before the conversion,
        ordered by created_at (earliest = first touch, latest = last touch).
        Each gets weight 1.0 and credited_value = conversion.value, i.e. TWO
        VIEWS OF THE SAME MONEY — a reader filters to one model, it never adds
        the two. Without a customer or touchpoints, no attribution rows are
        created.
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

        # Decimal, not float: this is the money figure every ROAS/revenue number
        # downstream divides by.
        credited = None if conversion.value is None else Decimal(str(conversion.value))
        rows = [
            Attribution(
                tenant_id=tenant_id,
                conversion_id=conversion.id,
                touchpoint_id=touchpoints[0].id,  # earliest
                model="first_touch",
                weight=Decimal("1"),
                credited_value=credited,
            ),
            Attribution(
                tenant_id=tenant_id,
                conversion_id=conversion.id,
                touchpoint_id=touchpoints[-1].id,  # latest
                model="last_touch",
                weight=Decimal("1"),
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
