"""CUSTOMERS domain service — identity resolution and CRM rules.

Every method takes the caller's session and tenant and NEVER commits: the
request/worker owns the transaction, the service owns the rules.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, or_, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.customers.models import (
    Customer,
    CustomerEvent,
    CustomerIdentity,
    Note,
    Tag,
    customer_tags,
)
from app.modules.errors import ConflictError, NotFoundError

_RESOLVE_ATTEMPTS = 2


def _now() -> datetime:
    return datetime.now(UTC)


class CustomerService:
    """All customer business rules; static methods taking (session, tenant_id)."""

    # ------------------------------------------------------------- lookup ----

    @staticmethod
    async def get(session: AsyncSession, tenant_id: UUID, customer_id: UUID) -> Customer:
        """Fetch a customer scoped to the tenant (NotFoundError otherwise)."""
        customer = (
            await session.execute(
                select(Customer).where(
                    Customer.id == customer_id,
                    Customer.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()
        if customer is None:
            raise NotFoundError(f"customer {customer_id} not found")
        return customer

    @staticmethod
    async def list_customers(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        search: str | None = None,
        limit: int = 50,
        offset: int = 0,
        before_created_at: datetime | None = None,
        before_id: UUID | None = None,
    ) -> list[Customer]:
        """Tenant-scoped listing with optional name/phone/email search.

        Pass before_created_at + before_id for stable keyset pages; the keyset
        path orders by (created_at, id) so cursors stay consistent.
        """
        stmt = select(Customer).where(Customer.tenant_id == tenant_id)
        if search:
            pattern = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    Customer.name.ilike(pattern),
                    Customer.phone.ilike(pattern),
                    Customer.email.ilike(pattern),
                )
            )
        if before_created_at is not None and before_id is not None:
            stmt = stmt.where(
                tuple_(Customer.created_at, Customer.id)
                < tuple_(before_created_at, before_id)
            )
            stmt = stmt.order_by(Customer.created_at.desc(), Customer.id.desc())
        else:
            stmt = stmt.order_by(Customer.created_at.desc(), Customer.name.asc())
        stmt = stmt.limit(limit).offset(offset)
        return list((await session.execute(stmt)).scalars().all())

    # ---------------------------------------------------------- identity ----

    @staticmethod
    async def get_or_create_by_identity(
        session: AsyncSession,
        tenant_id: UUID,
        channel: str,
        external_id: str,
        *,
        name: str | None = None,
        phone: str | None = None,
    ) -> Customer:
        """Resolve a channel handle to a customer, creating the cheapest match.

        1. an existing (tenant, channel, external_id) identity wins — the
           customer's last_seen_at is touched;
        2. else a customer holding the same phone adopts the new identity;
        3. else a fresh customer + identity pair is created.

        Retries once on unique violations so concurrent webhook deliveries
        converge on the same customer instead of failing.
        """
        for _attempt in range(_RESOLVE_ATTEMPTS):
            customer = await CustomerService._resolve_by_identity(
                session, tenant_id, channel, external_id
            )
            if customer is not None:
                CustomerService._touch(customer, name)
                return customer

            phone_customer = await CustomerService._resolve_by_phone(
                session, tenant_id, phone
            )
            if phone_customer is not None:
                try:
                    async with session.begin_nested():
                        session.add(
                            CustomerIdentity(
                                tenant_id=tenant_id,
                                customer_id=phone_customer.id,
                                channel=channel,
                                external_id=external_id,
                            )
                        )
                        await session.flush()
                except IntegrityError:
                    continue  # identity appeared concurrently — re-resolve
                CustomerService._touch(phone_customer, name)
                return phone_customer

            try:
                async with session.begin_nested():
                    customer = Customer(
                        tenant_id=tenant_id,
                        name=name or phone or "",
                        phone=phone,
                    )
                    session.add(customer)
                    await session.flush()
                    session.add(
                        CustomerIdentity(
                            tenant_id=tenant_id,
                            customer_id=customer.id,
                            channel=channel,
                            external_id=external_id,
                        )
                    )
                    await session.flush()
            except IntegrityError:
                continue  # phone/identity race — re-resolve
            return customer

        raise ConflictError(
            f"could not resolve identity {channel}:{external_id} after "
            f"{_RESOLVE_ATTEMPTS} attempts"
        )

    @staticmethod
    async def _resolve_by_identity(
        session: AsyncSession, tenant_id: UUID, channel: str, external_id: str
    ) -> Customer | None:
        identity = (
            await session.execute(
                select(CustomerIdentity).where(
                    CustomerIdentity.tenant_id == tenant_id,
                    CustomerIdentity.channel == channel,
                    CustomerIdentity.external_id == external_id,
                )
            )
        ).scalar_one_or_none()
        if identity is None:
            return None
        return await CustomerService.get(session, tenant_id, identity.customer_id)

    @staticmethod
    async def _resolve_by_phone(
        session: AsyncSession, tenant_id: UUID, phone: str | None
    ) -> Customer | None:
        if not phone:
            return None
        return (
            await session.execute(
                select(Customer).where(
                    Customer.tenant_id == tenant_id,
                    Customer.phone == phone,
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    def _touch(customer: Customer, name: str | None) -> None:
        """Mark the customer as seen; backfill a name only while it is empty."""
        customer.last_seen_at = _now()
        if name and not (customer.name or "").strip():
            customer.name = name

    # -------------------------------------------------------- tags/notes ----

    @staticmethod
    async def add_tag(
        session: AsyncSession, tenant_id: UUID, customer_id: UUID, tag_name: str
    ) -> Tag:
        """Link a tag to a customer; the tag row is created on first use."""
        await CustomerService.get(session, tenant_id, customer_id)
        tag_name = tag_name.strip()
        if not tag_name:
            raise ValueError("tag name must not be empty")

        tag = (
            await session.execute(
                select(Tag).where(Tag.tenant_id == tenant_id, Tag.name == tag_name)
            )
        ).scalar_one_or_none()
        if tag is None:
            # Race-safe create: another request may tag concurrently.
            await session.execute(
                pg_insert(Tag)
                .values(tenant_id=tenant_id, name=tag_name)
                .on_conflict_do_nothing(index_elements=["tenant_id", "name"])
            )
            tag = (
                await session.execute(
                    select(Tag).where(Tag.tenant_id == tenant_id, Tag.name == tag_name)
                )
            ).scalar_one()

        link = (
            await session.execute(
                select(customer_tags.c.tag_id).where(
                    customer_tags.c.customer_id == customer_id,
                    customer_tags.c.tag_id == tag.id,
                )
            )
        ).first()
        if link is None:
            await session.execute(
                customer_tags.insert().values(customer_id=customer_id, tag_id=tag.id)
            )
        return tag

    @staticmethod
    async def remove_tag(
        session: AsyncSession, tenant_id: UUID, customer_id: UUID, tag_name: str
    ) -> None:
        """Unlink a tag; a missing tag or link is a no-op."""
        await CustomerService.get(session, tenant_id, customer_id)
        await session.execute(
            delete(customer_tags).where(
                customer_tags.c.customer_id == customer_id,
                customer_tags.c.tag_id.in_(
                    select(Tag.id).where(
                        Tag.tenant_id == tenant_id, Tag.name == tag_name
                    )
                ),
            )
        )

    @staticmethod
    async def add_note(
        session: AsyncSession,
        tenant_id: UUID,
        customer_id: UUID,
        author_user_id: UUID | None,
        body: str,
    ) -> Note:
        await CustomerService.get(session, tenant_id, customer_id)
        note = Note(
            tenant_id=tenant_id,
            customer_id=customer_id,
            author_user_id=author_user_id,
            body=body,
        )
        session.add(note)
        await session.flush()
        return note

    @staticmethod
    async def record_event(
        session: AsyncSession,
        tenant_id: UUID,
        customer_id: UUID,
        event_type: str,
        payload: dict | None = None,
    ) -> CustomerEvent:
        """Append to the per-customer event log (channel messages, etc.)."""
        await CustomerService.get(session, tenant_id, customer_id)
        event = CustomerEvent(
            tenant_id=tenant_id,
            customer_id=customer_id,
            event_type=event_type,
            payload=payload or {},
        )
        session.add(event)
        await session.flush()
        return event


class IdentityMergeService:
    """Spec §27-28: resolve duplicate customers into one canonical record.

    Human-approved (AI only creates candidates). Preserves all history by
    remapping identities/conversations/orders/notes/tags/events/consents to
    the canonical customer, tombstones the loser with merged_into redirect,
    writes an IdentityMergeEvent + audit + customer.merged outbox event.
    """

    _REMAP_TABLES = [
        # (table, fk_column) — all tenant-scoped child tables of customers
        ("customer_identities", "customer_id"),
        ("addresses", "customer_id"),
        ("conversations", "customer_id"),
        ("orders", "customer_id"),
        ("notes", "customer_id"),
        ("customer_events", "customer_id"),
        ("leads", "customer_id"),
        ("consents", "customer_id"),
        ("touchpoints", "customer_id"),
        ("conversions", "customer_id"),
        ("memories", "customer_id"),
    ]

    @staticmethod
    async def merge(
        session,
        tenant_id,
        *,
        canonical_customer_id,
        merged_away_customer_id,
        performed_by_user_id=None,
        source: str = "human",
    ):
        from datetime import UTC, datetime

        from sqlalchemy import text

        from app.core.errors import ConflictError, NotFoundError
        from app.core.events.writer import add_outbox_event
        from app.modules.customers.models import IdentityMergeEvent
        from app.modules.platform.models import AuditLog

        if canonical_customer_id == merged_away_customer_id:
            raise ConflictError("cannot merge a customer into itself")

        canonical = (
            await session.execute(
                text(
                    "SELECT id FROM customers WHERE tenant_id = :t "
                    "AND id = :cid AND merged_into_customer_id IS NULL "
                    "AND deleted_at IS NULL FOR UPDATE"
                ),
                {"t": tenant_id, "cid": canonical_customer_id},
            )
        ).scalar_one_or_none()
        if canonical is None:
            raise NotFoundError("canonical customer not found")

        merged_away = (
            await session.execute(
                text(
                    "SELECT id FROM customers WHERE tenant_id = :t "
                    "AND id = :mid AND merged_into_customer_id IS NULL "
                    "AND deleted_at IS NULL FOR UPDATE"
                ),
                {"t": tenant_id, "cid": merged_away_customer_id},
            )
        ).scalar_one_or_none()
        if merged_away is None:
            raise NotFoundError("customer to merge away not found")

        # Remap every child table to the canonical customer.
        for table, fk in IdentityMergeService._REMAP_TABLES:
            await session.execute(
                text(
                    f"UPDATE {table} SET {fk} = :canonical "
                    f"WHERE tenant_id = :t AND {fk} = :away"
                ),
                {
                    "canonical": canonical_customer_id,
                    "t": tenant_id,
                    "mid": merged_away_customer_id,
                },
            )

        # Tombstone the merged-away customer with a redirect.
        await session.execute(
            text(
                "UPDATE customers SET merged_into_customer_id = :canonical, "
                "merged_at = :now, updated_at = now() "
                "WHERE tenant_id = :t AND id = :away"
            ),
            {
                "canonical": canonical_customer_id,
                "now": datetime.now(UTC),
                "t": tenant_id,
                "mid": merged_away_customer_id,
            },
        )

        # Consolidated lifetime value on the canonical record.
        await session.execute(
            text(
                "UPDATE customers c1 SET lifetime_value = c1.lifetime_value + c2.lifetime_value "
                "FROM customers c2 WHERE c1.id = :canonical AND c2.id = :mid"
            ),
            {"canonical": canonical_customer_id, "mid": merged_away_customer_id},
        )

        session.add(
            IdentityMergeEvent(
                tenant_id=tenant_id,
                canonical_customer_id=canonical_customer_id,
                merged_away_customer_id=merged_away_customer_id,
                performed_by_user_id=performed_by_user_id,
                source=source,
                details={},
            )
        )
        session.add(
            AuditLog(
                tenant_id=tenant_id,
                actor_user_id=performed_by_user_id,
                action="customer.merged",
                resource_type="customer",
                resource_id=str(canonical_customer_id),
                after={"merged_away": str(merged_away_customer_id), "source": source},
            )
        )
        await add_outbox_event(
            session,
            aggregate_type="customer",
            aggregate_id=canonical_customer_id,
            event_type="customer.merged",
            tenant_id=tenant_id,
            payload={
                "canonical_customer_id": str(canonical_customer_id),
                "merged_away_customer_id": str(merged_away_customer_id),
            },
        )
        await session.flush()
        return canonical_customer_id

    @staticmethod
    async def create_merge_candidate(
        session,
        tenant_id,
        *,
        customer_a_id,
        customer_b_id,
        match_type="ai_suggested",
        confidence=0.5,
        evidence=None,
    ):

        from app.modules.customers.models import IdentityMergeCandidate

        if customer_a_id == customer_b_id:
            raise ConflictError("candidate must be two different customers")
        candidate = IdentityMergeCandidate(
            tenant_id=tenant_id,
            customer_a_id=customer_a_id,
            customer_b_id=customer_b_id,
            match_type=match_type,
            confidence=confidence,
            evidence=evidence or {},
            status="pending",
        )
        session.add(candidate)
        await session.flush()
        return candidate

    @staticmethod
    async def resolve_merge_candidate(
        session,
        tenant_id,
        *,
        candidate_id,
        decision: str,  # merged | rejected | dismissed
        decided_by_user_id=None,
    ):
        from datetime import UTC, datetime

        from sqlalchemy import select

        from app.core.errors import ValidationError
        from app.modules.customers.models import IdentityMergeCandidate

        candidate = (
            await session.execute(
                select(IdentityMergeCandidate).where(
                    IdentityMergeCandidate.tenant_id == tenant_id,
                    IdentityMergeCandidate.id == candidate_id,
                )
            )
        ).scalar_one_or_none()
        if candidate is None:
            raise NotFoundError("merge candidate not found")
        if decision not in ("merged", "rejected", "dismissed"):
            raise ValidationError(f"invalid decision: {decision}")

        if decision == "merged":
            # Deterministic side wins as canonical unless AI flagged otherwise.
            canonical, away = candidate.customer_a_id, candidate.customer_b_id
            await IdentityMergeService.merge(
                session,
                tenant_id,
                canonical_customer_id=canonical,
                merged_away_customer_id=away,
                performed_by_user_id=decided_by_user_id,
                source="candidate",
            )

        candidate.status = decision
        candidate.decided_by_user_id = decided_by_user_id
        candidate.decided_at = datetime.now(UTC)
        await session.flush()
        return candidate
