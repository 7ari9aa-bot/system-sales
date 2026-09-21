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
    Address,
    Customer,
    CustomerEvent,
    CustomerIdentity,
    Note,
    Tag,
    customer_tags,
)
from app.modules.errors import ConflictError, NotFoundError, ValidationError

_RESOLVE_ATTEMPTS = 2


# ---------------------------------------------------------------------------
# §27-29 — E.164 phone normalization for identity resolution
# ---------------------------------------------------------------------------
# Customer identity resolution used to be exact-string: a customer with
# phone "+9647701234567" would NOT match a message from "07701234567" or
# "0770 123 4567". The §27-29 spec requires E.164 normalization so that
# the same human is resolved regardless of how the phone was entered.
#
# E.164 format: a leading "+" followed by 8-15 digits, no spaces, no
# dashes, no leading zeros beyond the country code. This function does a
# best-effort normalization — it strips formatting and adds a default
# country code if the number is a local format (no "+" prefix).
#
# The spec notes this is NOT a full phone parsing library — it is a
# normalization that handles the 90% case. Unknown formats fall through
# to exact-string matching (the old behavior), so no existing resolution
# breaks.

# Default country code for local numbers without a "+" prefix. Set to
# Iraq (964) as the deployment default; a per-tenant override would be a
# future task (§27 mentions this as a tenant configuration field).
_DEFAULT_COUNTRY_CODE = "964"


def normalize_phone_e164(raw: str | None) -> str | None:
    """Normalize a phone string to E.164.

    Returns None if the input is empty/None.
    Returns the normalized E.164 string if the input is parseable.
    Returns the original string (stripped) if it cannot be normalized —
    so the caller falls through to exact-string matching.

    Examples:
        "+9647701234567"  -> "+9647701234567"
        "07701234567"     -> "+9647701234567"  (default country code)
        "0770 123 4567"   -> "+9647701234567"  (spaces stripped)
        "+964 770 123 4567" -> "+9647701234567"
        "abc"             -> "abc"            (unparseable, passthrough)
    """
    if not raw or not raw.strip():
        return None

    # Strip whitespace, dashes, dots, parentheses
    stripped = raw.strip()
    cleaned = stripped.replace(" ", "").replace("-", "").replace(".", "").replace("(", "").replace(")", "")

    if not cleaned:
        return None

    # Already in E.164 format: "+" + digits only
    if cleaned.startswith("+"):
        digits = cleaned[1:]
        if digits.isdigit() and 8 <= len(digits) <= 15:
            return f"+{digits}"
        return stripped  # unparseable — passthrough

    # Local format: add default country code
    if cleaned.isdigit():
        # Strip leading 0 (trunk prefix) if present
        if cleaned.startswith("0"):
            cleaned = cleaned[1:]
        if 7 <= len(cleaned) <= 14:
            return f"+{_DEFAULT_COUNTRY_CODE}{cleaned}"

    return stripped  # unparseable — passthrough


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
    async def get_name_phone_map(
        session: AsyncSession, tenant_id: UUID, customer_ids: list[UUID]
    ) -> dict[UUID, tuple[str | None, str | None]]:
        """Batch-fetch customer name+phone — for cross-module read models (§8/§137).

        Returns dict keyed by customer_id with (name, phone) tuples.
        """
        if not customer_ids:
            return {}
        rows = (
            await session.execute(
                select(Customer.id, Customer.name, Customer.phone).where(
                    Customer.tenant_id == tenant_id,
                    Customer.id.in_(customer_ids),
                )
            )
        ).all()
        return {row[0]: (row[1], row[2]) for row in rows}

    @staticmethod
    async def list_customers(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        search: str | None = None,
        tag: str | None = None,
        limit: int = 50,
        offset: int = 0,
        before_created_at: datetime | None = None,
        before_id: UUID | None = None,
    ) -> list[Customer]:
        """Tenant-scoped listing with optional name/phone/email search.

        Tombstoned (soft-deleted) customers are always excluded. ``tag``
        narrows to customers carrying that tag. Pass before_created_at +
        before_id for stable keyset pages; the keyset path orders by
        (created_at, id) so cursors stay consistent.
        """
        stmt = select(Customer).where(
            Customer.tenant_id == tenant_id,
            Customer.deleted_at.is_(None),
        )
        if search:
            pattern = f"%{search.strip()}%"
            stmt = stmt.where(
                or_(
                    Customer.name.ilike(pattern),
                    Customer.phone.ilike(pattern),
                    Customer.email.ilike(pattern),
                )
            )
        if tag:
            stmt = stmt.where(
                select(customer_tags.c.customer_id)
                .join(Tag, Tag.id == customer_tags.c.tag_id)
                .where(
                    customer_tags.c.customer_id == Customer.id,
                    Tag.tenant_id == tenant_id,
                    Tag.name == tag,
                )
                .exists()
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

    # ------------------------------------------------------------- crud ----

    @staticmethod
    async def update_customer(
        session: AsyncSession, tenant_id: UUID, customer_id: UUID, **fields: object
    ) -> Customer:
        """Partial update; unknown fields and a taken phone are rejected."""
        allowed = {"name", "phone", "email", "locale", "extra"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValidationError(f"unknown customer fields: {sorted(unknown)}")
        if "name" in fields and fields["name"] is None:
            raise ValidationError("name must not be null")

        customer = await CustomerService.get(session, tenant_id, customer_id)
        if customer.deleted_at is not None:
            raise ConflictError("customer is archived")

        new_phone = fields.get("phone")
        if new_phone is not None and new_phone != customer.phone:
            duplicate = (
                await session.execute(
                    select(Customer.id).where(
                        Customer.tenant_id == tenant_id,
                        Customer.phone == new_phone,
                        Customer.id != customer_id,
                        Customer.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if duplicate is not None:
                raise ConflictError(f"customer phone '{new_phone}' already exists")

        for key, value in fields.items():
            setattr(customer, key, value)
        await session.flush()
        return customer

    @staticmethod
    async def set_blocked(
        session: AsyncSession, tenant_id: UUID, customer_id: UUID, *, blocked: bool
    ) -> Customer:
        """Toggle the ``is_blocked`` flag (blocked customers cannot transact)."""
        customer = await CustomerService.get(session, tenant_id, customer_id)
        if customer.deleted_at is not None:
            raise ConflictError("customer is archived")
        customer.is_blocked = blocked
        await session.flush()
        return customer

    @staticmethod
    async def archive(
        session: AsyncSession,
        tenant_id: UUID,
        customer_id: UUID,
        *,
        deleted_by: UUID | None = None,
        reason: str | None = None,
    ) -> Customer:
        """Soft-delete via the §143 tombstone columns (never a hard delete)."""
        customer = await CustomerService.get(session, tenant_id, customer_id)
        if customer.deleted_at is not None:
            raise ConflictError("customer already archived")
        customer.deleted_at = _now()
        customer.deleted_by = deleted_by
        customer.deletion_reason = reason
        await session.flush()
        return customer

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
                        phone=normalize_phone_e164(phone) or phone,
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
        # §27-29: normalize to E.164 before matching so "+9647701234567"
        # and "07701234567" resolve to the same customer. If the phone
        # is unparseable, the normalizer returns the original string, so
        # the query falls through to exact-string match (the old behavior).
        normalized = normalize_phone_e164(phone)
        if normalized is None:
            return None
        # Try the normalized form first, then the original as fallback
        # (in case the stored value was not normalized).
        for candidate in (normalized, phone):
            result = (
                await session.execute(
                    select(Customer).where(
                        Customer.tenant_id == tenant_id,
                        Customer.phone == candidate,
                    )
                )
            ).scalar_one_or_none()
            if result is not None:
                return result
        return None

    @staticmethod
    def _touch(customer: Customer, name: str | None) -> None:
        """Mark the customer as seen; backfill a name only while it is empty."""
        customer.last_seen_at = _now()
        if name and not (customer.name or "").strip():
            customer.name = name

    # -------------------------------------------------------- tags/notes ----

    @staticmethod
    async def list_tags(
        session: AsyncSession, tenant_id: UUID, customer_id: UUID
    ) -> list[Tag]:
        """Tags currently linked to a customer (empty when none)."""
        await CustomerService.get(session, tenant_id, customer_id)
        rows = (
            await session.execute(
                select(Tag)
                .join(customer_tags, customer_tags.c.tag_id == Tag.id)
                .where(
                    customer_tags.c.customer_id == customer_id,
                    Tag.tenant_id == tenant_id,
                )
                .order_by(Tag.name.asc())
            )
        ).scalars().all()
        return list(rows)

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
    async def list_notes(
        session: AsyncSession, tenant_id: UUID, customer_id: UUID
    ) -> list[Note]:
        """Notes for a customer, newest first."""
        await CustomerService.get(session, tenant_id, customer_id)
        rows = (
            await session.execute(
                select(Note)
                .where(
                    Note.tenant_id == tenant_id,
                    Note.customer_id == customer_id,
                )
                .order_by(Note.created_at.desc())
            )
        ).scalars().all()
        return list(rows)

    @staticmethod
    async def list_identities(
        session: AsyncSession, tenant_id: UUID, customer_id: UUID
    ) -> list[CustomerIdentity]:
        """Channel handles mapped to a customer."""
        await CustomerService.get(session, tenant_id, customer_id)
        rows = (
            await session.execute(
                select(CustomerIdentity)
                .where(
                    CustomerIdentity.tenant_id == tenant_id,
                    CustomerIdentity.customer_id == customer_id,
                )
                .order_by(CustomerIdentity.created_at.asc())
            )
        ).scalars().all()
        return list(rows)

    @staticmethod
    async def list_addresses(
        session: AsyncSession, tenant_id: UUID, customer_id: UUID
    ) -> list[Address]:
        """Delivery addresses on file for a customer."""
        await CustomerService.get(session, tenant_id, customer_id)
        rows = (
            await session.execute(
                select(Address)
                .where(
                    Address.tenant_id == tenant_id,
                    Address.customer_id == customer_id,
                )
                .order_by(Address.created_at.asc())
            )
        ).scalars().all()
        return list(rows)

    @staticmethod
    async def list_events(
        session: AsyncSession,
        tenant_id: UUID,
        customer_id: UUID,
        *,
        limit: int = 100,
        event_types: list[str] | None = None,
    ) -> list[CustomerEvent]:
        """Read the per-customer event log, newest first (Customer 360 timeline).

        `record_event` has always written here but nothing ever read it back —
        the timeline was write-only. Raises NotFoundError for an unknown
        customer so a 360 request cannot silently return an empty history.
        """
        await CustomerService.get(session, tenant_id, customer_id)
        stmt = select(CustomerEvent).where(
            CustomerEvent.tenant_id == tenant_id,
            CustomerEvent.customer_id == customer_id,
        )
        if event_types:
            stmt = stmt.where(CustomerEvent.event_type.in_(event_types))
        rows = (
            await session.execute(
                stmt.order_by(
                    CustomerEvent.created_at.desc(), CustomerEvent.id.desc()
                ).limit(limit)
            )
        ).scalars().all()
        return list(rows)

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
    async def _merge_open_conversations(
        session, tenant_id, canonical_customer_id, merged_away_customer_id
    ) -> None:
        """Resolve open-conversation conflicts BEFORE the generic FK remap.

        The partial unique index uq_conversations_open_tenant_customer_channel
        (tenant, customer, channel WHERE status <> 'closed') forbids two open
        conversations for one customer on one channel. A blind remap of
        conversations.customer_id violates it whenever both customers already
        talk to us on the same channel. Open conflicts are folded here: the
        merged conversation's messages move into the canonical conversation and
        the merged conversation is closed, after which the generic remap can
        re-point it safely.
        """
        from sqlalchemy import text

        merged_open = (
            await session.execute(
                text(
                    "SELECT id, channel FROM conversations "
                    "WHERE tenant_id = :t AND customer_id = :mid AND status <> 'closed' "
                    "FOR UPDATE"
                ),
                {"t": tenant_id, "mid": merged_away_customer_id},
            )
        ).mappings().all()

        for row in merged_open:
            canonical_open = (
                await session.execute(
                    text(
                        "SELECT id FROM conversations "
                        "WHERE tenant_id = :t AND customer_id = :canonical "
                        "AND channel = :channel AND status <> 'closed' "
                        "LIMIT 1"
                    ),
                    {
                        "t": tenant_id,
                        "canonical": canonical_customer_id,
                        "channel": row["channel"],
                    },
                )
            ).scalar_one_or_none()

            if canonical_open is None:
                # No conflict: re-point now so the conversation stays open
                # under the canonical customer.
                await session.execute(
                    text(
                        "UPDATE conversations SET customer_id = :canonical "
                        "WHERE tenant_id = :t AND id = :cid"
                    ),
                    {
                        "t": tenant_id,
                        "canonical": canonical_customer_id,
                        "cid": row["id"],
                    },
                )
                continue

            # Both customers had an open conversation on this channel: fold the
            # merged one into the canonical one, then close the merged one
            # (mirrors ConversationService.close: status + unread_count reset).
            await session.execute(
                text(
                    "UPDATE messages SET conversation_id = :canonical_conv "
                    "WHERE tenant_id = :t AND conversation_id = :merged_conv"
                ),
                {
                    "t": tenant_id,
                    "canonical_conv": canonical_open,
                    "merged_conv": row["id"],
                },
            )
            await session.execute(
                text(
                    "UPDATE conversations SET status = 'closed', unread_count = 0 "
                    "WHERE tenant_id = :t AND id = :cid"
                ),
                {"t": tenant_id, "cid": row["id"]},
            )

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
        from app.modules.platform.service import AuditService

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
                {"t": tenant_id, "mid": merged_away_customer_id},
            )
        ).scalar_one_or_none()
        if merged_away is None:
            raise NotFoundError("customer to merge away not found")

        # Merge open conversations FIRST: the generic remap below is a blind
        # UPDATE of conversations.customer_id, which violates the partial
        # unique index uq_conversations_open_tenant_customer_channel whenever
        # both customers already have an open conversation on the same
        # channel. Fold those conflicts here, then the remap is safe.
        await IdentityMergeService._merge_open_conversations(
            session, tenant_id, canonical_customer_id, merged_away_customer_id
        )

        # Remap every child table to the canonical customer.
        for table, fk in IdentityMergeService._REMAP_TABLES:
            await session.execute(
                text(
                    f"UPDATE {table} SET {fk} = :canonical "
                    f"WHERE tenant_id = :t AND {fk} = :mid"
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
                "WHERE tenant_id = :t AND id = :mid"
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
        await AuditService.write(
            session,
            tenant_id,
            performed_by_user_id,
            action="customer.merged",
            resource_type="customer",
            resource_id=str(canonical_customer_id),
            after={"merged_away": str(merged_away_customer_id), "source": source},
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
            aggregate_version=2,
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


# ------------------------------------------- §137 read models ----

class Customer360Query:
    """§137: read-optimized Customer 360 view.

    A single get_360() call assembles the customer's 360° profile using
    raw SQL (not full ORM loads) so the dashboard drawer fetches everything
    in one round-trip without hydrating relationships.
    """

    @staticmethod
    async def get_360(
        session: AsyncSession, tenant_id: UUID, customer_id: UUID
    ) -> dict:
        """Return a dict with customer info, recent orders, conversations,
        lifetime_value, and memories — all read-optimized."""
        from sqlalchemy import text

        customer_row = (
            await session.execute(
                text(
                    "SELECT id, name, phone, email, is_blocked, "
                    "lifetime_value, created_at, updated_at "
                    "FROM customers "
                    "WHERE tenant_id = :t AND id = :cid AND deleted_at IS NULL"
                ),
                {"t": str(tenant_id), "cid": str(customer_id)},
            )
        ).one_or_none()
        if customer_row is None:
            raise NotFoundError(f"customer {customer_id} not found")
        customer_info = dict(customer_row._mapping)

        order_rows = (
            await session.execute(
                text(
                    "SELECT id, number, status, grand_total, currency, "
                    "placed_at, created_at "
                    "FROM orders "
                    "WHERE tenant_id = :t AND customer_id = :cid "
                    "ORDER BY created_at DESC LIMIT 10"
                ),
                {"t": str(tenant_id), "cid": str(customer_id)},
            )
        ).all()
        recent_orders = [dict(r._mapping) for r in order_rows]

        conv_rows = (
            await session.execute(
                text(
                    "SELECT id, channel, status, unread_count, created_at "
                    "FROM conversations "
                    "WHERE tenant_id = :t AND customer_id = :cid "
                    "ORDER BY created_at DESC LIMIT 5"
                ),
                {"t": str(tenant_id), "cid": str(customer_id)},
            )
        ).all()
        recent_conversations = [dict(r._mapping) for r in conv_rows]

        mem_rows = (
            await session.execute(
                text(
                    "SELECT id, kind, content, source, confidence, created_at "
                    "FROM memories "
                    "WHERE tenant_id = :t AND customer_id = :cid "
                    "ORDER BY created_at DESC LIMIT 5"
                ),
                {"t": str(tenant_id), "cid": str(customer_id)},
            )
        ).all()
        memories = [dict(r._mapping) for r in mem_rows]

        return {
            "customer": customer_info,
            "recent_orders": recent_orders,
            "recent_conversations": recent_conversations,
            "lifetime_value": float(customer_info.get("lifetime_value") or 0),
            "memories": memories,
        }
