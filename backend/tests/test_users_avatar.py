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
