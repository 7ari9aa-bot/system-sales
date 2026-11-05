"""A staff user's own profile picture.

The picture belongs to the account, not to a tenant: one user can sit in several
workspaces, and `users` is a global table. So the write is "my own row", the
bytes are screened before anything reaches the bucket, and the read is a
short-lived signed URL rather than a permanent public one — a person's face
should not get a cached, unguessable-but-forever URL.

The screening tests are pure; the round trip is a real row under the tenant-bound
session, because a column that only exists in a test double is not a column.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm.exc import StaleDataError

from app.core.errors import PayloadTooLargeError, ValidationError
from app.modules.identity import avatar
from app.modules.identity.models import User
from app.modules.identity.routers._deps import bind_tenant_user
from app.modules.identity.services.user import UserService

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
JPEG = b"\xff\xd8\xff" + b"\x00" * 24
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 24


# ------------------------------------------------------------- screening ----


def test_the_three_accepted_types_are_accepted_for_their_own_bytes():
    for content_type, data in (("image/png", PNG), ("image/jpeg", JPEG), ("image/webp", WEBP)):
        assert avatar.screen(content_type, data) == content_type


def test_a_type_the_browser_claims_is_not_believed():
    """The declared type and the bytes must agree.

    A file renamed `.png` holding a GIF (or an SVG, which can carry script) is
    the classic upload spoof, so the signature decides and the header only picks
    which signature to check.
    """
    with pytest.raises(ValidationError):
        avatar.screen("image/png", JPEG)


@pytest.mark.parametrize("content_type", ["image/gif", "image/svg+xml", "application/pdf", ""])
def test_an_unsupported_kind_is_refused_before_the_bucket_is_touched(content_type):
    with pytest.raises(ValidationError):
        avatar.screen(content_type, PNG)


def test_the_limit_is_the_request_size_not_the_file_name():
    with pytest.raises(PayloadTooLargeError):
        avatar.screen("image/png", b"\x89PNG\r\n\x1a\n" + b"\x00" * avatar.MAX_AVATAR_BYTES)


def test_empty_bytes_are_not_a_picture():
    for data in (b"", b"\x89PNG\r\n\x1a\n"):
        with pytest.raises(ValidationError):
            avatar.screen("image/png", data)


# ---------------------------------------------------------------- reading ----


class _Storage:
    def __init__(self, *, configured=True, raises=None):
        self.configured = configured
        self.calls = []
        self._raises = raises

    def signed_url(self, key, *, expires_in=None):
        self.calls.append((key, expires_in))
        if self._raises:
            raise self._raises
        return f"https://read.example/{key}?e={expires_in}"


def test_a_stored_key_becomes_a_short_lived_read_url():
    storage = _Storage()
    url = avatar.read_url("s3://avatars/u-1/ab.png", storage=storage)
    assert url == "https://read.example/avatars/u-1/ab.png?e=86400"
    assert storage.calls == [("avatars/u-1/ab.png", 86400)]


def test_an_account_without_a_picture_has_no_url_to_read():
    for value in (None, ""):
        assert avatar.read_url(value, storage=_Storage()) is None


def test_a_url_that_is_not_our_object_is_never_resigned():
    """Only our own `s3://` keys are ours to sign.

    Anything else (a hand-inserted external link) is passed through rather than
    turned into a signature request for a key that does not exist.
    """
    storage = _Storage()
    assert avatar.read_url("https://elsewhere.example/x.png", storage=storage) == (
        "https://elsewhere.example/x.png"
    )
    assert storage.calls == []


def test_a_picture_cannot_be_read_when_storage_is_down():
    """The list falls back to the account's letters instead of a broken image."""
    unconfigured = _Storage(configured=False)
    broken = _Storage(raises=RuntimeError())
    assert avatar.read_url("s3://avatars/u-1/ab.png", storage=unconfigured) is None
    assert avatar.read_url("s3://avatars/u-1/ab.png", storage=broken) is None


# --------------------------------------------------------------- writing ----


async def test_the_avatar_columns_round_trip_through_the_service(db, tenant_ctx) -> None:
    """The column exists in the real schema and the service writes it.

    The session is bound as the account doing the writing: `users` is RLS-
    protected by a self-update policy, so an unbound session is not a normal
    state for this write — the request path binds it.
    """
    user_id = uuid.uuid4()
    db.add(
        User(
            id=user_id,
            email=f"avatar-{user_id.hex[:8]}@example.com",
            full_name="Avatar Tester",
            password_hash="x" * 60,
        )
    )
    await db.flush()
    await bind_tenant_user(db, user_id)

    await UserService.set_avatar_url(db, user_id, f"s3://avatars/{user_id}/new.png")
    stored = (await db.execute(select(User.avatar_url).where(User.id == user_id))).scalar_one()
    assert stored == f"s3://avatars/{user_id}/new.png"

    await UserService.clear_avatar_url(db, user_id)
    cleared = (await db.execute(select(User.avatar_url).where(User.id == user_id))).scalar_one()
    assert cleared is None


async def test_one_account_cannot_write_another_accounts_picture(db, tenant_ctx) -> None:
    """The database, not the router, is what makes "my avatar" mean mine.

    The endpoint never accepts a user id, and that is easy to write and easy to
    change. This policy is the second lock: a session bound as one account
    matches zero rows when it tries to update another's.
    """
    other_id = uuid.uuid4()
    db.add(
        User(
            id=other_id,
            email=f"avatar-other-{other_id.hex[:8]}@example.com",
            full_name="Someone Else",
            password_hash="x" * 60,
        )
    )
    await db.flush()
    await bind_tenant_user(db, tenant_ctx.user.id)

    with pytest.raises(StaleDataError):
        async with db.begin_nested():
            await UserService.set_avatar_url(db, other_id, "s3://avatars/other/steal.png")

    kept = (await db.execute(select(User.avatar_url).where(User.id == other_id))).scalar_one()
    assert kept is None


# ------------------------------------------------------------------ HTTP ----

import hashlib  # noqa: E402

from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core.storage import StoredMedia  # noqa: E402
from app.main import create_app  # noqa: E402
from app.modules.identity.deps import (  # noqa: E402
    AuthedUser,
    TenantContext,
    get_db,
    get_tenant_ctx,
)
from app.modules.identity.routers import users as users_router_module  # noqa: E402

PNG_KEY_SUFFIX = hashlib.sha256(PNG).hexdigest()[:8]


class _FakeStorage:
    def __init__(self, *, configured=True):
        self.configured = configured
        self.stored: list[tuple[str, bytes]] = []

    async def store(self, media, *, prefix, original_url=None):
        self.stored.append((prefix, media.data))
        if not self.configured:
            return StoredMedia(url="", content_type=None, bytes_written=0, durable=False)
        key = f"{prefix}/{media.checksum[:8]}.png"
        return StoredMedia(
            url=f"https://bucket.example/{key}",
            content_type=media.content_type,
            bytes_written=len(media.data),
            durable=True,
            storage_key=key,
            checksum=media.checksum,
        )

    def signed_url(self, key, *, expires_in=None):
        return f"https://read.example/{key}?e={expires_in}"


def _client(db, monkeypatch, storage: _FakeStorage, *, user_id, tenant_id):
    """The real routes over the real session, with auth and storage swapped.

    The auth override also binds `app.user_id`, because that binding is what the
    real dependency does and the RLS self-update policy on `users` reads it.
    """
    app = create_app()
    monkeypatch.setattr(users_router_module, "get_storage", lambda: storage)
    # The read paths sign through avatar.py's own reference, so both seams get
    # the fake: patching only the router would test a storage object the GET
    # never uses.
    monkeypatch.setattr(avatar, "get_storage", lambda: storage)
    ctx = TenantContext(
        session=db,
        user=AuthedUser(id=user_id, tenant_id=tenant_id, role_code="owner"),
        tenant_id=tenant_id,
        role_code="owner",
        permission_codes=set(),
    )

    async def _ctx():
        await bind_tenant_user(db, user_id)
        return ctx

    async def _session():
        yield db

    app.dependency_overrides[get_tenant_ctx] = _ctx
    app.dependency_overrides[get_db] = _session
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test", timeout=20)


@pytest.fixture
def account(db, tenant_ctx):
    """The signed-in account is a real row: the avatar write updates it."""
    return tenant_ctx.user.id, tenant_ctx.tenant_id


async def test_put_stores_the_picture_and_the_row_points_at_its_key(
    db, tenant_ctx, account, monkeypatch
):
    user_id, tenant_id = account
    storage = _FakeStorage()
    async with _client(db, monkeypatch, storage, user_id=user_id, tenant_id=tenant_id) as client:
        response = await client.put(
            "/api/v1/users/me/avatar", content=PNG, headers={"content-type": "image/png"}
        )
    key = f"avatars/{user_id}/{PNG_KEY_SUFFIX}.png"
    assert response.status_code == 200, response.text
    assert storage.stored == [(f"avatars/{user_id}", PNG)]
    assert response.json()["avatar_url"] == f"https://read.example/{key}?e=86400"
    stored = (await db.execute(select(User.avatar_url).where(User.id == user_id))).scalar_one()
    assert stored == f"s3://{key}"


async def test_put_refuses_bytes_that_are_not_the_declared_type(
    db, tenant_ctx, account, monkeypatch
):
    user_id, tenant_id = account
    storage = _FakeStorage()
    async with _client(db, monkeypatch, storage, user_id=user_id, tenant_id=tenant_id) as client:
        response = await client.put(
            "/api/v1/users/me/avatar", content=JPEG, headers={"content-type": "image/png"}
        )
    assert response.status_code == 400, response.text
    assert storage.stored == []


async def test_put_refuses_a_type_no_avatar_can_be(db, tenant_ctx, account, monkeypatch):
    user_id, tenant_id = account
    storage = _FakeStorage()
    async with _client(db, monkeypatch, storage, user_id=user_id, tenant_id=tenant_id) as client:
        response = await client.put(
            "/api/v1/users/me/avatar", content=PNG, headers={"content-type": "image/svg+xml"}
        )
    assert response.status_code == 400, response.text
    assert storage.stored == []


async def test_put_refuses_more_than_the_limit_without_storing_it(
    db, tenant_ctx, account, monkeypatch
):
    """The cap is applied while streaming, so a lying Content-Length loses."""
    user_id, tenant_id = account
    storage = _FakeStorage()
    oversized = PNG + b"\x00" * avatar.MAX_AVATAR_BYTES
    async with _client(db, monkeypatch, storage, user_id=user_id, tenant_id=tenant_id) as client:
        response = await client.put(
            "/api/v1/users/me/avatar", content=oversized, headers={"content-type": "image/png"}
        )
    assert response.status_code == 413, response.text
    assert storage.stored == []


async def test_put_says_storage_is_unavailable_instead_of_losing_the_picture(
    db, tenant_ctx, account, monkeypatch
):
    user_id, tenant_id = account
    storage = _FakeStorage(configured=False)
    async with _client(db, monkeypatch, storage, user_id=user_id, tenant_id=tenant_id) as client:
        response = await client.put(
            "/api/v1/users/me/avatar", content=PNG, headers={"content-type": "image/png"}
        )
    assert response.status_code == 503, response.text
    stored = (await db.execute(select(User.avatar_url).where(User.id == user_id))).scalar_one()
    assert stored is None


async def test_delete_forgets_the_picture(db, tenant_ctx, account, monkeypatch):
    user_id, tenant_id = account
    async with _client(
        db, monkeypatch, _FakeStorage(), user_id=user_id, tenant_id=tenant_id
    ) as client:
        await client.put(
            "/api/v1/users/me/avatar", content=PNG, headers={"content-type": "image/png"}
        )
        cleared = await client.delete("/api/v1/users/me/avatar")
    assert cleared.status_code == 200, cleared.text
    assert cleared.json() == {"avatar_url": None}
    stored = (await db.execute(select(User.avatar_url).where(User.id == user_id))).scalar_one()
    assert stored is None


async def test_my_profile_reads_the_picture_back_as_a_signed_url(
    db, tenant_ctx, account, monkeypatch
):
    user_id, tenant_id = account
    async with _client(
        db, monkeypatch, _FakeStorage(), user_id=user_id, tenant_id=tenant_id
    ) as client:
        await client.put(
            "/api/v1/users/me/avatar", content=PNG, headers={"content-type": "image/png"}
        )
        profile = await client.get("/api/v1/users/me")
    body = profile.json()
    assert profile.status_code == 200, profile.text
    assert body["avatar_url"].startswith(f"https://read.example/avatars/{user_id}/")
    assert "e=86400" in body["avatar_url"]
