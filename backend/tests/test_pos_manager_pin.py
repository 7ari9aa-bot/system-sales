"""Manager PIN: a manager approves ONE action at the cashier's till.

Each test pins one rule, and the ones about secrecy and throttling are written so that removing
the rule makes them fail:

* the PIN is stored as a hash and nothing in the audit trail contains it;
* every way of failing says the same thing;
* five wrong PINs lock the manager out, and the right PIN is refused while locked;
* the permission is checked when the PIN is USED;
* an approval covers one request and the audit row names the manager.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from fakeredis.aioredis import FakeRedis

from app.core.security import hash_password
from app.modules.errors import PermissionDeniedError, ValidationError
from app.modules.identity.deps import TenantContext
from app.modules.pos.override import (
    NO_GRANT,
    ManagerPinService,
    resolve_override,
)

pytestmark = pytest.mark.asyncio

REFUSED = "manager approval refused"


@pytest.fixture(autouse=True)
async def _redis(monkeypatch):
    """A private in-memory Redis per test: a real lockout (Lua and all), no shared state."""
    from app.modules.pos import override

    client = FakeRedis(decode_responses=True)
    monkeypatch.setattr(override, "get_redis", lambda: client)
    yield client
    await client.aclose()


async def _member(db, tenant_ctx, role_code, name="m"):
    """A real user who belongs to the tenant with the role the DB seeds."""
    from app.modules.identity.models import Role, TenantUser, User

    user = User(
        email=f"{name}-{uuid.uuid4().hex[:8]}@test.local",
        password_hash=hash_password("secret-password"),
        full_name=name,
    )
    db.add(user)
    await db.flush()
    role = (await db.execute(sa.select(Role).where(Role.code == role_code))).scalars().first()
    db.add(TenantUser(tenant_id=tenant_ctx.tenant_id, user_id=user.id, role_id=role.id))
    await db.flush()
    return user


async def _perms(db, role_code):
    return set(
        (
            await db.execute(
                sa.text(
                    "SELECT p.code FROM role_permissions rp JOIN roles r ON r.id = rp.role_id "
                    "JOIN permissions p ON p.id = rp.permission_id WHERE r.code = :c"
                ),
                {"c": role_code},
            )
        ).scalars()
    )


async def _ctx(db, tenant_ctx, user, role_code):
    return TenantContext(
        session=db,
        user=user,
        tenant_id=tenant_ctx.tenant_id,
        role_code=role_code,
        permission_codes=await _perms(db, role_code),
    )


def _req(path="/pos/sessions/x/sell"):
    return SimpleNamespace(method="POST", url=SimpleNamespace(path=path))


async def _resolve(ctx, manager_id=None, pin=None):
    return await resolve_override(_req(), ctx, x_manager_id=manager_id, x_manager_pin=pin)


async def _setup(db, tenant_ctx, pin="4821"):
    manager = await _member(db, tenant_ctx, "manager", "boss")
    cashier = await _member(db, tenant_ctx, "staff", "till")
    await ManagerPinService.set_pin(db, tenant_ctx.tenant_id, manager.id, pin)
    return manager, cashier, await _ctx(db, tenant_ctx, cashier, "staff")


async def _audit_actions(db, tenant_ctx):
    rows = await db.execute(
        sa.text(
            "SELECT action, actor_user_id, resource_id, after FROM audit_logs "
            "WHERE tenant_id = :t AND resource_type = 'pos_override' ORDER BY created_at, id"
        ),
        {"t": tenant_ctx.tenant_id},
    )
    return rows.all()


# ------------------------------------------------------------------ the happy path --


async def test_the_right_pin_grants_the_override_for_this_request(db, tenant_ctx):
    manager, cashier, ctx = await _setup(db, tenant_ctx)
    grant = await _resolve(ctx, str(manager.id), "4821")
    assert grant.active is True
    assert grant.approved_by == manager.id


async def test_without_headers_the_cashier_has_no_override(db, tenant_ctx):
    _, _, ctx = await _setup(db, tenant_ctx)
    assert await _resolve(ctx) == NO_GRANT


async def test_a_manager_signed_in_themself_needs_no_pin(db, tenant_ctx):
    manager = await _member(db, tenant_ctx, "manager", "boss")
    grant = await _resolve(await _ctx(db, tenant_ctx, manager, "manager"))
    assert grant.active is True
    assert grant.approved_by is None  # nobody approved it: it is their own authority


async def test_a_grant_is_not_remembered_for_the_next_request(db, tenant_ctx):
    manager, _, ctx = await _setup(db, tenant_ctx)
    assert (await _resolve(ctx, str(manager.id), "4821")).active
    assert await _resolve(ctx) == NO_GRANT  # no headers on the next call, no override


# ------------------------------------------------------------------- refusals --


async def test_a_wrong_pin_is_refused(db, tenant_ctx):
    manager, _, ctx = await _setup(db, tenant_ctx)
    with pytest.raises(PermissionDeniedError, match=REFUSED):
        await _resolve(ctx, str(manager.id), "0000")


async def test_every_kind_of_failure_says_the_same_thing(db, tenant_ctx):
    """No such manager, no PIN set, wrong PIN, not a manager: indistinguishable to the caller."""
    manager, cashier, ctx = await _setup(db, tenant_ctx)
    no_pin_manager = await _member(db, tenant_ctx, "manager", "nopin")
    other_cashier = await _member(db, tenant_ctx, "staff", "other")
    await ManagerPinService.set_pin(db, tenant_ctx.tenant_id, other_cashier.id, "1357")

    attempts = [
        (str(uuid.uuid4()), "4821"),  # nobody by that id
        (str(no_pin_manager.id), "4821"),  # a manager who never set a PIN
        (str(manager.id), "9999"),  # wrong PIN
        (str(other_cashier.id), "1357"),  # right PIN, but a role without pos:override
        ("not-a-uuid", "4821"),  # garbage id
    ]
    messages = set()
    for manager_id, pin in attempts:
        with pytest.raises(PermissionDeniedError) as exc:
            await _resolve(ctx, manager_id, pin)
        messages.add(str(exc.value))
    assert messages == {REFUSED}


async def test_only_one_of_the_two_headers_is_refused(db, tenant_ctx):
    manager, _, ctx = await _setup(db, tenant_ctx)
    with pytest.raises(PermissionDeniedError, match=REFUSED):
        await _resolve(ctx, str(manager.id), None)
    with pytest.raises(PermissionDeniedError, match=REFUSED):
        await _resolve(ctx, None, "4821")


async def test_a_pin_is_checked_against_the_permission_when_it_is_used(db, tenant_ctx):
    """A manager demoted after setting a PIN cannot approve with it."""
    manager, _, ctx = await _setup(db, tenant_ctx)
    assert (await _resolve(ctx, str(manager.id), "4821")).active
    staff_role = (
        await db.execute(sa.text("SELECT id FROM roles WHERE code = 'staff'"))
    ).scalar_one()
    await db.execute(
        sa.text("UPDATE tenant_users SET role_id = :r WHERE user_id = :u"),
        {"r": staff_role, "u": manager.id},
    )
    with pytest.raises(PermissionDeniedError, match=REFUSED):
        await _resolve(ctx, str(manager.id), "4821")


async def test_a_deactivated_manager_cannot_approve(db, tenant_ctx):
    """The session's own user is the one row the test role may change, so it plays the manager."""
    from app.modules.identity.models import Role

    manager = tenant_ctx.user
    manager_role = (
        (await db.execute(sa.select(Role).where(Role.code == "manager"))).scalars().first()
    )
    await db.execute(
        sa.text("UPDATE tenant_users SET role_id = :r WHERE tenant_id = :t AND user_id = :u"),
        {"r": manager_role.id, "t": tenant_ctx.tenant_id, "u": manager.id},
    )
    await ManagerPinService.set_pin(db, tenant_ctx.tenant_id, manager.id, "4821")
    cashier = await _member(db, tenant_ctx, "staff", "till")
    ctx = await _ctx(db, tenant_ctx, cashier, "staff")

    # Control: while active, the very same PIN is accepted. Without this the refusal below could
    # be caused by anything else (wrong role, missing PIN) and the test would prove nothing.
    grant = await _resolve(ctx, str(manager.id), "4821")
    assert grant.active and grant.approved_by == manager.id

    manager.is_active = False
    await db.flush()
    with pytest.raises(PermissionDeniedError, match=REFUSED):
        await _resolve(ctx, str(manager.id), "4821")


async def test_someone_who_is_not_a_member_of_this_shop_cannot_approve_here(db, tenant_ctx):
    """A manager elsewhere has no authority here, even with a PIN row and a manager role.

    Row-level security forbids writing another shop's membership from this session, so the
    outsider is modelled as a user whose membership here was removed: the PIN still exists, the
    role they hold elsewhere still carries ``pos:override``, and only the missing membership
    separates them from a real approver.
    """
    outsider = await _member(db, tenant_ctx, "manager", "outsider")
    await ManagerPinService.set_pin(db, tenant_ctx.tenant_id, outsider.id, "4821")
    cashier = await _member(db, tenant_ctx, "staff", "till")
    ctx = await _ctx(db, tenant_ctx, cashier, "staff")

    grant = await _resolve(ctx, str(outsider.id), "4821")  # control: a member is accepted
    assert grant.approved_by == outsider.id

    await db.execute(
        sa.text("DELETE FROM tenant_users WHERE tenant_id = :t AND user_id = :u"),
        {"t": tenant_ctx.tenant_id, "u": outsider.id},
    )
    with pytest.raises(PermissionDeniedError, match=REFUSED):
        await _resolve(ctx, str(outsider.id), "4821")


async def test_a_manager_cannot_approve_their_own_request_with_a_pin(db, tenant_ctx):
    """The cashier and the approver must be two people."""
    manager = await _member(db, tenant_ctx, "manager", "boss")
    await ManagerPinService.set_pin(db, tenant_ctx.tenant_id, manager.id, "4821")
    staff_like = await _ctx(db, tenant_ctx, manager, "staff")  # acting as a cashier-level caller
    with pytest.raises(PermissionDeniedError, match=REFUSED):
        await _resolve(staff_like, str(manager.id), "4821")


async def test_a_pin_sent_by_someone_who_is_already_a_manager_is_ignored(db, tenant_ctx):
    """It must not be a way to burn a colleague's lockout budget."""
    boss = await _member(db, tenant_ctx, "manager", "boss")
    colleague = await _member(db, tenant_ctx, "manager", "colleague")
    await ManagerPinService.set_pin(db, tenant_ctx.tenant_id, colleague.id, "4821")
    ctx = await _ctx(db, tenant_ctx, boss, "manager")
    for _ in range(8):
        grant = await _resolve(ctx, str(colleague.id), "0000")
        assert grant.active and grant.approved_by is None
    # The colleague's own PIN still works: nothing was counted against them.
    cashier = await _member(db, tenant_ctx, "staff", "till")
    assert (
        await _resolve(await _ctx(db, tenant_ctx, cashier, "staff"), str(colleague.id), "4821")
    ).active


# ------------------------------------------------------------------ the lockout --


async def test_five_wrong_pins_lock_the_manager_out_even_for_the_right_one(db, tenant_ctx):
    from app.core.errors import RateLimitExceededError

    manager, _, ctx = await _setup(db, tenant_ctx)
    for _ in range(5):
        with pytest.raises(PermissionDeniedError):
            await _resolve(ctx, str(manager.id), "0000")
    with pytest.raises(RateLimitExceededError) as exc:
        await _resolve(ctx, str(manager.id), "4821")  # the RIGHT pin, but locked
    assert exc.value.details["retry_after"] > 0


async def test_the_lock_is_per_manager_not_per_shop(db, tenant_ctx):
    manager, _, ctx = await _setup(db, tenant_ctx)
    second = await _member(db, tenant_ctx, "manager", "second")
    await ManagerPinService.set_pin(db, tenant_ctx.tenant_id, second.id, "1357")
    for _ in range(5):
        with pytest.raises(PermissionDeniedError):
            await _resolve(ctx, str(manager.id), "0000")
    assert (await _resolve(ctx, str(second.id), "1357")).active


async def test_a_good_pin_resets_the_count(db, tenant_ctx):
    manager, _, ctx = await _setup(db, tenant_ctx)
    for _ in range(4):
        with pytest.raises(PermissionDeniedError):
            await _resolve(ctx, str(manager.id), "0000")
    assert (await _resolve(ctx, str(manager.id), "4821")).active
    for _ in range(4):  # four more would have been the 8th failure without the reset
        with pytest.raises(PermissionDeniedError):
            await _resolve(ctx, str(manager.id), "0000")
    assert (await _resolve(ctx, str(manager.id), "4821")).active


# ---------------------------------------------------------- storage and format --


async def test_the_pin_is_stored_as_a_hash_and_never_appears_in_the_audit(db, tenant_ctx):
    manager, _, ctx = await _setup(db, tenant_ctx, pin="4821")
    await _resolve(ctx, str(manager.id), "4821")
    with pytest.raises(PermissionDeniedError):
        await _resolve(ctx, str(manager.id), "7777")

    stored = (
        await db.execute(
            sa.text("SELECT pin_hash FROM manager_pins WHERE user_id = :u"), {"u": manager.id}
        )
    ).scalar_one()
    assert stored != "4821" and "4821" not in stored and stored.startswith("bcrypt")

    dump = repr(await _audit_actions(db, tenant_ctx))
    assert "4821" not in dump and "7777" not in dump


@pytest.mark.parametrize(
    "bad", ["123", "123456789", "12ab", "", " 1234", "12 34", "١٢٣٤", None, 1234]
)
async def test_a_pin_must_be_four_to_eight_digits(db, tenant_ctx, bad):
    manager = await _member(db, tenant_ctx, "manager", "boss")
    with pytest.raises(ValidationError):
        await ManagerPinService.set_pin(db, tenant_ctx.tenant_id, manager.id, bad)


async def test_changing_the_pin_replaces_the_old_one(db, tenant_ctx):
    manager, _, ctx = await _setup(db, tenant_ctx, pin="4821")
    await ManagerPinService.set_pin(db, tenant_ctx.tenant_id, manager.id, "9090")
    with pytest.raises(PermissionDeniedError):
        await _resolve(ctx, str(manager.id), "4821")
    assert (await _resolve(ctx, str(manager.id), "9090")).active
    count = (
        await db.execute(
            sa.text("SELECT count(*) FROM manager_pins WHERE user_id = :u"), {"u": manager.id}
        )
    ).scalar_one()
    assert count == 1


async def test_setting_your_own_pin_needs_your_password(db, tenant_ctx):
    manager = await _member(db, tenant_ctx, "manager", "boss")
    with pytest.raises(PermissionDeniedError, match="password"):
        await ManagerPinService.set_own_pin(
            db, tenant_ctx.tenant_id, manager.id, password="wrong-password", pin="4821"
        )
    assert not await ManagerPinService.has_pin(db, tenant_ctx.tenant_id, manager.id)
    await ManagerPinService.set_own_pin(
        db, tenant_ctx.tenant_id, manager.id, password="secret-password", pin="4821"
    )
    assert await ManagerPinService.has_pin(db, tenant_ctx.tenant_id, manager.id)


async def test_the_password_check_is_throttled_too(db, tenant_ctx):
    """Otherwise this endpoint is a free password oracle for anyone holding an open session."""
    from app.core.errors import RateLimitExceededError

    manager = await _member(db, tenant_ctx, "manager", "boss")
    for _ in range(5):
        with pytest.raises(PermissionDeniedError):
            await ManagerPinService.set_own_pin(
                db, tenant_ctx.tenant_id, manager.id, password="nope", pin="4821"
            )
    with pytest.raises(RateLimitExceededError):
        await ManagerPinService.set_own_pin(
            db, tenant_ctx.tenant_id, manager.id, password="secret-password", pin="4821"
        )


# --------------------------------------------------------------------- the audit --


async def test_a_grant_is_audited_under_the_manager_and_a_refusal_under_the_cashier(db, tenant_ctx):
    manager, cashier, ctx = await _setup(db, tenant_ctx)
    with pytest.raises(PermissionDeniedError):
        await _resolve(ctx, str(manager.id), "0000")
    await _resolve(ctx, str(manager.id), "4821")

    rows = {r.action: r for r in await _audit_actions(db, tenant_ctx)}
    assert rows["pos.override.denied"].actor_user_id == cashier.id
    assert rows["pos.override.denied"].resource_id == str(manager.id)
    assert rows["pos.override.granted"].actor_user_id == manager.id
    assert rows["pos.override.granted"].resource_id == str(cashier.id)
    assert rows["pos.override.granted"].after["operation"] == "POST /pos/sessions/x/sell"


# ------------------------------------------- end to end through the real money gates --


async def test_a_pin_lets_a_cashier_sell_past_the_ceiling_and_nothing_else_changes(db, tenant_ctx):
    from app.modules.pos.router import sell
    from tests.test_pos_discount_ceiling import _body, _till

    shift, variant, customer = await _till(db, tenant_ctx, ceiling="10")
    manager = await _member(db, tenant_ctx, "manager", "boss")
    cashier = await _member(db, tenant_ctx, "staff", "till")
    await ManagerPinService.set_pin(db, tenant_ctx.tenant_id, manager.id, "4821")
    ctx = await _ctx(db, tenant_ctx, cashier, "staff")

    # Without the PIN the ceiling still bites.
    from app.modules.errors import ValidationError as VE

    with pytest.raises(VE, match="ceiling"):
        await sell(shift.id, _body(variant, customer), ctx, await _resolve(ctx))

    # With it, the same sale goes through, once.
    grant = await _resolve(ctx, str(manager.id), "4821")
    out = await sell(shift.id, _body(variant, customer), ctx, grant)
    assert out["grand_total"] == "60.00"
