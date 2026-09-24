"""HTTP request-integrity helpers: idempotent writes (G-14) and conditional
writes (G-15).

Both are cross-cutting edge concerns that several modules need. They live in
``app/core`` because ``app/core`` is the only place two modules may share code
without adding a cross-module import (the ratchet in
``tests/test_module_boundaries.py``). The one module import here —
``platform.models.IdempotencyKey`` — follows the existing precedent in
``app/core/events/writer.py`` (``platform`` is the system-plumbing module) and
creates no cycle.

Idempotency (G-14)
------------------
A client that retries a side-effecting write (a payment, an order, a campaign)
must not perform the effect twice. The mechanism is **opt-in via an explicit
allow-list** of side-effecting paths (``IDEMPOTENT_PATHS``) combined with the
presence of the ``Idempotency-Key`` header. It is deliberately NOT a blanket
rule on every POST:

* most POSTs are naturally idempotent (or must stay freely retryable) and gain
  nothing from a replay cache;
* requiring the header on every POST would break every existing client.

So a request is guarded only when its method+path is on the list AND it carries
the header. Everything else is untouched.

The stored record is **tenant-scoped**: the tenant id is encoded into the
existing ``IdempotencyKey.scope`` (``http:<tenant>:<route>``), mirroring the
ingest gateway's ``webhook:<provider>:<tenant>`` convention. A key replayed with
a DIFFERENT body is rejected with 409 rather than silently returning the first
response — a retry must be the same request.

The store is **Postgres** (the ``idempotency_keys`` table), not Redis. When it
is unreachable the middleware fails **CLOSED** (503): the entire point is to
stop a duplicate money/order effect, so refusing the write is safer than
risking a double charge. This is the opposite of the rate limiter's throughput
tiers, which fail open.

Retention: ``expires_at`` is honoured. An expired key is reclaimed the next
time it is claimed (delete-on-claim), so a client can reuse a key after the
window; ``purge_expired`` exists for a scheduled worker to reclaim keys that
are never retried again.

Outcome handling once the route has run:

* 2xx / 3xx — the response is stored and replayed for the same key.
* 4xx — the reservation is RELEASED. A client-caused rejection means nothing
  ran, so the client may fix the request and reuse the key.
* 5xx, or an exception escaping the route — the reservation is kept in a
  terminal ``failed`` state and a retry with the same key is refused (409).
  A 5xx means the outcome is **unknown**, not "did not happen": the effect may
  have partially applied, so re-executing could double a non-transactional
  effect (a provider send, a PSP capture). The client must use a new key.

Conditional writes (G-15)
-------------------------
``model_kit.VersionMixin.version`` already exists on the mutable models. There
is no second concurrency mechanism here: ``apply_versioned_update`` issues one
``UPDATE ... WHERE id = ? AND version = ?`` and raises the project's existing
``ConflictError`` (409) when that WHERE clause matches nothing, so the
DATABASE decides the winner. ``etag_for`` / ``apply_etag`` render the version
back on responses.

This surface is WIRED (§17): customers PATCH, orders status/cancel + the
detail GET's ETag, and the automation writes — workflow status PATCH and
version publish both route through ``apply_versioned_update``, so the row
version bumps on EVERY write (conditional or not) and the read advertises it
as an ETag. The remaining versioned models — campaigns, agents, refunds —
have NO HTTP mutation endpoint today (their routes create, they never update),
so there is no conditional-write seam to wire; when such an endpoint is added
it must follow the customers/automation pattern, not a raw attribute write.
"""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import Depends, Header
from sqlalchemy import delete, func, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import update as sa_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value
from starlette.responses import Response

from app.core.db import SessionLocal
from app.core.errors import (
    ConflictError,
    ValidationError,
    build_error_envelope,
    request_id_contextvar,
    retryable_for_status,
)
from app.core.observability import get_logger
from app.core.security import decode_token
from app.modules.platform.models import IdempotencyKey

# ---------------------------------------------------------------------------
# Idempotency — policy
# ---------------------------------------------------------------------------

#: Methods that can have a side effect. A GET/HEAD is never guarded.
GUARDED_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: Explicit allow-list of side-effecting path prefixes (mounted under /api/v1).
#: Only these paths are ever guarded, and only when the request also carries an
#: ``Idempotency-Key``. Adding a path here is a deliberate decision that a
#: duplicate execution would be harmful; it is not a default.
IDEMPOTENT_PATHS: tuple[str, ...] = (
    "/api/v1/orders",  # create order, capture/reconcile payment, refund, cancel
    "/api/v1/billing",  # start-trial, usage metering (money)
    "/api/v1/marketing/campaigns",  # campaign send / broadcast
    "/api/v1/marketing/touchpoints",  # outbound touchpoint
    "/api/v1/conversations",  # send message, assign, close
    "/api/v1/privacy/data-requests",  # data-subject request execution
    "/api/v1/workflows/executions",  # run an automation
)

#: Response header set on a replayed response so a client can tell it apart.
REPLAY_HEADER = "Idempotency-Replayed"

#: Retention for a stored key. ``expires_at`` is written on every record and
#: READ by :meth:`IdempotencyService.begin` (delete-on-claim) and by
#: :meth:`IdempotencyService.purge_expired`.
KEY_TTL = timedelta(days=7)

# Outcome values for :class:`IdempotencyClaim`.
NEW = "new"
REPLAY = "replay"
CONFLICT = "conflict"
IN_PROGRESS = "in_progress"
FAILED = "failed"

#: Record states stored in ``IdempotencyKey.status``.
STATUS_PROCESSING = "processing"
STATUS_PROCESSED = "processed"
STATUS_FAILED = "failed"


@dataclass(frozen=True, slots=True)
class IdempotencyClaim:
    """Result of trying to reserve an idempotency key."""

    outcome: str
    response: dict[str, Any] | None = None


def should_guard(method: str, path: str) -> bool:
    """True when this request is eligible for idempotency handling.

    Eligibility is method + allow-listed path; the header is checked
    separately because its absence must leave the route's plain semantics.
    """
    if method.upper() not in GUARDED_METHODS:
        return False
    return any(_path_matches(path, prefix) for prefix in IDEMPOTENT_PATHS)


def _path_matches(path: str, prefix: str) -> bool:
    prefix = prefix.rstrip("/")
    return path == prefix or path.startswith(prefix + "/")


def body_hash(body: bytes) -> str:
    """Stable fingerprint of the request body used to detect key reuse."""
    return hashlib.sha256(body).hexdigest()


def idem_scope(
    tenant_id: uuid.UUID | str | None,
    method: str,
    path: str,
    *,
    client_ip: str | None = None,
) -> str:
    """Tenant-scoped scope string for ``IdempotencyKey``.

    ``IdempotencyKey.scope`` is ``String(63)``, so the owner is hashed down to
    fit rather than truncated (truncation could collide two tenants). The route
    is folded into a short hash so the same key value used on two endpoints
    stays distinct.
    """
    owner = str(tenant_id) if tenant_id else f"ip:{client_ip or 'unknown'}"
    if len(owner) > 40:
        owner = hashlib.sha256(owner.encode()).hexdigest()[:40]
    route = hashlib.sha256(f"{method.upper()} {path}".encode()).hexdigest()[:16]
    return f"http:{owner}:{route}"


def _expiry() -> datetime:
    return datetime.now(UTC) + KEY_TTL


def _is_expired(record: IdempotencyKey) -> bool:
    expires_at = record.expires_at
    if expires_at is None:  # pragma: no cover — column is NOT NULL
        return False
    if expires_at.tzinfo is None:  # a driver that drops tzinfo
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= datetime.now(UTC)


async def _find(session: AsyncSession, scope: str, key: str) -> IdempotencyKey | None:
    return (
        await session.execute(
            select(IdempotencyKey).where(
                IdempotencyKey.scope == scope, IdempotencyKey.key == key
            )
        )
    ).scalar_one_or_none()


class IdempotencyService:
    """Reserve / complete / fail / release an idempotency key.

    The middleware uses :class:`DbIdempotencyStore` (its own session), but the
    service is session-agnostic on purpose: a route that wants true atomicity
    with its effect can call ``begin``/``complete`` on its own request session
    so the record and the write commit together.
    """

    @staticmethod
    async def begin(
        session: AsyncSession, *, scope: str, key: str, request_hash: str
    ) -> IdempotencyClaim:
        existing = await _find(session, scope, key)
        if existing is not None:
            if _is_expired(existing):
                # Delete-on-claim: the retention window elapsed, so the key is
                # free again. This is what makes expires_at effective without a
                # background worker for keys that ARE retried; purge_expired
                # reclaims the ones that are not.
                await session.delete(existing)
                await session.flush()
            else:
                return _claim_from(existing, request_hash)

        record = IdempotencyKey(
            scope=scope,
            key=key,
            request_hash=request_hash,
            response=None,
            status=STATUS_PROCESSING,
            expires_at=_expiry(),
        )
        try:
            # SAVEPOINT: a duplicate insert (concurrent retry) must not poison
            # the caller's transaction — we roll back only the insert and read
            # the winner's record instead.
            async with session.begin_nested():
                session.add(record)
                await session.flush()
        except IntegrityError:
            winner = await _find(session, scope, key)
            if winner is None:  # pragma: no cover — row vanished mid-race
                return IdempotencyClaim(IN_PROGRESS)
            return _claim_from(winner, request_hash)
        return IdempotencyClaim(NEW)

    @staticmethod
    async def complete(
        session: AsyncSession,
        *,
        scope: str,
        key: str,
        status_code: int,
        body: bytes,
        content_type: str,
    ) -> None:
        """Record a definitive outcome so the same key replays it."""
        record = await _find(session, scope, key)
        if record is None:
            return
        record.status = STATUS_PROCESSED
        record.response = {
            "status": int(status_code),
            "body": base64.b64encode(body).decode("ascii"),
            "content_type": content_type,
        }
        await session.flush()

    @staticmethod
    async def fail(
        session: AsyncSession, *, scope: str, key: str, status_code: int | None = None
    ) -> None:
        """Mark the attempt terminal-failed because its outcome is UNKNOWN.

        Used for a 5xx or an exception escaping the route. The reservation is
        deliberately KEPT: deleting it would let a retry re-execute an effect
        that may have already partially applied. A retry with this key is
        refused (see :func:`_claim_from`) and the client must use a new key.
        """
        record = await _find(session, scope, key)
        if record is None:
            return
        record.status = STATUS_FAILED
        # Keep the status code for operators; it is NOT a replayable response.
        record.response = {"status": int(status_code)} if status_code else None
        await session.flush()

    @staticmethod
    async def release(session: AsyncSession, *, scope: str, key: str) -> None:
        """Drop the reservation — ONLY when nothing can have run.

        This is the client-caused-failure path (4xx): the request was rejected,
        so the key is free for a corrected retry. Never use it for a 5xx or an
        exception, where the outcome is unknown (use :meth:`fail`).
        """
        record = await _find(session, scope, key)
        if record is not None:
            await session.delete(record)
            await session.flush()

    @staticmethod
    async def purge_expired(session: AsyncSession, *, limit: int = 1000) -> int:
        """Delete up to ``limit`` expired keys; return how many were removed.

        Delete-on-claim reclaims a key the next time it is retried. This sweep
        reclaims the keys that never come back, which is what keeps the table
        bounded. It is a maintenance entry point: NOTHING schedules it yet
        (a worker would, and workers are out of this workstream's file scope).
        """
        expired_ids = (
            select(IdempotencyKey.id)
            .where(IdempotencyKey.expires_at <= func.now())
            .limit(limit)
        )
        result = await session.execute(
            delete(IdempotencyKey)
            .where(IdempotencyKey.id.in_(expired_ids))
            .returning(IdempotencyKey.id)
        )
        return len(result.scalars().all())


def _claim_from(record: IdempotencyKey, request_hash: str) -> IdempotencyClaim:
    # A key reused with a different body is a client bug, not a retry: refuse
    # it instead of replaying the first response for a different request.
    if record.request_hash and record.request_hash != request_hash:
        return IdempotencyClaim(CONFLICT)
    if record.status == STATUS_FAILED:
        # The previous attempt ended with an UNKNOWN outcome (5xx / crash).
        # Refuse: re-executing could double an effect that partially applied.
        return IdempotencyClaim(FAILED)
    if record.status == STATUS_PROCESSED and record.response:
        return IdempotencyClaim(REPLAY, record.response)
    # Reserved but not yet completed (in-flight, or a process died before the
    # response was recorded). Refuse rather than execute again.
    return IdempotencyClaim(IN_PROGRESS)


class DbIdempotencyStore:
    """Postgres-backed store used by the middleware (one session per call)."""

    def __init__(self, session_factory: Callable[[], Any] | None = None) -> None:
        self._session_factory = session_factory or SessionLocal

    async def begin(self, *, scope: str, key: str, request_hash: str) -> IdempotencyClaim:
        async with self._session_factory() as session:
            claim = await IdempotencyService.begin(
                session, scope=scope, key=key, request_hash=request_hash
            )
            if claim.outcome == NEW:
                await session.commit()
            return claim

    async def complete(
        self,
        *,
        scope: str,
        key: str,
        status_code: int,
        body: bytes,
        content_type: str,
    ) -> None:
        async with self._session_factory() as session:
            await IdempotencyService.complete(
                session,
                scope=scope,
                key=key,
                status_code=status_code,
                body=body,
                content_type=content_type,
            )
            await session.commit()

    async def fail(
        self, *, scope: str, key: str, status_code: int | None = None
    ) -> None:
        async with self._session_factory() as session:
            await IdempotencyService.fail(
                session, scope=scope, key=key, status_code=status_code
            )
            await session.commit()

    async def release(self, *, scope: str, key: str) -> None:
        async with self._session_factory() as session:
            await IdempotencyService.release(session, scope=scope, key=key)
            await session.commit()


# ---------------------------------------------------------------------------
# Idempotency — ASGI middleware
# ---------------------------------------------------------------------------


def _read_body_message(body: bytes) -> dict[str, Any]:
    return {"type": "http.request", "body": body, "more_body": False}


async def _read_body(receive: Callable[[], Awaitable[dict[str, Any]]]) -> bytes:
    chunks: list[bytes] = []
    more = True
    while more:
        message = await receive()
        if message["type"] == "http.disconnect":
            break
        chunks.append(message.get("body", b""))
        more = message.get("more_body", False)
    return b"".join(chunks)


def _header_value(headers: list[tuple[bytes, bytes]], name: bytes) -> str | None:
    for key, value in headers:
        if key.lower() == name:
            return value.decode("latin-1")
    return None


def _tenant_from_headers(headers: dict[str, str]) -> uuid.UUID | None:
    """Best-effort tenant id from the (signature-verified) bearer token.

    Used ONLY to scope the idempotency record — never for authorization. The
    route's own auth dependency still runs and still decides access. A missing
    or invalid token simply falls back to an IP-scoped key, so an anonymous
    caller cannot collide with an authenticated tenant's keys.
    """
    authorization = headers.get("authorization")
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    try:
        payload = decode_token(authorization.split(" ", 1)[1].strip())
        raw = payload.get("tenant_id")
        return uuid.UUID(raw) if raw else None
    except Exception:  # noqa: BLE001 — invalid/expired token is expected here
        return None


async def _emit_error(
    send: Callable[[dict[str, Any]], Awaitable[None]],
    status: int,
    code: str,
    message: str,
) -> None:
    body = json.dumps(
        build_error_envelope(
            code,
            message,
            retryable=retryable_for_status(status),
            request_id=request_id_contextvar.get(),
        )
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def _send_stored(
    send: Callable[[dict[str, Any]], Awaitable[None]], stored: dict[str, Any]
) -> None:
    body = base64.b64decode(stored.get("body", ""))
    content_type = stored.get("content_type") or "application/json"
    await send(
        {
            "type": "http.response.start",
            "status": int(stored.get("status", 200)),
            "headers": [
                (b"content-type", content_type.encode("latin-1")),
                (b"content-length", str(len(body)).encode()),
                (REPLAY_HEADER.encode(), b"true"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class IdempotencyMiddleware:
    """Replay the first response for a repeated ``Idempotency-Key``.

    Registered innermost (see app.main): the body-size cap and CORS run outside
    it, so an oversized body is refused before this reads it and a replayed
    response still carries CORS/security headers.
    """

    def __init__(self, app, *, store: Any | None = None, enabled: bool | None = None) -> None:
        self.app = app
        self.store = store if store is not None else DbIdempotencyStore()
        # Enabled by default. The middleware is inert unless a request both
        # matches the allow-list AND carries Idempotency-Key, so leaving it on
        # during the test run costs nothing — and it is a correctness control,
        # not an optimisation, so it should not silently switch off. Tests that
        # exercise it inject their own store.
        self.enabled = True if enabled is None else enabled

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or not self.enabled:
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")
        path = scope.get("path", "")
        if not should_guard(method, path):
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        raw_key = headers.get("idempotency-key")
        if not raw_key:
            # Opt-in header absent: leave the route's semantics untouched.
            await self.app(scope, receive, send)
            return

        body = await _read_body(receive)
        request_hash = body_hash(body)
        client = scope.get("client") or ("unknown", 0)
        scope_key = idem_scope(
            _tenant_from_headers(headers), method, path, client_ip=client[0]
        )

        try:
            claim = await self.store.begin(
                scope=scope_key, key=raw_key, request_hash=request_hash
            )
        except Exception as exc:  # noqa: BLE001 — store unreachable
            # FAIL CLOSED. The record is the only thing standing between a
            # client retry and a duplicate charge; a 503 is recoverable, a
            # double effect is not. (Throughput rate limits fail open; this
            # does not.)
            get_logger("idempotency").error(
                "idempotency_store_unavailable", error=str(exc), path=path
            )
            await _emit_error(send, 503, "idempotency_unavailable", "idempotency store unavailable")
            return

        if claim.outcome == CONFLICT:
            await _emit_error(
                send,
                409,
                "conflict",
                "Idempotency-Key reused with a different request body",
            )
            return
        if claim.outcome == IN_PROGRESS:
            await _emit_error(
                send, 409, "conflict", "request with this Idempotency-Key is in progress"
            )
            return
        if claim.outcome == FAILED:
            # A previous attempt with this key ended with an unknown outcome.
            # Re-executing it could double a partially-applied effect, so the
            # retry is refused; the client must start a new attempt with a new
            # Idempotency-Key.
            await _emit_error(
                send,
                409,
                "conflict",
                "previous attempt with this Idempotency-Key failed with an unknown "
                "outcome; retry with a new key",
            )
            return
        if claim.outcome == REPLAY and claim.response is not None:
            await _send_stored(send, claim.response)
            return

        # NEW: execute once, capture the response, then persist the outcome.
        body_consumed = False

        async def replay_receive() -> dict[str, Any]:
            nonlocal body_consumed
            if not body_consumed:
                body_consumed = True
                return _read_body_message(body)
            return {"type": "http.request", "body": b"", "more_body": False}

        captured: dict[str, Any] = {}
        chunks: list[bytes] = []

        async def send_capture(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                captured["status"] = message["status"]
                captured["headers"] = list(message.get("headers", []))
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))
            await send(message)

        try:
            await self.app(scope, replay_receive, send_capture)
        except Exception:
            # The route raised, so no response was produced and the outcome is
            # UNKNOWN — the effect may have partially applied. Mark the key
            # terminal-failed (do NOT release: releasing would let a retry
            # re-execute it) and let the exception propagate.
            await self._fail_quietly(scope_key, raw_key, None)
            raise

        status = int(captured.get("status", 500))
        content_type = _header_value(captured.get("headers", []), b"content-type")
        if status >= 500:
            # A 5xx means UNKNOWN, not "did not happen": keep the reservation
            # in a terminal state so a retry is refused rather than re-run.
            await self._fail_quietly(scope_key, raw_key, status)
        elif status >= 400:
            # Client-caused rejection: nothing ran, so free the key for a
            # corrected retry.
            await self._release_quietly(scope_key, raw_key)
        else:
            await self._complete_quietly(
                scope_key, raw_key, status, b"".join(chunks), content_type or "application/json"
            )

    async def _complete_quietly(
        self, scope_key: str, key: str, status: int, body: bytes, content_type: str
    ) -> None:
        try:
            await self.store.complete(
                scope=scope_key,
                key=key,
                status_code=status,
                body=body,
                content_type=content_type,
            )
        except Exception as exc:  # noqa: BLE001
            # The response has already been sent, so the request cannot be
            # failed without inviting a retry of an effect that already
            # happened. Log loudly. The reservation is left in "processing",
            # which _claim_from refuses (409) rather than re-executing — so a
            # lost completion costs a rejected retry, never a double effect.
            get_logger("idempotency").error(
                "idempotency_record_failed", error=str(exc), scope=scope_key
            )

    async def _fail_quietly(
        self, scope_key: str, key: str, status: int | None
    ) -> None:
        try:
            await self.store.fail(scope=scope_key, key=key, status_code=status)
        except Exception as exc:  # noqa: BLE001
            # If we cannot even record the failure, the reservation stays in
            # "processing", which _claim_from also refuses to re-execute — so
            # the safe behaviour (no double effect) is preserved either way.
            get_logger("idempotency").error(
                "idempotency_fail_record_failed", error=str(exc), scope=scope_key
            )

    async def _release_quietly(self, scope_key: str, key: str) -> None:
        try:
            await self.store.release(scope=scope_key, key=key)
        except Exception as exc:  # noqa: BLE001
            get_logger("idempotency").error(
                "idempotency_release_failed", error=str(exc), scope=scope_key
            )


# ---------------------------------------------------------------------------
# Conditional writes — ETag / If-Match (G-15)
# ---------------------------------------------------------------------------


def etag_for(version: int) -> str:
    """Strong ETag for a ``VersionMixin.version`` value."""
    return f'"{int(version)}"'


def apply_etag(response: Response, version: int) -> Response:
    """Attach the version's ETag to a response (used on reads and writes)."""
    response.headers["ETag"] = etag_for(version)
    return response


def parse_if_match(header: str | None) -> int | None:
    """Extract the expected version from an ``If-Match`` header.

    Returns ``None`` when the header is absent or ``*`` (meaning "any existing
    representation"), i.e. no version constraint. A malformed value is a client
    error (400), never a silent pass.
    """
    if header is None:
        return None
    value = header.strip()
    if not value or value == "*":
        return None
    token = value.split(",", 1)[0].strip()  # single representation → first token
    if token.startswith("W/"):
        token = token[2:].strip()
    if len(token) >= 2 and token[0] == '"' and token[-1] == '"':
        token = token[1:-1]
    if not token.isdigit():
        raise ValidationError("malformed If-Match header", details={"if_match": header})
    return int(token)


def require_version(if_match: str | None, current_version: int) -> None:
    """Non-atomic FAST-FAIL pre-check for a stale ``If-Match``.

    This compares against a version the caller already read, so it can only
    reject an obviously stale request before doing expensive work. It is NOT
    sufficient on its own: the read and the later write are two steps, and a
    concurrent writer can slip between them. The authoritative check is
    :func:`apply_versioned_update`, which puts the version in the UPDATE's
    ``WHERE`` clause and lets the database decide.
    """
    expected = parse_if_match(if_match)
    if expected is None:
        return
    if expected != int(current_version):
        raise ConflictError(
            "resource version conflict — it changed since you read it",
            details={"if_match": expected, "current_version": int(current_version)},
        )


async def _current_version(
    session: AsyncSession, model: Any, instance: Any
) -> int | None:
    mapper = sa_inspect(model)
    pk = mapper.primary_key[0]
    stmt = select(model.version).where(pk == getattr(instance, pk.key))
    if "tenant_id" in mapper.columns and getattr(instance, "tenant_id", None) is not None:
        stmt = stmt.where(model.tenant_id == instance.tenant_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def apply_versioned_update(
    session: AsyncSession,
    instance: Any,
    if_match: str | None,
    values: Mapping[str, Any],
) -> None:
    """Atomic compare-and-swap on ``version``.

    Issues ONE statement::

        UPDATE <table> SET <values>, version = version + 1
        WHERE id = :id [AND tenant_id = :tenant_id] AND version = :expected

    and raises the project's existing ``ConflictError`` (409) when it matches
    no row. The DATABASE decides the winner: two concurrent writers holding the
    same valid ``If-Match`` cannot both succeed, because the second statement's
    ``WHERE version`` no longer matches the bumped row. A Python read-then-write
    cannot give that guarantee — the in-memory object can be stale.

    ``if_match`` of ``None`` or ``*`` means unconditional (still one statement,
    still version-bumped). ``values`` are plain column values to set.
    """
    model = type(instance)
    mapper = sa_inspect(model)
    pk = mapper.primary_key[0]
    expected = parse_if_match(if_match)

    stmt = sa_update(model).where(pk == getattr(instance, pk.key))
    # Defence in depth: RLS already scopes by tenant, but pin it explicitly so
    # a caller running without the tenant GUC cannot cross tenants.
    if "tenant_id" in mapper.columns and getattr(instance, "tenant_id", None) is not None:
        stmt = stmt.where(model.tenant_id == instance.tenant_id)
    if expected is not None:
        stmt = stmt.where(model.version == expected)
    stmt = (
        stmt.values(**values, version=model.version + 1)
        .returning(model.version)
        .execution_options(synchronize_session=False)
    )

    new_version = (await session.execute(stmt)).scalar_one_or_none()
    if new_version is None:
        raise ConflictError(
            "resource version conflict — it changed since you read it",
            details={
                "if_match": expected,
                "current_version": await _current_version(session, model, instance),
            },
        )

    # The UPDATE bypassed the identity map (synchronize_session=False). Keep the
    # ORM object consistent WITHOUT marking it dirty: a plain setattr would
    # leave the instance dirty and a later flush would emit an UNGUARDED UPDATE
    # that could clobber a concurrent writer — undoing the guarantee above.
    for name, value in values.items():
        set_committed_value(instance, name, value)
    set_committed_value(instance, "version", int(new_version))


async def if_match_header(
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
) -> str | None:
    """Dependency form of the ``If-Match`` header."""
    return if_match


#: Usage: ``if_match: IfMatch = ...`` then ``require_version(if_match, row.version)``.
IfMatch = Annotated[str | None, Depends(if_match_header)]
