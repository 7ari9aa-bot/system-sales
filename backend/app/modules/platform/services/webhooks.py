"""Webhook registration and outbound delivery services."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select

from app.core.config import get_settings
from app.core.errors import NotFoundError, ValidationError
from app.core.events.writer import add_outbox_event
from app.modules.platform.models import WebhookDelivery, WebhookEndpoint

from .audit import AuditService


def _ssrf_guard(url: str) -> None:
    """Late-bound SSRF guard: resolves THROUGH the aggregator
    (platform.service) because the delivery tests patch it there. This module
    is imported BY that aggregator, so a module-level binding would dodge the
    patch after the modular split — the lazy import is the late binding."""
    from app.modules.platform import service as _platform_service

    _platform_service.assert_public_url(url)

WEBHOOK_STREAM = "platform.events"


class WebhookService:
    """The tenant-owned outbound webhook registry (§148).

    Lifecycle contract, fail-closed by construction:

    * ``register_endpoint`` mints a signing secret that the caller receives
      EXACTLY once (in the register response) — no read path ever returns a
      secret again, so a leaked response cannot be salvaged from the API.
    * ``rotate_endpoint_secret`` replaces the secret and returns the NEW one
      exactly once. ``webhooks.secret`` is a single column, so there is no
      dual-acceptance grace period: the old secret stops verifying the moment
      the new one is minted, and the rotate response is the only place the new
      value exists.
    * ``deactivate_endpoint`` is a soft delete (``is_active=False``): the
      dispatcher skips inactive endpoints without contacting them, and the
      delivery ledger keeps its rows — nothing disappears.
    * Every registry mutation is audited (§66) with the acting user attached.
    """

    @staticmethod
    async def register_endpoint(
        session: Any,
        tenant_id: uuid.UUID,
        *,
        url: str,
        events: list[str],
        actor_user_id: uuid.UUID | None = None,
    ) -> WebhookEndpoint:
        # S6: reject internal/metadata targets at registration time so a tenant
        # cannot turn our delivery worker into an SSRF proxy. Re-validated at
        # send time in WebhookDispatcher.deliver (DNS rebinding).
        _ssrf_guard(url)
        endpoint = WebhookEndpoint(
            tenant_id=tenant_id,
            url=url,
            secret=uuid.uuid4().hex + uuid.uuid4().hex,
            events=events,
        )
        session.add(endpoint)
        await session.flush()
        # §66: registration is a credential-bearing configuration act — the
        # audit row carries the target and event filter, never the secret.
        await AuditService.write(
            session,
            tenant_id,
            actor_user_id,
            "webhook_endpoint.registered",
            "webhook_endpoint",
            str(endpoint.id),
            after={"url": url, "events": list(events)},
        )
        return endpoint

    @staticmethod
    async def _load_endpoint(
        session: Any, tenant_id: uuid.UUID, endpoint_id: uuid.UUID
    ) -> WebhookEndpoint:
        endpoint = (
            await session.execute(
                select(WebhookEndpoint).where(
                    WebhookEndpoint.tenant_id == tenant_id,
                    WebhookEndpoint.id == endpoint_id,
                )
            )
        ).scalar_one_or_none()
        if endpoint is None:
            # Tenant-scoped on purpose: another tenant's endpoint id is a 404,
            # not a 403 — its existence is not the caller's business.
            raise NotFoundError("webhook endpoint not found")
        return endpoint

    @staticmethod
    async def list_endpoints(session: Any, tenant_id: uuid.UUID) -> list[WebhookEndpoint]:
        """Every endpoint the tenant registered, oldest first.

        The read half of the registry surface. Unpaginated on the same grounds
        as the flags list: endpoints are tenant configuration, not a growing
        user dataset. ``(created_at, id)`` is a total order, so repeated reads
        return the rows in one stable sequence.
        """
        rows = (
            await session.execute(
                select(WebhookEndpoint)
                .where(WebhookEndpoint.tenant_id == tenant_id)
                .order_by(WebhookEndpoint.created_at, WebhookEndpoint.id)
            )
        ).scalars()
        return list(rows.all())

    @staticmethod
    async def rotate_endpoint_secret(
        session: Any,
        tenant_id: uuid.UUID,
        endpoint_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID | None = None,
    ) -> WebhookEndpoint:
        """Replace the endpoint's signing secret; return the row with it.

        Fail-closed on purpose: the new secret is minted server-side and never
        sent anywhere but this return value (the router responds with it once).
        The old secret is dropped in the same flush — a receiver still holding
        it fails signature verification from the next delivery on, which is
        the documented cost of rotation (no dual-secret grace window exists in
        the single-column model).
        """
        endpoint = await WebhookService._load_endpoint(session, tenant_id, endpoint_id)
        endpoint.secret = uuid.uuid4().hex + uuid.uuid4().hex
        await session.flush()
        await AuditService.write(
            session,
            tenant_id,
            actor_user_id,
            "webhook_endpoint.secret_rotated",
            "webhook_endpoint",
            str(endpoint.id),
            after={"active": bool(endpoint.is_active)},
        )
        return endpoint

    @staticmethod
    async def deactivate_endpoint(
        session: Any,
        tenant_id: uuid.UUID,
        endpoint_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID | None = None,
    ) -> WebhookEndpoint:
        """Soft delete: ``is_active=False`` so deliveries stop targeting it.

        Never a hard DELETE — ``webhook_deliveries`` rows reference the
        endpoint and the delivery history is the audit trail (§24: nothing
        disappears). Idempotent: an already-inactive endpoint is returned
        unchanged and writes no second audit row.
        """
        endpoint = await WebhookService._load_endpoint(session, tenant_id, endpoint_id)
        if endpoint.is_active:
            endpoint.is_active = False
            await session.flush()
            await AuditService.write(
                session,
                tenant_id,
                actor_user_id,
                "webhook_endpoint.deactivated",
                "webhook_endpoint",
                str(endpoint.id),
                before={"active": True},
                after={"active": False},
            )
        return endpoint

    @staticmethod
    async def enqueue(
        session: Any,
        tenant_id: uuid.UUID,
        *,
        event_name: str,
        payload: dict,
    ) -> list[WebhookDelivery]:
        endpoints = (
            (
                await session.execute(
                    select(WebhookEndpoint).where(
                        WebhookEndpoint.tenant_id == tenant_id,
                        WebhookEndpoint.is_active.is_(True),
                    )
                )
            )
            .scalars()
            .all()
        )
        deliveries = []
        for endpoint in endpoints:
            if endpoint.events and event_name not in endpoint.events:
                continue
            delivery = WebhookDelivery(
                tenant_id=tenant_id,
                webhook_id=endpoint.id,
                event_name=event_name,
                payload={"event": event_name, "data": payload},
                status="queued",
                next_retry_at=datetime.now(UTC),
            )
            session.add(delivery)
            deliveries.append(delivery)
        await session.flush()
        for delivery in deliveries:
            await add_outbox_event(
                session,
                aggregate_type="webhook",
                aggregate_id=delivery.id,
                event_type="webhook.deliver",
                tenant_id=tenant_id,
                payload={"delivery_id": str(delivery.id)},
            )
        return deliveries


class WebhookDispatcher:
    """Delivers signed outbound webhooks (§148 replay protection).

    Every delivery carries three SalesOS headers:

        X-SalesOS-Signature:  sha256=HMAC-SHA256(secret, "<timestamp>.<body>")
        X-SalesOS-Timestamp:  unix seconds (UTC) — INSIDE the signed input
        X-SalesOS-Delivery-Id: the webhook_deliveries row id (dedupe key)

    Verification recipe for receivers:

        1. Read the three headers. Reject when
           |now - X-SalesOS-Timestamp| > 300 seconds (replay window).
        2. Recompute HMAC-SHA256(secret, "<timestamp>.<raw body>") over the
           RAW request bytes and compare against the signature (after the
           "sha256=" prefix) with hmac.compare_digest. Because the timestamp
           is covered by the signature, a captured delivery cannot be replayed
           later with a refreshed timestamp, and the body cannot be tampered
           with without breaking the signature.
        3. Dedupe on X-SalesOS-Delivery-Id: a delivery may arrive more than
           once (at-least-once retries); process each id at most once.

    A secret is issued per endpoint by WebhookService.register_endpoint.
    """

    TIMEOUT = 15.0

    @classmethod
    def sign(cls, secret: str, body: bytes, timestamp: str | int) -> str:
        """§148: the unix-seconds timestamp is part of the signed input."""
        covered = f"{timestamp}.".encode() + body
        return "sha256=" + hmac.new(secret.encode(), covered, hashlib.sha256).hexdigest()

    @classmethod
    async def deliver(
        cls,
        session: Any,
        tenant_id: uuid.UUID,
        delivery_id: uuid.UUID,
        *,
        _client: httpx.AsyncClient | None = None,
    ) -> WebhookDelivery | None:
        delivery = (
            await session.execute(
                select(WebhookDelivery).where(
                    WebhookDelivery.tenant_id == tenant_id,
                    WebhookDelivery.id == delivery_id,
                )
            )
        ).scalar_one_or_none()
        if delivery is None or delivery.status in ("delivered", "dead"):
            return delivery

        endpoint = (
            await session.execute(
                select(WebhookEndpoint).where(WebhookEndpoint.id == delivery.webhook_id)
            )
        ).scalar_one_or_none()
        if endpoint is None or not endpoint.is_active:
            delivery.status = "failed"
            delivery.last_error = "endpoint missing or inactive"
            return delivery

        # S6: re-validate at SEND time. A hostname that resolved to a public
        # address at registration can be re-pointed at an internal one later
        # (DNS rebinding) — the check has to happen on the request that
        # actually goes out, not only on the one that stored the URL.
        try:
            _ssrf_guard(endpoint.url)
        except ValidationError as exc:
            delivery.status = "dead"
            delivery.last_error = f"endpoint url rejected: {exc.message}"
            return delivery

        body = json.dumps(delivery.payload, default=str).encode()
        # §148: the timestamp rides INSIDE the signature (replay protection)
        # and the delivery row id lets receivers dedupe redeliveries.
        timestamp = str(int(datetime.now(UTC).timestamp()))
        headers = {
            "Content-Type": "application/json",
            "X-SalesOS-Event": delivery.event_name,
            "X-SalesOS-Signature": cls.sign(endpoint.secret, body, timestamp),
            "X-SalesOS-Timestamp": timestamp,
            "X-SalesOS-Delivery-Id": str(delivery.id),
        }
        client = _client or httpx.AsyncClient(timeout=cls.TIMEOUT)
        try:
            response = await client.post(endpoint.url, content=body, headers=headers)
            delivery.attempts += 1
            delivery.response_code = response.status_code
            if 200 <= response.status_code < 300:
                delivery.status = "delivered"
                delivery.delivered_at = datetime.now(UTC)
                delivery.next_retry_at = None
            else:
                delivery.status = "failed"
                delivery.last_error = f"HTTP {response.status_code}"
                cls._schedule_retry(delivery)
        except Exception as exc:  # noqa: BLE001 — network errors are expected
            delivery.attempts += 1
            delivery.status = "failed"
            delivery.last_error = str(exc)[:300]
            cls._schedule_retry(delivery)
        finally:
            if _client is None:
                await client.aclose()
        return delivery

    @staticmethod
    def _schedule_retry(delivery: WebhookDelivery) -> None:
        settings = get_settings()
        if delivery.attempts >= settings.worker_max_attempts:
            delivery.status = "dead"
            return
        base = min(2.0 * (2 ** (delivery.attempts - 1)), 60.0)
        delivery.next_retry_at = datetime.now(UTC) + timedelta(seconds=base)
