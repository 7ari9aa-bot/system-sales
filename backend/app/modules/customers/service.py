"""CUSTOMERS domain service — identity resolution and CRM rules.

Every method takes the caller's session and tenant and NEVER commits: the
request/worker owns the transaction, the service owns the rules.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, func, or_, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contact_norm import (
    ContactNormalizationError,
    classify_stored_phone,
    email_candidates,
    normalize_email,
    normalize_phone,
    phone_candidates,
)
from app.core.sql import LIKE_ESCAPE, like_pattern
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
# The extra key migration d5a1c7e94b02 leaves its contact findings under.
_BACKFILL_KEY = "m12_contact_backfill"

# The two things the backfill could not decide, named once here and used by
# both the queue (``contact_data_quality_report``) and its resolve half, so
# the vocabulary the operator sees and the vocabulary the server checks can
# never drift. Each issue owns exactly the mark keys its resolution may clear.
ISSUE_LEGACY_DEFAULT = "phone_legacy_default_country"
ISSUE_CANONICAL_COLLISION = "phone_canonical_collision"
_ISSUE_MARK_KEYS: dict[str, tuple[str, ...]] = {
    ISSUE_LEGACY_DEFAULT: ("phone_status", "legacy_raw", "suspected_phone"),
    ISSUE_CANONICAL_COLLISION: ("phone_collision",),
}
# A ``+9640`` fabrication resolves two ways (the column is right after all, or
# the operator states the real number). A collision resolves ONE way: the two
# rows are confirmed different people. Merging them is NOT offered here —
# see ``resolve_contact_issue``.
_ISSUE_RESOLUTIONS: dict[str, tuple[str, ...]] = {
    ISSUE_LEGACY_DEFAULT: ("confirm_genuine", "correct"),
    ISSUE_CANONICAL_COLLISION: ("confirm_distinct",),
}


def _contact_flag(extra: dict | None) -> dict:
    """The backfill mark on a row's ``extra``, as a dict (possibly empty)."""
    flag = ((extra or {}).get("data_quality") or {}).get(_BACKFILL_KEY)
    return flag if isinstance(flag, dict) else {}


def _open_contact_issues(flag: dict) -> list[str]:
    """Which of the two queue issues this mark still has open.

    Read off the MARK, not a re-scan — same rule the queue list uses: a row
    the backfill merely rewrote carries provenance (``phone_from``) with
    nothing to act on.
    """
    issues: list[str] = []
    if flag.get("phone_status") == "needs_review":
        issues.append(ISSUE_LEGACY_DEFAULT)
    if flag.get("phone_collision"):
        issues.append(ISSUE_CANONICAL_COLLISION)
    return issues


def _canonical_or_raw(raw: str | None, normalize) -> str | None:
    """Canonical form when we are confident, otherwise the value as it came in.

    Deliberately tolerant because this is the channel/webhook entry: raising a
    400 there makes the provider retry the delivery forever. An unparseable
    value is stored UNCHANGED — never as a fabricated ``+…`` — and then matches
    as itself, exactly as before the normalization layer. The human write path
    (`update_customer`) is strict instead, because there a typo is the caller's
    to fix.
    """
    if not raw or not raw.strip():
        return None
    try:
        return normalize(raw)
    except ContactNormalizationError:
        return raw.strip()


def _now() -> datetime:
    return datetime.now(UTC)


class CustomerService:
    """All customer business rules; static methods taking (session, tenant_id)."""

    # ------------------------------------------------------------- lookup ----

    @staticmethod
    async def _fetch(
        session: AsyncSession, tenant_id: UUID, customer_id: UUID
    ) -> Customer | None:
        """The raw row, dead or alive. Internal: callers use ``get``."""
        return (
            await session.execute(
                select(Customer).where(
                    Customer.id == customer_id,
                    Customer.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def get(session: AsyncSession, tenant_id: UUID, customer_id: UUID) -> Customer:
        """Fetch a LIVE customer scoped to the tenant.

        M2: a tombstone and a merged-away redirector are not customers. Checkout
        carried its own guard for them since Wave 0; every other caller had to
        remember it. Refusing here is what removes that rule from the callers —
        the two states fail differently on purpose (a deletion is gone, a merge
        points somewhere).
        """
        customer = await CustomerService._fetch(session, tenant_id, customer_id)
        if customer is None:
            raise NotFoundError(f"customer {customer_id} not found")
        if customer.deleted_at is not None:
            raise NotFoundError(f"customer {customer_id} not found (archived)")
        if customer.merged_into_customer_id is not None:
            raise ConflictError(
                f"customer {customer_id} has been merged — resolve the canonical "
                "customer first",
                details={"merged_into_customer_id": str(customer.merged_into_customer_id)},
            )
        return customer

    @staticmethod
    async def get_for_erasure(
        session: AsyncSession, tenant_id: UUID, customer_id: UUID
    ) -> Customer:
        """§172: the eraser sees the rows ``get`` refuses.

        A merged-away and an already-tombstoned row are exactly what a
        data-subject request is about, and ``get``'s refusal would park the
        request open forever.
        """
        customer = await CustomerService._fetch(session, tenant_id, customer_id)
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
        before_id for stable keyset pages.

        P7 — ONE sort key for every page: ``(created_at DESC, id DESC)``. The
        cursor is a ``(created_at, id)`` position (``core/pagination.py``), so
        the keyset predicate below only means anything while the ORDER BY breaks
        its tie on ``id`` too. This used to order the uncursed page by ``name``,
        which made page 1's boundary row and page 2's ``<`` comparison agree on
        nothing: customers sharing a ``created_at`` repeated on the next page and
        whatever slid past the boundary was never returned. ``name`` is not
        unique and the tie does happen in practice — a CSV import or a webhook
        burst stamps rows in one transaction.
        """
        stmt = select(Customer).where(
            Customer.tenant_id == tenant_id,
            Customer.deleted_at.is_(None),
        )
        if search:
            term = search.strip()
            # M12: contact values are stored canonical, so a search typed in a
            # local spelling must be canonicalized too — otherwise the row
            # exists and the merchant is told it does not.
            patterns = {like_pattern(term)}
            patterns |= {like_pattern(v) for v in phone_candidates(term)}
            patterns |= {like_pattern(v) for v in email_candidates(term)}
            clauses = []
            for column in (Customer.name, Customer.phone, Customer.email):
                clauses.extend(
                    column.ilike(pattern, escape=LIKE_ESCAPE) for pattern in patterns
                )
            stmt = stmt.where(or_(*clauses))
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
        stmt = stmt.limit(limit).offset(offset)
        return list((await session.execute(stmt)).scalars().all())

    @staticmethod
    async def contact_data_quality_report(
        session: AsyncSession, tenant_id: UUID, *, limit: int = 200
    ) -> list[dict]:
        """Rows the M12 backfill could NOT fix, read straight off its marks.

        Migration ``d5a1c7e94b02`` writes two kinds of mark into
        ``customers.extra -> data_quality -> m12_contact_backfill``: a phone
        whose ``+964`` may be the old Iraq default rather than a country code,
        and a pair that would collide on ``uq_customers_tenant_phone``. Both
        need a person — one to say what the number really was, one to decide
        which customer survives — and until now neither was readable anywhere.
        This is the queue behind ``GET /customers/contact-data-issues``.

        Deliberate: the queue comes from the MARKS, not a live re-scan — a row
        the backfill merely rewrote carries a mark with nothing to act on, and
        is dropped here. ``phone_state`` IS re-classified per row, which is what
        makes a human-corrected row visibly corrected instead of quietly wrong.
        Tombstoned and merged-away rows are excluded: a dead row is not a
        quarantined CONTACT any more — resolve refuses it, so the queue must
        not promise it.
        """
        mark = func.jsonb_extract_path(Customer.extra, "data_quality", _BACKFILL_KEY)
        rows = (
            await session.execute(
                select(
                    Customer.id, Customer.name, Customer.phone, Customer.email, Customer.extra
                )
                .where(
                    Customer.tenant_id == tenant_id,
                    mark.isnot(None),
                    Customer.deleted_at.is_(None),
                    Customer.merged_into_customer_id.is_(None),
                )
                .order_by(Customer.id.asc())
                .limit(limit)
            )
        ).all()
        items: list[dict] = []
        for row in rows:
            flag = _contact_flag(row.extra)
            issues = _open_contact_issues(flag)
            if not issues:
                continue
            items.append(CustomerService._contact_issue_view(row, flag, issues))
        return items

    @staticmethod
    def _contact_issue_view(row, flag: dict, issues: list[str]) -> dict:
        """One queue item — the mark's facts, the raw stored value, and the
        LIVE classification. Never a value the server does not have: keys the
        mark does not carry come back ``None``/empty, and the screen says so."""
        collision = flag.get("phone_collision") or {}
        return {
            "customer_id": str(row.id),
            "name": row.name,
            "phone": row.phone,
            "email": row.email,
            "phone_state": classify_stored_phone(row.phone),
            "issues": issues,
            "legacy_raw": flag.get("legacy_raw"),
            "suspected_phone": flag.get("suspected_phone"),
            "canonical_phone": collision.get("canonical"),
            "peer_customer_ids": collision.get("peer_customer_ids") or [],
        }

    @staticmethod
    async def resolve_contact_issue(
        session: AsyncSession,
        tenant_id: UUID,
        customer_id: UUID,
        *,
        issue: str,
        resolution: str,
        phone: str | None = None,
        actor_user_id: UUID | None = None,
    ) -> dict:
        """Clear ONE quarantine mark the operator has actually decided.

        What is safe to automate, and what is not:

        * ``confirm_genuine`` / ``correct`` for a ``+9640`` review mark —
          safe: they change a MARK (and, for ``correct``, the one column the
          operator restates, canonicalized by the same strict rule every human
          write uses and clash-checked against live rows).
        * ``confirm_distinct`` for a collision — safe: it records that two
          rows are two people; each keeps its own spelling.
        * MERGING the colliding pair is NOT offered, deliberately. A merge
          retargets orders, conversations, ledgers and identities onto one
          survivor and tombstones the other — whose lifetime value and
          history survive is a business decision ``IdentityMergeService``
          guards behind explicit human approval (``POST /customers/merge``).
          A mark-clearing endpoint that could trigger it would let a queue
          click decide that, so it refuses instead — and says where the real
          merge lives.

        A row whose issue is not open answers ``ConflictError`` naming the
        server's REAL open issues — an already-resolved row never reports
        success a second time.
        """
        from app.core.audit import write_audit_row

        customer = await CustomerService.get(session, tenant_id, customer_id)
        if issue not in _ISSUE_MARK_KEYS:
            raise ValidationError(
                f"unknown contact issue '{issue}'; openable issues are "
                f"{sorted(_ISSUE_MARK_KEYS)}"
            )
        open_issues = _open_contact_issues(_contact_flag(customer.extra))
        if issue not in open_issues:
            raise ConflictError(
                f"customer {customer_id} has no open '{issue}' contact issue — "
                f"the server's real state: open issues are "
                f"{open_issues if open_issues else 'none (row is clean)'}"
            )
        allowed = _ISSUE_RESOLUTIONS[issue]
        if resolution not in allowed:
            refusal = ""
            if issue == ISSUE_CANONICAL_COLLISION:
                refusal = (
                    " — a merge moves orders, conversations and ledgers and "
                    "tombstones a customer, which is a human decision owned by "
                    "POST /customers/merge, not by this endpoint"
                )
            raise ValidationError(
                f"resolution '{resolution}' is not offered for '{issue}'; "
                f"allowed: {list(allowed)}{refusal}"
            )

        before_flag = _contact_flag(customer.extra)
        cleared = [k for k in _ISSUE_MARK_KEYS[issue] if k in before_flag]
        after_flag = {k: v for k, v in before_flag.items() if k not in _ISSUE_MARK_KEYS[issue]}

        phone_before = customer.phone
        if resolution == "correct":
            if not phone:
                raise ValidationError(
                    f"resolution 'correct' for '{issue}' requires the real phone"
                )
            canonical = normalize_phone(phone)  # strict, like every human write
            clash = (
                await session.execute(
                    select(Customer.id).where(
                        Customer.tenant_id == tenant_id,
                        Customer.phone.in_(phone_candidates(phone)),
                        Customer.id != customer_id,
                        Customer.deleted_at.is_(None),
                        Customer.merged_into_customer_id.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if clash is not None:
                raise ConflictError(
                    f"customer phone '{canonical}' already belongs to customer {clash}"
                )
            customer.phone = canonical

        # Rebuild extra WHOLESALE: JSONB has no in-place mutation the ORM can
        # see, and the mark is merged additively with any other data_quality
        # keys the row may have gained since.
        extra = dict(customer.extra or {})
        quality = dict(extra.get("data_quality") or {})
        if after_flag:
            quality[_BACKFILL_KEY] = after_flag
        else:
            quality.pop(_BACKFILL_KEY, None)
        if quality:
            extra["data_quality"] = quality
        else:
            extra.pop("data_quality", None)
        customer.extra = extra
        await session.flush()

        await write_audit_row(
            session,
            tenant_id,
            actor_user_id,
            action="customer.contact_issue_resolved",
            resource_type="customer",
            resource_id=str(customer_id),
            before={
                "issue": issue,
                "cleared_keys": cleared,
                "phone_before": phone_before,
            },
            after={
                "resolution": resolution,
                "phone_after": customer.phone,
                "remaining_issues": _open_contact_issues(after_flag),
            },
        )
        return CustomerService._contact_issue_view(
            customer, after_flag, _open_contact_issues(after_flag)
        )

    # ------------------------------------------------------------- crud ----

    @staticmethod
    async def create_from_import(
        session: AsyncSession,
        tenant_id: UUID,
        *,
        name: str,
        email: str | None = None,
        phone: str | None = None,
        source: str = "csv_import",
        tags: str | None = None,
    ) -> Customer:
        """Create one customer from a CSV row through the SAME rules (§161/ADR-056).

        The §161 import pipeline hands each validated row here UNCHANGED. This
        is the customers intake, and it is not a bypass: the contact handles are
        canonicalised with ``normalize_phone``/``normalize_email`` and then
        resolved with the very resolver the webhook path uses
        (``_resolve_live_by_contact``), which matches the canonical value AND
        the raw typing because legacy rows still hold what a human typed. So a
        CSV line can never clone a customer that ``update_customer``/
        ``get_or_create_by_identity`` refuse.

        Refusals differ on purpose. A handle that collides with a live customer
        raises ``ConflictError`` — the one exception the pipeline surfaces as a
        visible conflict rather than folding into a generic error. A handle that
        cannot be canonicalised lets ``ContactNormalizationError`` (the project's
        400) propagate: it is refused as that row's error, never stored as a
        fabricated ``+…`` that would poison the uniqueness key.
        """
        canonical_phone = normalize_phone(phone)
        canonical_email = normalize_email(email)

        if phone:
            clash = await CustomerService._resolve_live_by_contact(
                session, tenant_id, Customer.phone, phone_candidates(phone)
            )
            if clash is not None:
                raise ConflictError(
                    f"customer with phone '{canonical_phone}' already exists "
                    f"(id {clash.id})"
                )
        if email:
            clash = await CustomerService._resolve_live_by_contact(
                session, tenant_id, Customer.email, email_candidates(email)
            )
            if clash is not None:
                raise ConflictError(
                    f"customer with email '{canonical_email}' already exists "
                    f"(id {clash.id})"
                )

        # ``source`` is provenance, not a column: it rides ``extra`` so the row
        # records where it came in without inventing a schema for a CSV.
        extra: dict = {"source": source} if source else {}
        customer = Customer(
            tenant_id=tenant_id,
            name=name,
            phone=canonical_phone,
            email=canonical_email,
            extra=extra,
        )
        try:
            async with session.begin_nested():
                session.add(customer)
                await session.flush()
        except IntegrityError:
            # Lost a phone race with a concurrent write (uq_customers_tenant_phone).
            raise ConflictError(
                f"customer with phone '{canonical_phone}' already exists"
            ) from None

        if tags:
            for tag in (t.strip() for t in tags.split(",")):
                if tag:
                    await CustomerService.add_tag(session, tenant_id, customer.id, tag)
        return customer

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

        # M12: canonicalize BEFORE the session is touched. The phone column is a
        # uniqueness key, so a value this layer cannot canonicalize must never
        # reach it — and the canonical form is what gets stored.
        typed_phone = fields.get("phone")
        if typed_phone is not None:
            fields["phone"] = normalize_phone(typed_phone)
        if fields.get("email") is not None:
            fields["email"] = normalize_email(fields["email"])

        customer = await CustomerService.get(session, tenant_id, customer_id)

        new_phone = fields.get("phone")
        if new_phone is not None and new_phone != customer.phone:
            # Match the canonical value AND the raw spelling, because rows
            # written before this layer still hold whatever was typed.
            duplicate = (
                await session.execute(
                    select(Customer.id).where(
                        Customer.tenant_id == tenant_id,
                        Customer.phone.in_(phone_candidates(typed_phone)),
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
        # get() refuses an already-deleted row, so the tombstone cannot be
        # stamped twice from here.
        customer = await CustomerService.get(session, tenant_id, customer_id)
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
        email: str | None = None,
    ) -> Customer:
        """Resolve a channel handle to a customer, creating the cheapest match.

        1. an existing (tenant, channel, external_id) identity wins — the
           customer's last_seen_at is touched;
        2. else a customer holding the same phone/email adopts the new identity;
        3. else a fresh customer + identity pair is created.

        Retries once on unique violations so concurrent webhook deliveries
        converge on the same customer instead of failing.
        """
        # M12: resolve AND store on the canonical form, so one human writing one
        # handle three ways is still one customer.
        canonical_phone = _canonical_or_raw(phone, normalize_phone)
        canonical_email = _canonical_or_raw(email, normalize_email)

        for _attempt in range(_RESOLVE_ATTEMPTS):
            customer = await CustomerService._resolve_by_identity(
                session, tenant_id, channel, external_id
            )
            if customer is not None:
                CustomerService._touch(customer, name)
                return customer

            # The ORIGINAL spellings go in, not the canonical ones: the resolver
            # tries canonical first and then the typed form, which is what a row
            # written before this layer still holds.
            phone_customer = await CustomerService._resolve_by_phone(
                session, tenant_id, phone
            )
            contact_customer = phone_customer or await CustomerService._resolve_by_email(
                session, tenant_id, email
            )
            if contact_customer is not None:
                try:
                    async with session.begin_nested():
                        session.add(
                            CustomerIdentity(
                                tenant_id=tenant_id,
                                customer_id=contact_customer.id,
                                channel=channel,
                                external_id=external_id,
                            )
                        )
                        await session.flush()
                except IntegrityError:
                    continue  # identity appeared concurrently — re-resolve
                CustomerService._touch(contact_customer, name)
                return contact_customer

            try:
                async with session.begin_nested():
                    customer = Customer(
                        tenant_id=tenant_id,
                        name=name or canonical_phone or "",
                        phone=canonical_phone,
                        email=canonical_email,
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
        # get() raises for a tombstone: an erased person is never resurrected by
        # the next inbound message on their old handle.
        return await CustomerService.get(session, tenant_id, identity.customer_id)

    @staticmethod
    async def _resolve_live_by_contact(
        session: AsyncSession, tenant_id: UUID, column, candidates: list[str]
    ) -> Customer | None:
        """First live customer holding one of ``candidates``, canonical first.

        One-at-a-time rather than IN(...): legacy rows can hold two spellings of
        the same handle, and the canonical one must win. A dead row never adopts
        a new identity (M2 again — this query does not go through get()).
        """
        for candidate in candidates:
            customer = (
                await session.execute(
                    select(Customer).where(
                        Customer.tenant_id == tenant_id,
                        column == candidate,
                        Customer.deleted_at.is_(None),
                        Customer.merged_into_customer_id.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if customer is not None:
                return customer
        return None

    @staticmethod
    async def _resolve_by_phone(
        session: AsyncSession, tenant_id: UUID, phone: str | None
    ) -> Customer | None:
        if not phone:
            return None
        return await CustomerService._resolve_live_by_contact(
            session, tenant_id, Customer.phone, phone_candidates(phone)
        )

    @staticmethod
    async def _resolve_by_email(
        session: AsyncSession, tenant_id: UUID, email: str | None
    ) -> Customer | None:
        if not email:
            return None
        return await CustomerService._resolve_live_by_contact(
            session, tenant_id, Customer.email, email_candidates(email)
        )

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

        from app.core.audit import write_audit_row
        from app.core.errors import ConflictError, NotFoundError
        from app.core.events.writer import add_outbox_event
        from app.modules.customers.models import IdentityMergeEvent

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

        # Consolidated lifetime value on the canonical record. Both sides are
        # DERIVED figures (the order money path rewrites them from the ledger
        # rows, §M6) and the remap above moved those rows to the canonical
        # customer, so the sum is what a restripe of that row would derive.
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
        await write_audit_row(
            session,
            tenant_id,
            performed_by_user_id,
            action="customer.merged",
            resource_type="customer",
            resource_id=str(canonical_customer_id),
            after={"merged_away": str(merged_away_customer_id), "source": source},
        )
        # §153: the canonical row's REAL version (Customer carries
        # VersionMixin). The merge's raw SQL above does not bump it, so read
        # the post-merge value from the row instead of hardcoding a literal.
        canonical_version = (
            await session.execute(
                text(
                    "SELECT version FROM customers "
                    "WHERE tenant_id = :t AND id = :cid"
                ),
                {"t": tenant_id, "cid": canonical_customer_id},
            )
        ).scalar_one()
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
            aggregate_version=canonical_version,
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
            # §47/ADR-053: the SAME column `customers/router.py::_customer_summary`
            # and `timeline.py` already ship as `str(Decimal)`. The `or` keeps the
            # money scale on a zero row so this reader never answers "0" where the
            # human read answers "0.00"; it is a float-free coercion, not a second
            # money rule.
            "lifetime_value": str(customer_info.get("lifetime_value") or Decimal("0.00")),
            "memories": memories,
        }
