"""The person's own contact facts, and the way out of the account.

The profile page could only hold a name and an address: no phone, no job title,
and no way at all to ask for the account to be closed. Both are the PERSON's
facts, so both live on ``/users/me`` — never on a tenant route — and the id
always comes from the token.

Two behaviours are worth pinning because they are easy to get wrong later:

- A phone is stored as what it is (digits and one leading ``+``), and an empty
  string is a real instruction that clears it. Typed punctuation is forgiven;
  text that is not a number is refused rather than saved as decoration.
- Closing the account is a REQUEST with a handover in front of it. A sole owner
  of a live shop cannot open one — the shop would be left with nobody able to
  administer it — and the state route names the shop instead of hiding the
  reason.
"""

from __future__ import annotations

from typing import Any

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ValidationError
from app.main import create_app
from app.platform.identity.deps import AuthedUser, TenantContext, get_tenant_ctx
from app.platform.identity.models import Role, TenantUser
from app.platform.identity.service import AccountClosureService, UserService

PROFILE_URL = "/api/v1/users/me"
CLOSURE_URL = "/api/v1/users/me/closure-request"


def _client(db: AsyncSession, ctx: TenantContext) -> AsyncClient:
    app: FastAPI = create_app()

    async def _ctx() -> TenantContext:
        return TenantContext(
            session=db,
            user=AuthedUser(id=ctx.user.id, tenant_id=ctx.tenant_id, role_code="owner"),
            tenant_id=ctx.tenant_id,
            role_code="owner",
            permission_codes=set(),
        )

    app.dependency_overrides[get_tenant_ctx] = _ctx
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _demote_to_staff(db: AsyncSession, ctx: TenantContext) -> None:
    """The person stops being the shop's only owner, so nothing blocks a closure."""
    staff = (await db.execute(sa.select(Role).where(Role.code == "staff"))).scalar_one()
    membership = (
        await db.execute(
            sa.select(TenantUser).where(
                TenantUser.user_id == ctx.user.id,
                TenantUser.tenant_id == ctx.tenant_id,
            )
        )
    ).scalar_one()
    membership.role_id = staff.id
    await db.flush()


# ------------------------------------------------------------------ phone ----


async def test_a_typed_phone_is_stored_as_digits_and_one_leading_plus(
    db: AsyncSession, tenant_ctx
) -> None:
    await UserService.update_profile(db, tenant_ctx.user.id, phone="+20 100 123 4567")
    assert (await UserService.get(db, tenant_ctx.user.id)).phone == "+201001234567"


async def test_a_local_number_keeps_its_digits_without_a_plus(db: AsyncSession, tenant_ctx) -> None:
    await UserService.update_profile(db, tenant_ctx.user.id, phone="0100-123-4567")
    assert (await UserService.get(db, tenant_ctx.user.id)).phone == "01001234567"


async def test_an_unusable_phone_is_refused(db: AsyncSession, tenant_ctx) -> None:
    with pytest.raises(ValidationError):
        await UserService.update_profile(db, tenant_ctx.user.id, phone="not a phone")
    with pytest.raises(ValidationError):
        await UserService.update_profile(db, tenant_ctx.user.id, phone="12345")
    assert (await UserService.get(db, tenant_ctx.user.id)).phone is None


async def test_an_empty_phone_clears_the_field(db: AsyncSession, tenant_ctx) -> None:
    await UserService.update_profile(db, tenant_ctx.user.id, phone="+201001234567")
    await UserService.update_profile(db, tenant_ctx.user.id, phone="")
    assert (await UserService.get(db, tenant_ctx.user.id)).phone is None


# -------------------------------------------------------------- job title ----


async def test_a_job_title_collapses_whitespace_and_clears_on_empty(
    db: AsyncSession, tenant_ctx
) -> None:
    await UserService.update_profile(db, tenant_ctx.user.id, job_title="  Store   Manager ")
    assert (await UserService.get(db, tenant_ctx.user.id)).job_title == "Store Manager"

    await UserService.update_profile(db, tenant_ctx.user.id, job_title="   ")
    assert (await UserService.get(db, tenant_ctx.user.id)).job_title is None


# ------------------------------------------------------------- the route -----


async def test_the_profile_route_answers_with_the_contact_fields(
    db: AsyncSession, tenant_ctx
) -> None:
    async with _client(db, tenant_ctx) as client:
        response = await client.patch(
            PROFILE_URL,
            json={"phone": "+20 100 123 4567", "job_title": "Owner"},
        )
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        assert body["phone"] == "+201001234567"
        assert body["job_title"] == "Owner"
        # the screen draws a verification badge from this flag, so it must travel
        assert body["email_verified"] is False
        # the name was not part of the request and is untouched
        assert body["full_name"] == tenant_ctx.user.full_name


async def test_a_body_with_nothing_to_change_is_refused(db: AsyncSession, tenant_ctx) -> None:
    async with _client(db, tenant_ctx) as client:
        empty = await client.patch(PROFILE_URL, json={})
        assert empty.status_code == 422, empty.text


# ---------------------------------------------------------------- closure ----


async def test_a_sole_owner_cannot_ask_to_close_the_account(db: AsyncSession, tenant_ctx) -> None:
    """The shop would be left without an administrator, so the request is refused."""
    with pytest.raises(ValidationError) as refusal:
        await AccountClosureService.open(db, tenant_ctx.user.id, mode="close", reason=None)
    assert tenant_ctx.tenant.name in str(refusal.value)


async def test_the_closure_state_names_the_blocking_shop(db: AsyncSession, tenant_ctx) -> None:
    state = await AccountClosureService.state(db, tenant_ctx.user.id)
    assert state["request"] is None
    assert state["memberships"] == 1
    assert [blocker["tenant_name"] for blocker in state["blockers"]] == [tenant_ctx.tenant.name]


async def test_a_member_can_open_one_request_and_cancel_it(db: AsyncSession, tenant_ctx) -> None:
    await _demote_to_staff(db, tenant_ctx)

    opened = await AccountClosureService.open(
        db, tenant_ctx.user.id, mode="delete", reason="  moving   on "
    )
    assert opened.status == "pending"
    assert opened.reason == "moving on"

    # a second submit is a conflict, not a second row
    with pytest.raises(ConflictError):
        await AccountClosureService.open(db, tenant_ctx.user.id, mode="close", reason=None)

    cancelled = await AccountClosureService.cancel(db, tenant_ctx.user.id)
    assert cancelled.status == "cancelled"

    state = await AccountClosureService.state(db, tenant_ctx.user.id)
    assert state["request"] is not None
    assert state["request"].status == "cancelled"
    assert state["blockers"] == []


async def test_the_closure_route_opens_and_withdraws_a_request(
    db: AsyncSession, tenant_ctx
) -> None:
    await _demote_to_staff(db, tenant_ctx)

    async with _client(db, tenant_ctx) as client:
        read = await client.get(CLOSURE_URL)
        assert read.status_code == 200, read.text
        assert read.json()["request"] is None
        assert read.json()["blockers"] == []

        created = await client.post(CLOSURE_URL, json={"mode": "close"})
        assert created.status_code == 201, created.text
        assert created.json()["request"]["status"] == "pending"
        assert created.json()["request"]["mode"] == "close"

        withdrawn = await client.delete(CLOSURE_URL)
        assert withdrawn.status_code == 204, withdrawn.text

        after = await client.get(CLOSURE_URL)
        assert after.json()["request"]["status"] == "cancelled"


async def test_the_closure_route_refuses_a_sole_owner_with_a_reason(
    db: AsyncSession, tenant_ctx
) -> None:
    async with _client(db, tenant_ctx) as client:
        refused = await client.post(CLOSURE_URL, json={"mode": "close"})
        assert refused.status_code == 400, refused.text
        assert tenant_ctx.tenant.name in refused.text

        state = await client.get(CLOSURE_URL)
        assert [b["tenant_id"] for b in state.json()["blockers"]] == [str(tenant_ctx.tenant_id)]


async def test_a_mode_outside_the_two_choices_is_refused(db: AsyncSession, tenant_ctx) -> None:
    async with _client(db, tenant_ctx) as client:
        response = await client.post(CLOSURE_URL, json={"mode": "delete-everything"})
        assert response.status_code == 422, response.text
    # nothing was written for a malformed ask
    assert (
        await db.execute(
            sa.text("SELECT count(*) FROM account_closure_requests WHERE user_id = :uid"),
            {"uid": str(tenant_ctx.user.id)},
        )
    ).scalar_one() == 0
