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


def _mint_secret() -> str:
    """Mint a 64-hex-char endpoint signing secret (plaintext, shown once)."""
    return uuid.uuid4().hex + uuid.uuid4().hex


def _secret_at_rest(plaintext: str) -> str:
    """Encrypt a signing secret for the ``webhooks.secret`` column (§68).

    The signing secret is a replayable credential: a DB dump must not yield
    it (the deep review flagged the plaintext column). Stored values carry
    the ``v1:`` envelope prefix; legacy plaintext rows still verify — decrypt
    is backwards-compatible, so the population migrates as endpoints rotate.
    """
    from app.core.secrets import get_envelope_store

    return get_envelope_store().encrypt(plaintext)


def _endpoint_signing_secret(stored: str) -> str:
    """Read the signing secret back out, transparently for legacy rows."""
    from app.core.secrets import EnvelopeSecretStore, get_envelope_store

    if stored.startswith(EnvelopeSecretStore.PREFIX):
        return get_envelope_store().decrypt(stored).value
    return stored


class PreparedDelivery:
    """The signed request built by `prepare`, held outside any transaction."""

    __slots__ = ("delivery_id", "url", "body", "headers")

    def __init__(self, *, delivery_id: uuid.UUID, url: str, body: bytes, headers: dict) -> None:
        self.delivery_id = delivery_id
        self.url = url
        self.body = body
        self.headers = headers


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
        plaintext = _mint_secret()
        endpoint = WebhookEndpoint(
            tenant_id=tenant_id,
            url=url,
            secret=_secret_at_rest(plaintext),
            events=events,
        )
        # Transient, NEVER persisted: the one-time plaintext delivery the
        # register/rotate responses promise. The column keeps ciphertext.
        endpoint.plaintext_secret = plaintext
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
        plaintext = _mint_secret()
        endpoint.secret = _secret_at_rest(plaintext)
        endpoint.plaintext_secret = plaintext
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
    async def prepare(
        cls,
        session: Any,
        tenant_id: uuid.UUID,
        delivery_id: uuid.UUID,
    ) -> PreparedDelivery | None:
        """Phase 1 (DB-only, short transaction): validate and build the request.

        Reads the delivery and endpoint, runs the local refusal checks and
        builds the signed request — NO network I/O. The caller commits this
        transaction BEFORE the HTTP call, so a slow receiver cannot pin a
        pooled connection, the delivery-row lock, or the RLS-bound
        transaction for `TIMEOUT` seconds (the pool-exhaustion failure mode
        the deep review flagged).
        """
        delivery = (
            await session.execute(
                select(WebhookDelivery)
                .where(
                    WebhookDelivery.tenant_id == tenant_id,
                    WebhookDelivery.id == delivery_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if delivery is None or delivery.status in ("delivered", "dead"):
            return None

        endpoint = (
            await session.execute(
                select(WebhookEndpoint).where(WebhookEndpoint.id == delivery.webhook_id)
            )
        ).scalar_one_or_none()
        if endpoint is None or not endpoint.is_active:
            delivery.status = "failed"
            delivery.last_error = "endpoint missing or inactive"
            return None

        # S6: re-validate at SEND time. A hostname that resolved to a public
        # address at registration can be re-pointed at an internal one later
        # (DNS rebinding) — the check has to happen on the request that
        # actually goes out, not only on the one that stored the URL.
        try:
            _ssrf_guard(endpoint.url)
        except ValidationError as exc:
            delivery.status = "dead"
            delivery.last_error = f"endpoint url rejected: {exc.message}"
            return None

        body = json.dumps(delivery.payload, default=str).encode()
        # §148: the timestamp rides INSIDE the signature (replay protection)
        # and the delivery row id lets receivers dedupe redeliveries.
        timestamp = str(int(datetime.now(UTC).timestamp()))
        signing_secret = _endpoint_signing_secret(endpoint.secret)
        headers = {
            "Content-Type": "application/json",
            "X-SalesOS-Event": delivery.event_name,
            "X-SalesOS-Signature": cls.sign(signing_secret, body, timestamp),
            "X-SalesOS-Timestamp": timestamp,
            "X-SalesOS-Delivery-Id": str(delivery.id),
        }
        return PreparedDelivery(
            delivery_id=delivery.id, url=endpoint.url, body=body, headers=headers
        )

    @classmethod
    async def record_outcome(
        cls,
        session: Any,
        tenant_id: uuid.UUID,
        delivery_id: uuid.UUID,
        *,
        response_code: int | None = None,
        error: str | None = None,
    ) -> WebhookDelivery | None:
        """Phase 2 (own short transaction, after the HTTP call): write the result.

        Re-checks the terminal statuses under a row lock, so a concurrent
        redelivery that finished first is not double-counted (attempts) or
        overwritten.
        """
        delivery = (
            await session.execute(
                select(WebhookDelivery)
                .where(
                    WebhookDelivery.tenant_id == tenant_id,
                    WebhookDelivery.id == delivery_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if delivery is None or delivery.status in ("delivered", "dead"):
            return delivery

        delivery.attempts += 1
        if error is None and response_code is not None and 200 <= response_code < 300:
            delivery.response_code = response_code
            delivery.status = "delivered"
            delivery.delivered_at = datetime.now(UTC)
            delivery.next_retry_at = None
        elif response_code is not None:
            delivery.response_code = response_code
            delivery.status = "failed"
            delivery.last_error = f"HTTP {response_code}"
            cls._schedule_retry(delivery)
        else:
            delivery.status = "failed"
            delivery.last_error = (error or "unknown delivery failure")[:300]
            cls._schedule_retry(delivery)
        return delivery

    @classmethod
    async def deliver(
        cls,
        session: Any,
        tenant_id: uuid.UUID,
        delivery_id: uuid.UUID,
        *,
        _client: httpx.AsyncClient | None = None,
    ) -> WebhookDelivery | None:
        """Single-session convenience: prepare → POST → record_outcome.

        The PRODUCTION worker must NOT use this path — it holds the session's
        transaction open across the network call (see prepare/record_outcome).
        Kept for inline callers and tests that drive the whole flow on one
        session with an injected client.
        """
        prepared = await cls.prepare(session, tenant_id, delivery_id)
        if prepared is None:
            return (
                await session.execute(
                    select(WebhookDelivery).where(
                        WebhookDelivery.tenant_id == tenant_id,
                        WebhookDelivery.id == delivery_id,
                    )
                )
            ).scalar_one_or_none()

        client = _client or httpx.AsyncClient(timeout=cls.TIMEOUT)
        response_code: int | None = None
        error: str | None = None
        try:
            response = await client.post(
                prepared.url, content=prepared.body, headers=prepared.headers
            )
            response_code = response.status_code
        except Exception as exc:  # noqa: BLE001 — network errors are expected
            error = str(exc)
        finally:
            if _client is None:
                await client.aclose()
        return await cls.record_outcome(
            session, tenant_id, delivery_id, response_code=response_code, error=error
        )

    @staticmethod
    def _schedule_retry(delivery: WebhookDelivery) -> None:
        settings = get_settings()
        if delivery.attempts >= settings.worker_max_attempts:
            delivery.status = "dead"
            return
        base = min(2.0 * (2 ** (delivery.attempts - 1)), 60.0)
        delivery.next_retry_at = datetime.now(UTC) + timedelta(seconds=base)
