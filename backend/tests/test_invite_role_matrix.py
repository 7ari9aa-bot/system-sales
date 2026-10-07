"""The mandated closing matrix for package 1.3 — every role inviting every role.

Two layers, one invariant (the invitation IS the grant — accept_invitation
binds the invited role_id verbatim, service.py — so the invite surface is the
privilege-escalation boundary of the whole tenant):

HTTP layer — POST /api/v1/tenants/{id}/invitations driven through ``create_app``
and the real dependency stack, the same harness as the 1.2 lifecycle matrix.
Each cell's verdict is the status the API actually answers:

  201  the invitation was created (pending)
  403  refused on authority — no credentials, the RBAC gate
       (``settings:write``), or the service hierarchy guard
  400  the invited role code does not exist (role resolution precedes the
       hierarchy check, service.py invite — the documented 400)

Service layer — ``TenantService.invite`` called directly. This is the only way
to reach the strict-outrank invariant for inviters the HTTP RBAC gate hides:
manager and staff hold no ``settings:write`` (provision.py ROLE_MATRIX), so
their hierarchy cells are unreachable through the route. Unknown inviter ranks
("ghost") fail CLOSED there — an inviter whose role cannot be placed outranks
nothing.

Completeness guard — the matrix must cover every role provision.py seeds plus
the platform admin and the unknown rank, exactly once per cell. The seeded set
is parsed out of provision.py (its ROLES literal is the source of truth the
``_ROLE_RANK`` order table mirrors), so a new role added to the system without
extending the matrix fails HERE, loudly.
"""

from __future__ import annotations

import ast
import pathlib
import uuid

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy import select

from app.core.errors import PermissionDeniedError, ValidationError
from app.main import create_app
from app.modules.identity.deps import AuthedUser, TenantContext, get_db, get_tenant_ctx
from app.modules.identity.models import Permission, Role, TenantUser, User, role_permissions
from app.modules.identity.service import TenantService

BACKEND = pathlib.Path(__file__).resolve().parent.parent
PROVISION_PATH = BACKEND / "scripts" / "provision.py"

#: The invited role codes exercised by both layers: every seeded role plus one
#: provably-unknown code (the fail-closed column).
_INVITED_ROLES = ("owner", "manager", "staff", "superwizard")

_SERVICE_INVITERS = ("owner", "manager", "staff", "ghost", "platform_admin")

# (inviter, invited) -> verdict, service layer. EVERY cell has one verdict:
#   allow         — a pending invitation is created
#   deny          — PermissionDeniedError (strict outrank / platform-admin-only
#                   owner invitations / unknown inviter rank, fail closed)
#   unknown_role  — ValidationError: the invited code resolves to no role
SERVICE_INVITE_MATRIX: dict[tuple[str, str], str] = {
    # owner (rank 3): strictly outranks manager and staff; owner invitations
    # are platform-admin-only, so a peer-owner invite is refused.
    ("owner", "owner"): "deny",
    ("owner", "manager"): "allow",
    ("owner", "staff"): "allow",
    # manager (rank 2): strictly outranks staff only; equal rank refuses.
    ("manager", "owner"): "deny",
    ("manager", "manager"): "deny",
    ("manager", "staff"): "allow",
    # staff (rank 1): outranks nobody.
    ("staff", "owner"): "deny",
    ("staff", "manager"): "deny",
    ("staff", "staff"): "deny",
    # ghost: a rank the table cannot place — fails CLOSED on every invite.
    ("ghost", "owner"): "deny",
    ("ghost", "manager"): "deny",
    ("ghost", "staff"): "deny",
    # platform admin: the §146/§147 authority — the one inviter allowed to
    # mint an owner, so it outranks everything seeded.
    ("platform_admin", "owner"): "allow",
    ("platform_admin", "manager"): "allow",
    ("platform_admin", "staff"): "allow",
    # unknown invited code: role resolution precedes the hierarchy check for
    # every inviter — nothing can mint a role that does not exist.
    ("owner", "superwizard"): "unknown_role",
    ("manager", "superwizard"): "unknown_role",
    ("staff", "superwizard"): "unknown_role",
    ("ghost", "superwizard"): "unknown_role",
    ("platform_admin", "superwizard"): "unknown_role",
}

_HTTP_ACTORS = ("anonymous", "staff", "manager", "owner", "platform_admin")

# (actor, invited) -> the status POST /tenants/{id}/invitations must answer.
# EVERY cell has a verdict. The RBAC gate fires before the hierarchy: manager
# and staff hold no settings:write, so even a hierarchy-legal cell such as
# manager→staff is a 403 at the permission gate — which is exactly why the
# service-layer matrix above exists for those inviters.
HTTP_INVITE_MATRIX: dict[tuple[str, str], int] = {
    # No credentials → no tenant context → refused outright.
    **{(actor, invited): 403 for actor in ("anonymous",) for invited in _INVITED_ROLES},
    # RBAC gate: neither staff nor manager holds settings:write.
    **{(actor, invited): 403 for actor in ("staff", "manager") for invited in _INVITED_ROLES},
    # Owner (settings:write, rank 3): peer-owner refused, below-rank allowed,
    # unknown role is the documented 400.
    ("owner", "owner"): 403,
    ("owner", "manager"): 201,
    ("owner", "staff"): 201,
    ("owner", "superwizard"): 400,
    # DB-verified platform admin: owner invitations allowed, below-rank too,
    # unknown role still a 400 (resolution precedes hierarchy for everyone).
    ("platform_admin", "owner"): 201,
    ("platform_admin", "manager"): 201,
    ("platform_admin", "staff"): 201,
    ("platform_admin", "superwizard"): 400,
}


# --- the completeness guards (fail-first if the matrices go stale) ----------


def _provisioned_role_codes() -> set[str]:
    """The role codes provision.py seeds — the source of truth for the ranks."""
    tree = ast.parse(PROVISION_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "ROLES" for target in node.targets
        ):
            codes = {
                element.elts[0].value  # ("code", "Name", "description")
                for element in node.value.elts
            }
            assert codes, "provision.py ROLES parsed to an empty set"
            return codes
    raise AssertionError("ROLES literal not found in provision.py")


def test_the_service_matrix_covers_every_inviter_and_invited_exactly_once() -> None:
    """20 cells: 5 inviters x 4 invited roles, each once, verdicts in vocabulary.

    The inviter set is every seeded role plus the platform admin and the
    unknown rank; the invited set is every seeded role plus one provably
    unknown code. ``_ROLE_RANK`` must mirror provision.py's ROLES exactly —
    a new seeded role without a rank (or a rank without a seeded role) breaks
    the strict-outrank rule this matrix pins.
    """
    seeded = _provisioned_role_codes()
    assert seeded == {"owner", "manager", "staff"}
    assert set(TenantService._ROLE_RANK) == seeded, (
        "TenantService._ROLE_RANK no longer mirrors provision.py's ROLES — "
        "extend the matrix with the new rank before seeding it"
    )
    assert set(_SERVICE_INVITERS) == seeded | {"ghost", "platform_admin"}
    assert set(_INVITED_ROLES) == seeded | {"superwizard"}
    assert len(SERVICE_INVITE_MATRIX) == len(_SERVICE_INVITERS) * len(_INVITED_ROLES)
    assert set(SERVICE_INVITE_MATRIX) == {
        (inviter, invited) for inviter in _SERVICE_INVITERS for invited in _INVITED_ROLES
    }
    assert {verdict for verdict in SERVICE_INVITE_MATRIX.values()} <= {
        "allow",
        "deny",
        "unknown_role",
    }


def test_the_http_matrix_covers_every_actor_and_invited_exactly_once() -> None:
    """20 cells: 5 actor kinds x 4 invited roles, verdicts in {201, 400, 403}.

    The actor set is every seeded role reachable through the route plus the
    platform admin and the anonymous caller — the same actor vocabulary the
    1.2 lifecycle matrix uses.
    """
    seeded = _provisioned_role_codes()
    assert set(_HTTP_ACTORS) == seeded | {"anonymous", "platform_admin"}
    assert set(_INVITED_ROLES) == seeded | {"superwizard"}
    assert len(HTTP_INVITE_MATRIX) == len(_HTTP_ACTORS) * len(_INVITED_ROLES)
    assert set(HTTP_INVITE_MATRIX) == {
        (actor, invited) for actor in _HTTP_ACTORS for invited in _INVITED_ROLES
    }
    assert {verdict for verdict in HTTP_INVITE_MATRIX.values()} <= {200, 201, 400, 403}


# --- the service-layer matrix -----------------------------------------------


@pytest.mark.parametrize(("inviter", "invited"), sorted(SERVICE_INVITE_MATRIX))
async def test_service_invite_matrix(db, tenant_ctx, inviter: str, invited: str) -> None:
    """Every service-layer cell has one pinned verdict (see SERVICE_INVITE_MATRIX).

    ``allow`` cells additionally assert the invitation carries the role the
    database resolved — the exact role_id accept_invitation binds.
    """
    verdict = SERVICE_INVITE_MATRIX[(inviter, invited)]
    kwargs: dict = {
        "tenant_id": tenant_ctx.tenant_id,
        "email": f"m-{uuid.uuid4().hex[:10]}@test.local",
        "role_code": invited,
        "invited_by": tenant_ctx.user.id,
        "inviter_role_code": inviter,
    }
    if inviter == "platform_admin":
        kwargs["inviter_is_platform_admin"] = True

    if verdict == "unknown_role":
        with pytest.raises(ValidationError):
            await TenantService.invite(db, **kwargs)
        return
    if verdict == "deny":
        with pytest.raises(PermissionDeniedError):
            await TenantService.invite(db, **kwargs)
        return

    invitation = await TenantService.invite(db, **kwargs)
    assert invitation.status == "pending"
    expected_role = (await db.execute(select(Role).where(Role.code == invited))).scalar_one()
    assert invitation.role_id == expected_role.id, (
        "the invitation must carry the database-resolved role id — it is the "
        "exact value accept_invitation binds as the new membership's role"
    )


# --- the HTTP-layer matrix ---------------------------------------------------


async def _db_permission_codes(db, role_code: str) -> set[str]:
    """The role's permission codes read from role_permissions — the same
    source get_tenant_ctx feeds require_permission from on every request."""
    role = (await db.execute(select(Role).where(Role.code == role_code))).scalar_one()
    rows = (
        await db.execute(
            select(Permission.code)
            .join(role_permissions, role_permissions.c.permission_id == Permission.id)
            .where(role_permissions.c.role_id == role.id)
        )
    ).all()
    return {code for (code,) in rows}


async def _matrix_ctx(db, tenant_ctx, actor: str) -> TenantContext:
    """The hand-built TenantContext for one matrix actor.

    Identity mirrors what ``get_current_user``/``get_tenant_ctx`` DB-verify in
    production: role_code is the membership row's role, permission codes come
    from role_permissions (not a cache), and the platform flag rides the
    AuthedUser exactly as the DB-verified value ``require_platform_admin``
    reads.
    """
    role_code = "owner" if actor == "platform_admin" else actor
    perms = await _db_permission_codes(db, role_code)
    return TenantContext(
        session=db,
        user=AuthedUser(
            id=tenant_ctx.user.id,
            tenant_id=tenant_ctx.tenant_id,
            role_code=role_code,
            is_platform_admin=actor == "platform_admin",
            is_active=True,
        ),
        tenant_id=tenant_ctx.tenant_id,
        role_code=role_code,
        permission_codes=perms,
    )


def _matrix_app(db, tenant_ctx, ctx: TenantContext | None):
    """The real app with sessions bound to the test transaction.

    For ``anonymous`` no identity dependency is overridden: the real auth chain
    runs, finds no token and refuses — that refusal IS the cell.
    """
    app = create_app()

    async def _session():
        yield db

    app.dependency_overrides[get_db] = _session
    if ctx is not None:
        app.dependency_overrides[get_tenant_ctx] = lambda: ctx
    return app


@pytest.mark.parametrize(("actor", "invited"), sorted(HTTP_INVITE_MATRIX))
async def test_http_invite_matrix(
    db,
    tenant_ctx,
    app_sessions_on_test_connection,
    actor: str,
    invited: str,
) -> None:
    """Every HTTP cell has one pinned verdict (see HTTP_INVITE_MATRIX).

    201 → the invitation exists and is pending; 403 → no credentials, the
    RBAC gate, or the hierarchy guard; 400 → the invited code resolves to
    no role.
    """
    expected = HTTP_INVITE_MATRIX[(actor, invited)]
    ctx = None if actor == "anonymous" else await _matrix_ctx(db, tenant_ctx, actor)
    app = _matrix_app(db, tenant_ctx, ctx)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/tenants/{tenant_ctx.tenant_id}/invitations",
            json={
                # A plain domain, not a reserved one: pydantic's EmailStr on the
                # request body rejects special-use names (test.local would be a
                # 422, not a matrix verdict).
                "email": f"m-{uuid.uuid4().hex[:10]}@matrix-test.com",
                "role_code": invited,
            },
        )

    assert response.status_code == expected, (
        f"matrix cell (actor={actor!r}, invited={invited!r}): expected "
        f"{expected}, got {response.status_code}: {response.text}"
    )
    if expected == 201:
        body = response.json()
        assert body["status"] == "pending"
        assert body["role_code"] == invited


# --- the two focused facts the matrix depends on -----------------------------


async def test_the_inviter_role_is_read_from_the_membership_row_not_a_claim(db, tenant_ctx) -> None:
    """The hierarchy guard is fed by get_tenant_ctx's DB read, never a JWT claim.

    The identity token pair carries NO role claim at all (_issue_pair mints
    tenant_id / auth_version / is_platform_admin only). This pins the DB side:
    a membership row whose role is staff, fed through get_tenant_ctx, yields
    role_code "staff" — the value the invite route passes to the hierarchy
    guard — even though the AuthedUser's claim-carried field says "owner".
    """
    from fastapi import Request

    staff_role = (await db.execute(select(Role).where(Role.code == "staff"))).scalar_one()
    staff_user = User(
        email=f"staff-{uuid.uuid4().hex[:10]}@test.local",
        password_hash="not-a-real-hash",
        full_name="Staff Member",
    )
    db.add(staff_user)
    await db.flush()
    await db.execute(
        sa.text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(staff_user.id)}
    )
    db.add(TenantUser(tenant_id=tenant_ctx.tenant_id, user_id=staff_user.id, role_id=staff_role.id))
    await db.flush()

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/auth/me",
        "headers": [],
        "query_string": b"",
        "server": ("testserver", 80),
        "scheme": "http",
        "client": ("127.0.0.1", 54321),
    }
    request = Request(scope)
    ctx = await get_tenant_ctx(
        request,
        db,
        AuthedUser(
            id=staff_user.id,
            tenant_id=tenant_ctx.tenant_id,
            # A forged/legacy claim: whatever the token says, the membership
            # row decides.
            role_code="owner",
            is_active=True,
        ),
    )
    assert ctx.role_code == "staff"
    # Closing the loop: the DB-read role feeds the guard, and a staff member
    # cannot even invite a peer staff member.
    with pytest.raises(PermissionDeniedError):
        await TenantService.invite(
            db,
            tenant_id=tenant_ctx.tenant_id,
            email=f"peer-{uuid.uuid4().hex[:10]}@test.local",
            role_code="staff",
            invited_by=staff_user.id,
            inviter_role_code=ctx.role_code,
        )


async def test_accept_binds_the_invitation_role_verbatim(db, tenant_ctx) -> None:
    """The invitation IS the grant: acceptance binds its role_id, unchanged.

    The role was resolved from the roles table at invite time; acceptance must
    never re-interpret it — the membership row the new account receives is the
    exact role the (platform-admin-only, for owner) inviter was authorized to
    grant.
    """
    invitation = await TenantService.invite(
        db,
        tenant_id=tenant_ctx.tenant_id,
        email=f"bind-{uuid.uuid4().hex[:10]}@test.local",
        role_code="manager",
        invited_by=tenant_ctx.user.id,
        inviter_role_code="owner",
    )
    manager_role = (await db.execute(select(Role).where(Role.code == "manager"))).scalar_one()
    assert invitation.role_id == manager_role.id

    user, accepted = await TenantService.accept_invitation(
        db,
        token=invitation.token,
        password="x-strong-pass-1",
        full_name="Invited Manager",
    )
    membership = (
        await db.execute(
            select(TenantUser).where(
                TenantUser.user_id == user.id,
                TenantUser.tenant_id == tenant_ctx.tenant_id,
            )
        )
    ).scalar_one()
    assert membership.role_id == invitation.role_id
    assert accepted.status == "accepted"
    # The invitation-born account is born verified (inbox proof via the token).
    assert user.email_verified is True
