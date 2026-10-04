"""Durable delivery of account-security email through Resend.

Reset tokens are validated from their hash in Postgres. The encrypted copy is
used only by this worker to retry delivery until expiry or a terminal failure.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import httpx
from sqlalchemy import or_, select, update

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.secrets import get_envelope_store
from app.modules.identity.models import PasswordResetToken, User

logger = logging.getLogger(__name__)

_RESEND_EMAILS_URL = "https://api.resend.com/emails"
_MAX_ATTEMPTS = 8
_LEASE_SECONDS = 60


@dataclass(frozen=True, slots=True)
class _Delivery:
    id: uuid.UUID
    email: str
    encrypted_token: str
    attempts: int


class EmailDeliveryError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class ResendEmailSender:
    """Minimal server-side Resend adapter for account recovery messages."""

    def __init__(self, client_factory=httpx.AsyncClient) -> None:
        self._client_factory = client_factory

    async def send_password_reset(
        self, *, delivery_id: uuid.UUID, recipient: str, token: str
    ) -> None:
        settings = get_settings()
        if not settings.auth_email_delivery_configured:
            raise EmailDeliveryError("email delivery is not configured", retryable=True)

        reset_url = (
            f"{settings.frontend_public_url.rstrip('/')}/reset-password"
            f"#token={quote(token, safe='')}"
        )
        html = (
            "<!doctype html><html><body>"
            "<h1>Reset your password</h1>"
            "<p>We received a request to reset the password for your account.</p>"
            f'<p><a href="{reset_url}">Choose a new password</a></p>'
            "<p>This link expires in one hour. If you did not request this, "
            "you can ignore this email.</p>"
            "</body></html>"
        )
        payload = {
            "from": settings.email_from,
            "to": [recipient],
            "subject": "Reset your password",
            "html": html,
            "text": (
                "We received a request to reset your password. "
                f"Choose a new password here: {reset_url} "
                "This link expires in one hour. If you did not request this, "
                "you can ignore this email."
            ),
        }
        try:
            async with self._client_factory(
                timeout=httpx.Timeout(10.0, connect=3.0)
            ) as client:
                response = await client.post(
                    _RESEND_EMAILS_URL,
                    headers={
                        "Authorization": f"Bearer {settings.resend_api_key}",
                        # Retries after a network timeout must not send the
                        # same reset message more than once.
                        "Idempotency-Key": str(delivery_id),
                    },
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise EmailDeliveryError("resend network error", retryable=True) from exc

        if response.is_success:
            return
        retryable = response.status_code in {408, 409, 425, 429} or response.status_code >= 500
        # Do not persist or log the provider response body; it may echo
        # recipient data or credential-adjacent request details.
        raise EmailDeliveryError(
            f"resend rejected delivery (http {response.status_code})",
            retryable=retryable,
        )


class PasswordResetEmailDelivery:
    """Leased, at-least-once email queue consumer started by SchedulerWorker."""

    @staticmethod
    async def run_once(*, sender: ResendEmailSender | None = None) -> int:
        settings = get_settings()
        if not settings.auth_email_delivery_configured:
            return 0

        now = datetime.now(UTC)
        delivery: _Delivery | None = None
        async with SessionLocal() as session:
            async with session.begin():
                # Expired entries retain only a hash and metadata after cleanup.
                await session.execute(
                    update(PasswordResetToken)
                    .where(
                        PasswordResetToken.expires_at <= now,
                        PasswordResetToken.consumed_at.is_(None),
                    )
                    .values(
                        consumed_at=now,
                        encrypted_token="",
                        lease_expires_at=None,
                    )
                )
                candidate = (
                    await session.execute(
                        select(PasswordResetToken, User.email)
                        .join(User, User.id == PasswordResetToken.user_id)
                        .where(
                            User.is_active.is_(True),
                            PasswordResetToken.sent_at.is_(None),
                            PasswordResetToken.consumed_at.is_(None),
                            PasswordResetToken.delivery_failed_at.is_(None),
                            PasswordResetToken.expires_at > now,
                            PasswordResetToken.next_attempt_at <= now,
                            or_(
                                PasswordResetToken.lease_expires_at.is_(None),
                                PasswordResetToken.lease_expires_at <= now,
                            ),
                        )
                        .order_by(PasswordResetToken.requested_at)
                        .with_for_update(of=PasswordResetToken, skip_locked=True)
                        .limit(1)
                    )
                ).one_or_none()
                if candidate is None:
                    return 0
                row, email = candidate
                row.attempts += 1
                row.lease_expires_at = now + timedelta(seconds=_LEASE_SECONDS)
                delivery = _Delivery(
                    id=row.id,
                    email=email,
                    encrypted_token=row.encrypted_token,
                    attempts=row.attempts,
                )

        assert delivery is not None
        try:
            token = get_envelope_store().decrypt(delivery.encrypted_token).value
            await (sender or ResendEmailSender()).send_password_reset(
                delivery_id=delivery.id,
                recipient=delivery.email,
                token=token,
            )
        except EmailDeliveryError as exc:
            await PasswordResetEmailDelivery._record_failure(delivery, exc)
            logger.warning(
                "auth.password_reset_email_failed delivery_id=%s reason=%s",
                delivery.id,
                str(exc),
            )
            return 1
        except Exception:  # noqa: BLE001 — keep poller alive on corrupt ciphertext/provider bugs
            await PasswordResetEmailDelivery._record_failure(
                delivery,
                EmailDeliveryError("email delivery internal error", retryable=False),
            )
            logger.exception("auth.password_reset_email_internal_error delivery_id=%s", delivery.id)
            return 1

        finished_at = datetime.now(UTC)
        async with SessionLocal() as session:
            async with session.begin():
                row = (
                    await session.execute(
                        select(PasswordResetToken)
                        .where(PasswordResetToken.id == delivery.id)
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if row is not None:
                    row.sent_at = finished_at
                    row.encrypted_token = ""
                    row.lease_expires_at = None
                    row.last_error = None
        return 1

    @staticmethod
    async def _record_failure(delivery: _Delivery, error: EmailDeliveryError) -> None:
        now = datetime.now(UTC)
        async with SessionLocal() as session:
            async with session.begin():
                row = (
                    await session.execute(
                        select(PasswordResetToken)
                        .where(PasswordResetToken.id == delivery.id)
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                if row is None:
                    return
                row.lease_expires_at = None
                row.last_error = str(error)[:255]
                if not error.retryable or row.attempts >= _MAX_ATTEMPTS:
                    row.delivery_failed_at = now
                    row.encrypted_token = ""
                    return
                delay_seconds = min(15 * (2 ** max(row.attempts - 1, 0)), 900)
                row.next_attempt_at = now + timedelta(seconds=delay_seconds)
