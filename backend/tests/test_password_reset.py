from __future__ import annotations

import hashlib
import json
import uuid
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import select
from starlette.requests import Request

from app.core.errors import PermissionDeniedError, ValidationError
from app.core.security import hash_password, verify_password
from app.modules.identity import email_delivery
from app.modules.identity.deps import get_current_user
from app.modules.identity.models import PasswordResetToken, RefreshToken, User
from app.modules.identity.service import AuthService


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/auth/me",
            "raw_path": b"/api/v1/auth/me",
            "query_string": b"",
            "headers": [],
            "scheme": "http",
            "server": ("test", 80),
            "client": ("127.0.0.1", 12345),
        }
    )


def test_new_password_hashes_distinguish_values_after_bcrypt_limit() -> None:
    password = "a" * 72 + "first"
    stored_hash = hash_password(password)
    assert verify_password(password, stored_hash)
    assert not verify_password("a" * 72 + "other", stored_hash)


async def test_password_reset_is_single_use_and_revokes_sessions(db) -> None:
    email = f"reset-{uuid.uuid4().hex[:8]}@test.local"
    user, _tenant = await AuthService.register(
        db,
        tenant_name="Reset Tenant",
        tenant_slug=f"reset-{uuid.uuid4().hex[:8]}",
        email=email,
        password="original-password-1",
        full_name="Reset Owner",
    )
    pair, _logged_in, _tenant_id = await AuthService.login(
        db, email=email, password="original-password-1"
    )

    await AuthService.request_password_reset(db, email=email)
    reset_row = (
        await db.execute(select(PasswordResetToken).where(PasswordResetToken.user_id == user.id))
    ).scalar_one()
    token = email_delivery.get_envelope_store().decrypt(reset_row.encrypted_token).value
    assert reset_row.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert token not in reset_row.encrypted_token

    await AuthService.reset_password(db, token=token, password="replacement-password-2")
    await db.refresh(user)
    await db.refresh(reset_row)
    assert verify_password("replacement-password-2", user.password_hash)
    assert user.auth_version == 1
    assert reset_row.consumed_at is not None
    assert reset_row.encrypted_token == ""

    refresh_rows = (
        (await db.execute(select(RefreshToken).where(RefreshToken.user_id == user.id)))
        .scalars()
        .all()
    )
    assert refresh_rows
    assert all(row.revoked_at is not None for row in refresh_rows)

    # Access JWTs are checked against auth_version on every protected request.
    with pytest.raises(PermissionDeniedError, match="session revoked"):
        await get_current_user(_request(), db, f"Bearer {pair.access_token}")

    with pytest.raises(ValidationError, match="invalid or expired"):
        await AuthService.reset_password(db, token=token, password="another-password-3")


async def test_password_reset_request_does_not_create_rows_for_unknown_email(db) -> None:
    email = f"unknown-{uuid.uuid4().hex[:8]}@test.local"
    await AuthService.request_password_reset(db, email=email)
    assert (
        await db.execute(
            select(PasswordResetToken.id)
            .join(User, User.id == PasswordResetToken.user_id)
            .where(User.email == email)
        )
    ).scalars().all() == []


async def test_resend_message_uses_fragment_token_and_idempotency_key(monkeypatch) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = request.headers
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "mail_123"})

    def client_factory(**kwargs):
        return httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            **kwargs,
        )

    monkeypatch.setattr(
        email_delivery,
        "get_settings",
        lambda: SimpleNamespace(
            auth_email_delivery_configured=True,
            frontend_public_url="https://sales.example.com",
            email_from="security@sales.example.com",
            resend_api_key="test-key",
        ),
    )
    delivery_id = uuid.uuid4()
    await email_delivery.ResendEmailSender(client_factory).send_password_reset(
        delivery_id=delivery_id,
        recipient="user@example.com",
        token="safe_token-123",
    )

    assert captured["headers"]["authorization"] == "Bearer test-key"
    assert captured["headers"]["idempotency-key"] == str(delivery_id)
    assert "#token=safe_token-123" in captured["payload"]["text"]
    assert "token=safe_token-123" not in captured["payload"]["text"].split("#", 1)[0]


async def test_email_worker_waits_without_provider_configuration(monkeypatch) -> None:
    monkeypatch.setattr(
        email_delivery,
        "get_settings",
        lambda: SimpleNamespace(auth_email_delivery_configured=False),
    )
    assert await email_delivery.PasswordResetEmailDelivery.run_once() == 0
