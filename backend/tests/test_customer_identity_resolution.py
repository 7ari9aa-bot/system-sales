"""Customer identity: dead rows and contact normalization (GAP_REGISTER M2/M12).

Two halves, deliberately:

* ``CustomerService.get`` handed back a tombstoned or merged-away row, so every
  caller except checkout had to remember the guard (M2). These tests pin that
  the accessor itself refuses.
* phone/email identity resolution was exact-string, so ``+20 100 123 4567``,
  ``00201001234567`` and ``01001234567`` created three customers (M12). These
  tests pin one canonical stored value per human.

The pure cases (contact_norm + the fake-session ``get`` refusals) run locally.
The DB-backed ones skip locally and prove their RED in CI.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contact_norm import (
    ContactNormalizationError,
    normalize_email,
    normalize_phone,
)
from app.modules.customers.models import Customer
from app.modules.customers.service import CustomerService, IdentityMergeService
from app.modules.errors import ConflictError, NotFoundError, ValidationError

EGYPT_CANONICAL = "+201001234567"


# ---------------------------------------------------------------------------
# Doubles — a session that answers one select(Customer) with a given row
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, row: object) -> None:
        self._row = row

    def scalar_one_or_none(self) -> object:
        return self._row


class _RowSession:
    """Enough of AsyncSession for CustomerService.get's single SELECT."""

    def __init__(self, row: object) -> None:
        self.row = row
        self.statement: object = None

    async def execute(self, statement: object) -> _Result:
        self.statement = statement
        return _Result(self.row)


def _row(**fields: object) -> Customer:
    """An unsaved Customer instance — the state under test, not a DB round trip."""
    return Customer(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        name="Sameh",
        phone=EGYPT_CANONICAL,
        **fields,
    )


# ---------------------------------------------------------------------------
# A (M2) — get refuses a dead row. Pure: the refusal is a rule, not a query.
# ---------------------------------------------------------------------------


async def test_get_refuses_a_tombstoned_customer() -> None:
    """A deleted customer is not retrievable — the guard checkout already had."""
    row = _row(deleted_at=datetime.now(UTC))

    with pytest.raises(NotFoundError) as exc:
        await CustomerService.get(_RowSession(row), row.tenant_id, row.id)  # type: ignore[arg-type]

    assert "archived" in str(exc.value)


async def test_get_refuses_a_merged_away_customer() -> None:
    """A merged row is a redirect, not a customer; the error names the target."""
    canonical = uuid.uuid4()
    row = _row(merged_into_customer_id=canonical, merged_at=datetime.now(UTC))

    with pytest.raises(ConflictError) as exc:
        await CustomerService.get(_RowSession(row), row.tenant_id, row.id)  # type: ignore[arg-type]

    assert "merged" in str(exc.value)
    assert exc.value.details.get("merged_into_customer_id") == str(canonical)


async def test_get_still_returns_a_live_customer() -> None:
    row = _row()

    found = await CustomerService.get(_RowSession(row), row.tenant_id, row.id)  # type: ignore[arg-type]

    assert found.id == row.id


# ---------------------------------------------------------------------------
# B (M12) — the normalization vocabulary itself. Stdlib only, so it runs here.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "spelling",
    [
        "+20 100 123 4567",
        "00201001234567",
        "01001234567",
        "0100-123-4567",
        "201001234567",
        "(0100) 123 4567",
    ],
)
def test_every_egyptian_spelling_canonicalizes_to_one_e164_value(spelling: str) -> None:
    assert normalize_phone(spelling) == EGYPT_CANONICAL


def test_an_international_number_passes_through_unchanged() -> None:
    """Other markets arrive already canonical; there is nothing to guess."""
    assert normalize_phone("+44 20 7183 8750") == "+442071838750"
    assert normalize_phone("+10000000001") == "+10000000001"


def test_a_double_zero_prefix_matches_the_plus_form() -> None:
    assert normalize_phone("00201001234567") == normalize_phone("+201001234567")


def test_a_number_that_cannot_be_canonicalized_is_refused() -> None:
    """Guessing beats nothing: a bogus '+…' string is a poisoned identity key."""
    for garbage in ("call me maybe", "0100123", "+2010a3f9b2c1", "12345", "+", "0"):
        with pytest.raises(ContactNormalizationError):
            normalize_phone(garbage)


def test_blank_phone_normalizes_to_nothing() -> None:
    assert normalize_phone(None) is None
    assert normalize_phone("   ") is None


def test_email_canonical_form_is_trimmed_and_lowercased() -> None:
    assert normalize_email("  Ali.Hassan@EXAMPLE.com ") == "ali.hassan@example.com"
    assert normalize_email("ali@example.com") == "ali@example.com"


def test_a_non_email_is_refused() -> None:
    for garbage in ("no-at-sign", "@example.com", "ali@", "ali @example.com"):
        with pytest.raises(ContactNormalizationError):
            normalize_email(garbage)


def test_blank_email_normalizes_to_nothing() -> None:
    assert normalize_email(None) is None
    assert normalize_email("") is None


# ---------------------------------------------------------------------------
# B — the write path refuses a phone it cannot canonicalize (before the DB).
# ---------------------------------------------------------------------------


async def test_update_customer_refuses_an_unparseable_phone_without_touching_db() -> None:
    with pytest.raises(ValidationError):
        await CustomerService.update_customer(
            None,  # type: ignore[arg-type] — the guard must run before the session
            uuid.uuid4(),
            uuid.uuid4(),
            phone="call me maybe",
        )


async def test_update_customer_refuses_an_unparseable_email_without_touching_db() -> None:
    with pytest.raises(ValidationError):
        await CustomerService.update_customer(
            None,  # type: ignore[arg-type]
            uuid.uuid4(),
            uuid.uuid4(),
            email="not-an-email",
        )


# ---------------------------------------------------------------------------
# DB-backed halves (CI RED; skipped locally without DATABASE_URL_APP_ADMIN)
# ---------------------------------------------------------------------------


async def _mk_customer(db: AsyncSession, tenant_id: uuid.UUID, **fields: object) -> Customer:
    return await CustomerService.get_or_create_by_identity(
        db, tenant_id, "whatsapp", f"wa-{uuid.uuid4().hex[:12]}", **fields  # type: ignore[arg-type]
    )


async def test_get_refuses_an_archived_customer_in_db(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    customer = await _mk_customer(db, tenant_id, name="Gone")
    await CustomerService.archive(db, tenant_id, customer.id, reason="privacy")

    with pytest.raises(NotFoundError):
        await CustomerService.get(db, tenant_id, customer.id)


async def test_get_refuses_a_merged_away_customer_in_db(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    canonical = await _mk_customer(db, tenant_id, name="Kept")
    away = await _mk_customer(db, tenant_id, name="Duplicated")

    await IdentityMergeService.merge(
        db,
        tenant_id,
        canonical_customer_id=canonical.id,
        merged_away_customer_id=away.id,
        performed_by_user_id=tenant_ctx.user.id,
    )

    with pytest.raises(ConflictError):
        await CustomerService.get(db, tenant_id, away.id)
    # The surviving record still reads back normally.
    live = await CustomerService.get(db, tenant_id, canonical.id)
    assert live.id == canonical.id


async def test_identity_resolution_never_hands_back_a_tombstone(
    db: AsyncSession, tenant_ctx
):
    """The channel handle belongs to a deleted person: refuse, never resurrect."""
    tenant_id = tenant_ctx.tenant_id
    external_id = f"wa-{uuid.uuid4().hex[:12]}"
    customer = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "whatsapp", external_id, name="Erased"
    )
    await CustomerService.archive(db, tenant_id, customer.id, reason="privacy")

    with pytest.raises(NotFoundError):
        await CustomerService.get_or_create_by_identity(db, tenant_id, "whatsapp", external_id)


async def test_three_spellings_of_one_egyptian_number_are_one_customer(
    db: AsyncSession, tenant_ctx
):
    tenant_id = tenant_ctx.tenant_id

    first = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "whatsapp", f"wa-{uuid.uuid4().hex[:12]}", phone="+20 100 123 4567"
    )
    second = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "instagram", f"ig-{uuid.uuid4().hex[:12]}", phone="00201001234567"
    )
    third = await CustomerService.get_or_create_by_identity(
        db, tenant_id, "telegram", f"tg-{uuid.uuid4().hex[:12]}", phone="01001234567"
    )

    assert second.id == first.id
    assert third.id == first.id
    stored = await db.scalar(select(Customer.phone).where(Customer.id == first.id))
    assert stored == EGYPT_CANONICAL
    rows = await db.scalar(
        select(func.count()).select_from(Customer).where(Customer.tenant_id == tenant_id)
    )
    assert rows == 1


async def test_email_case_does_not_create_a_duplicate(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id

    first = await CustomerService.get_or_create_by_identity(
        db,
        tenant_id,
        "webchat",
        f"wc-{uuid.uuid4().hex[:12]}",
        email="Ali.Hassan@EXAMPLE.com",
    )
    again = await CustomerService.get_or_create_by_identity(
        db,
        tenant_id,
        "messenger",
        f"ms-{uuid.uuid4().hex[:12]}",
        email="  ali.hassan@example.com ",
    )

    assert again.id == first.id
    stored = await db.scalar(select(Customer.email).where(Customer.id == first.id))
    assert stored == "ali.hassan@example.com"


async def test_update_customer_stores_canonical_contact_values(db: AsyncSession, tenant_ctx):
    tenant_id = tenant_ctx.tenant_id
    customer = await _mk_customer(db, tenant_id, name="Canonical")

    updated = await CustomerService.update_customer(
        db, tenant_id, customer.id, phone="0100 123 4567", email="  SAMEH@Example.COM "
    )

    assert updated.phone == EGYPT_CANONICAL
    assert updated.email == "sameh@example.com"


async def test_update_customer_refuses_a_phone_already_on_another_customer(
    db: AsyncSession, tenant_ctx
):
    """The clash is on the CANONICAL value, not the typed spelling."""
    tenant_id = tenant_ctx.tenant_id
    taken = await _mk_customer(db, tenant_id, name="Taken", phone=EGYPT_CANONICAL)
    other = await _mk_customer(db, tenant_id, name="Other")

    with pytest.raises(ConflictError):
        await CustomerService.update_customer(db, tenant_id, other.id, phone="0100-123-4567")
    assert taken.phone == EGYPT_CANONICAL
