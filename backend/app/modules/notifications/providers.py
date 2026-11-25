"""Provider interface for email and push notification delivery.

The notification service stages ``notification.email`` / ``notification.push``
events in the outbox.  The delivery worker (``app.workers.notification_delivery_worker``)
consumes them and hands each to a provider adapter that talks to the outside
world.

Protocols (``EmailProvider``, ``PushProvider``) are the boundary.  Adapters:

* ``ResendEmailProvider`` — production email adapter for Resend
  (https://resend.com).  No real API key is stored here; the key comes from
  ``settings.resend_api_key`` at call time, exactly like the existing
  ``identity/email_delivery.py`` adapter.

* ``FakeEmailProvider`` / ``FakePushProvider`` — in-memory fakes for tests.
  They record every call so a test can assert "the email was sent" without
  touching the network.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

logger = logging.getLogger(__name__)

_RESEND_EMAILS_URL = "https://api.resend.com/emails"


class EmailProvider(Protocol):
    """Boundary for sending a notification email."""

    async def send(self, *, to: str, subject: str, body: str) -> None: ...


class PushProvider(Protocol):
    """Boundary for sending a push notification."""

    async def send(self, *, token: str, title: str, body: str) -> None: ...


# ──────────────────────────────────────────────────────────────────────
# Resend email adapter (production)
# ──────────────────────────────────────────────────────────────────────


class ResendEmailProvider:
    """Minimal Resend adapter for notification emails.

    Uses ``settings.resend_api_key`` and ``settings.email_from`` from the app
    config, the same credentials the account-recovery adapter
    (``identity/email_delivery.py``) uses.  When delivery is not configured the
    call is a no-op so the worker can still drain the outbox without errors.
    """

    def __init__(self, client_factory: type[httpx.AsyncClient] | None = None) -> None:
        self._client_factory = client_factory or httpx.AsyncClient

    async def send(self, *, to: str, subject: str, body: str) -> None:
        from app.core.config import get_settings

        settings = get_settings()
        if not settings.auth_email_delivery_configured:
            logger.debug("resend.not_configured — skipping notification email to %s", to)
            return
        payload: dict[str, Any] = {
            "from": settings.email_from,
            "to": [to],
            "subject": subject,
            "text": body,
        }
        try:
            async with self._client_factory(timeout=httpx.Timeout(10.0, connect=3.0)) as client:
                response = await client.post(
                    _RESEND_EMAILS_URL,
                    headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise RuntimeError("resend network error") from exc
        if not response.is_success:
            raise RuntimeError(f"resend rejected delivery (http {response.status_code})")


# ──────────────────────────────────────────────────────────────────────
# Fake providers (tests)
# ──────────────────────────────────────────────────────────────────────


@dataclass
class FakeEmailProvider:
    """In-memory email provider for tests.  Records every send."""

    sent: list[dict[str, str]] = field(default_factory=list)

    async def send(self, *, to: str, subject: str, body: str) -> None:
        self.sent.append({"to": to, "subject": subject, "body": body})


@dataclass
class FakePushProvider:
    """In-memory push provider for tests.  Records every send."""

    sent: list[dict[str, str]] = field(default_factory=list)

    async def send(self, *, token: str, title: str, body: str) -> None:
        self.sent.append({"token": token, "title": title, "body": body})


# ──────────────────────────────────────────────────────────────────────
# FCM push adapter (production)
# ──────────────────────────────────────────────────────────────────────

_FCM_URL = "https://fcm.googleapis.com/fcm/send"


class FCMPushProvider:
    """Minimal Firebase Cloud Messaging adapter for push notifications.

    Mirrors the shape of ``ResendEmailProvider``: no real API key is stored in
    the class; the server key comes from ``settings.fcm_server_key`` at call
    time.  When FCM is not configured the call is a no-op so the worker can
    still drain the outbox without errors.
    """

    def __init__(self, client_factory: type[httpx.AsyncClient] | None = None) -> None:
        self._client_factory = client_factory or httpx.AsyncClient

    async def send(self, *, token: str, title: str, body: str) -> None:
        from app.core.config import get_settings

        settings = get_settings()
        if not settings.fcm_server_key.strip():
            logger.debug("fcm.not_configured — skipping push to %s", token)
            return
        payload: dict[str, Any] = {
            "to": token,
            "notification": {"title": title, "body": body},
        }
        try:
            async with self._client_factory(timeout=httpx.Timeout(10.0, connect=3.0)) as client:
                response = await client.post(
                    _FCM_URL,
                    headers={
                        "Authorization": f"key={settings.fcm_server_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise RuntimeError("fcm network error") from exc
        if not response.is_success:
            raise RuntimeError(f"fcm rejected delivery (http {response.status_code})")


# ──────────────────────────────────────────────────────────────────────
# Fake push provider (tests) — kept after FCM so the import order in tests
# that reference both is stable.
# ──────────────────────────────────────────────────────────────────────
