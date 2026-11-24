"""WhatsApp Business App (coexistence) data sync — contacts and chat history.

Coexistence has two halves and this module owns the second one. The first half (the number works
in the app AND the Cloud API) is proven at connect time. The second half is Meta moving the
merchant's own data into the partner:

* ``POST /{phone-number-id}/smb_app_data`` with ``sync_type: smb_app_state_sync`` — the app's
  WhatsApp contacts, then every later add/edit of them.
* the same call with ``sync_type: history`` — up to 180 days of one-to-one chat history, in three
  phases (0: link → today, 1: today → 90 days, 2: 90 → 180 days), each split into chunks that may
  arrive in any order.

Two rules make this the most fragile part of the channel, and both are enforced here rather than
by convention:

1. **Inside 24 hours, once per connection.** Meta accepts the first request only within 24 hours of
   onboarding, and a second request for the same connection is not a retry — it requires an
   offboarding and a fresh link. So the request is recorded in Postgres (``whatsapp_sync_runs``)
   BEFORE it is sent, keyed by ``onboarding_epoch``, and a row that already carries a
   ``request_id`` is never sent again.
2. **Declining history is not a failure.** Meta answers error 2593109 when the merchant chose not to
   share their chat history. The channel stays connected; the state becomes ``not_shared`` and the
   screen says so.

The channel state the settings screen shows is computed from these rows by
:func:`channel_sync_state`, so "connected" and "synced" are never the same word.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ExternalProviderError, ValidationError
from app.modules.conversations.models import (
    WHATSAPP_SYNC_CONTACTS,
    WHATSAPP_SYNC_HISTORY,
    WhatsAppSyncRun,
)

logger = logging.getLogger(__name__)

GRAPH = "https://graph.facebook.com/v27.0"

#: Meta's wire value for each sync kind.
WIRE_SYNC_TYPE = {WHATSAPP_SYNC_CONTACTS: "smb_app_state_sync", WHATSAPP_SYNC_HISTORY: "history"}

#: Meta's own window: both requests must be sent within 24 hours of onboarding.
SYNC_WINDOW = timedelta(hours=24)

#: Meta's error code for "the merchant declined to share their chat history". Not an outage and
#: not a broken connection — a decision the shop made and can live with.
HISTORY_NOT_SHARED_CODE = 2593109

#: Channel-level state, in the order a healthy connection passes through them.
STATE_ONBOARDING = "ONBOARDING"
STATE_CONNECTED_PENDING_SYNC = "CONNECTED_PENDING_SYNC"
STATE_CONTACTS_SYNC_PENDING = "CONTACTS_SYNC_PENDING"
STATE_CONTACTS_SYNC_IN_PROGRESS = "CONTACTS_SYNC_IN_PROGRESS"
STATE_CONTACTS_SYNC_COMPLETED = "CONTACTS_SYNC_COMPLETED"
STATE_HISTORY_SYNC_PENDING = "HISTORY_SYNC_PENDING"
STATE_HISTORY_SYNC_IN_PROGRESS = "HISTORY_SYNC_IN_PROGRESS"
STATE_HISTORY_SYNC_COMPLETED = "HISTORY_SYNC_COMPLETED"
STATE_HISTORY_NOT_SHARED = "HISTORY_NOT_SHARED"
STATE_READY = "READY"
STATE_SYNC_FAILED = "SYNC_FAILED"
STATE_OFFBOARDED = "OFFBOARDED"


def epoch_for(config: dict) -> str:
    """The connection's identity for sync purposes: when it proved coexistence.

    A re-linked number gets a new timestamp, so it legitimately starts new runs; everything else
    (a retried webhook, a restarted worker, a second click) resolves to the same epoch and hits the
    same row, which is what makes "request it once" enforceable.
    """
    verified_at = str(config.get("coexistence_verified_at") or "").strip()
    if verified_at:
        return verified_at
    # No coexistence stamp (a plain Cloud API channel): pin the epoch to the number itself so a
    # single run row exists and can never be duplicated.
    return f"cloud_api:{config.get('phone_number_id') or ''}"


def deadline_from(onboarding_completed_at: datetime) -> datetime:
    """Meta stops accepting the first sync request 24 hours after onboarding."""
    return onboarding_completed_at + SYNC_WINDOW


def may_request(run: WhatsAppSyncRun | None, now: datetime, deadline: datetime) -> tuple[bool, str]:
    """Whether a first request may be sent for this run — and why not, when it may not.

    Sent-once is the whole point: a row that already has a ``request_id`` is answered with "already
    requested" even if the caller is a retry, a second worker or a support engineer pressing the
    button again. A failed or expired row needs a re-link, which Meta requires anyway.
    """
    if run is None:
        if now > deadline:
            return False, "the 24-hour window Meta allows for the first sync request has closed"
        return True, ""
    if run.request_id:
        return False, "this connection already asked Meta for this sync"
    if run.state == "expired":
        return False, "the 24-hour window Meta allows for the first sync request has closed"
    if run.state == "failed":
        return False, "Meta refused this sync request; only re-linking the number can retry it"
    if run.state == "not_shared":
        return False, "the merchant chose not to share chat history"
    if now > deadline:
        return False, "the 24-hour window Meta allows for the first sync request has closed"
    return True, ""


def request_id_from(payload: object) -> str:
    """Meta's handle for the transfer, from a 2xx body — or a provider error, never a silent blank.

    A sync request without a ``request_id`` cannot be followed: no chunk can be attributed to it and
    no progress can be read, so treating it as success would leave a channel that looks synced and
    is not.
    """
    if not isinstance(payload, dict):
        raise ExternalProviderError(
            "Meta returned an invalid response for the WhatsApp sync request."
        )
    if payload.get("error"):
        raise ExternalProviderError("Meta refused the WhatsApp sync request.")
    request_id = payload.get("request_id")
    if not isinstance(request_id, str) or not request_id.strip():
        raise ExternalProviderError(
            "Meta accepted the WhatsApp sync request without a request id, so it cannot be "
            "followed. Re-link the number."
        )
    return request_id.strip()


def meta_error_code(response: httpx.Response) -> int | None:
    """The numeric code in a Graph error body, when there is one."""
    try:
        error = response.json().get("error") or {}
    except (ValueError, AttributeError):
        return None
    code = error.get("code")
    return code if isinstance(code, int) else None


class HistoryNotShared(Exception):
    """The merchant declined to share chat history (Meta 2593109). A choice, not a failure."""


async def post_sync_request(
    http: httpx.AsyncClient, *, phone_number_id: str, token: str, sync_type: str
) -> str:
    """Ask Meta to start one sync kind. Returns the ``request_id``.

    The body is Meta's documented shape and nothing else: ``messaging_product`` is required, and
    the sync kind is the whole request.
    """
    wire_type = WIRE_SYNC_TYPE.get(sync_type)
    if wire_type is None:
        raise ValidationError(f"Unknown WhatsApp sync type: {sync_type}")
    try:
        response = await http.post(
            f"{GRAPH}/{phone_number_id}/smb_app_data",
            headers={"Authorization": f"Bearer {token}"},
            json={"messaging_product": "whatsapp", "sync_type": wire_type},
        )
    except httpx.RequestError:
        raise ExternalProviderError(
            "Could not reach Meta to start the WhatsApp data sync. Try again.", retryable=True
        ) from None
    if response.status_code == 429 or response.status_code >= 500:
        raise ExternalProviderError(
            "Meta is temporarily unavailable while starting the WhatsApp data sync.",
            retryable=True,
        )
    if response.is_error:
        if (
            meta_error_code(response) == HISTORY_NOT_SHARED_CODE
            and sync_type == WHATSAPP_SYNC_HISTORY
        ):
            raise HistoryNotShared()
        raise ExternalProviderError(
            "Meta refused to start the WhatsApp data sync. Re-link the number to try again."
        )
    try:
        payload = response.json()
    except ValueError:
        raise ExternalProviderError(
            "Meta returned an invalid response for the WhatsApp sync request."
        ) from None
    return request_id_from(payload)


async def _get_run(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    phone_number_id: str,
    sync_type: str,
    epoch: str,
) -> WhatsAppSyncRun | None:
    return (
        await session.execute(
            select(WhatsAppSyncRun).where(
                WhatsAppSyncRun.tenant_id == tenant_id,
                WhatsAppSyncRun.phone_number_id == phone_number_id,
                WhatsAppSyncRun.sync_type == sync_type,
                WhatsAppSyncRun.onboarding_epoch == epoch,
            )
        )
    ).scalar_one_or_none()


async def request_sync(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    phone_number_id: str,
    waba_id: str | None,
    epoch: str,
    onboarding_completed_at: datetime,
    sync_type: str,
    token: str,
    http: httpx.AsyncClient,
    now: datetime | None = None,
) -> WhatsAppSyncRun:
    """Start one sync kind exactly once, inside Meta's window, and record what Meta answered.

    The row is created and flushed BEFORE the call, so a crash between "sent" and "answered" leaves
    evidence that a request may exist instead of a clean slate that invites a second one.
    """
    now = now or datetime.now(UTC)
    deadline = deadline_from(onboarding_completed_at)
    run = await _get_run(
        session,
        tenant_id,
        phone_number_id=phone_number_id,
        sync_type=sync_type,
        epoch=epoch,
    )
    allowed, reason = may_request(run, now, deadline)
    if not allowed:
        if run is None:
            raise ValidationError(f"Could not start the WhatsApp {sync_type} sync: {reason}.")
        logger.info(
            "whatsapp.sync_request_skipped tenant=%s phone_number_id=%s type=%s reason=%s",
            tenant_id,
            phone_number_id,
            sync_type,
            reason,
        )
        return run

    if run is None:
        run = WhatsAppSyncRun(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            phone_number_id=phone_number_id,
            waba_id=waba_id,
            sync_type=sync_type,
            onboarding_epoch=epoch,
            state="pending",
            deadline_at=deadline,
        )
        session.add(run)
        await session.flush()
    run.attempts = (run.attempts or 0) + 1
    await session.flush()

    try:
        request_id = await post_sync_request(
            http, phone_number_id=phone_number_id, token=token, sync_type=sync_type
        )
    except HistoryNotShared:
        run.state = "not_shared"
        run.error = "the merchant chose not to share chat history"
        run.requested_at = now
        await session.flush()
        logger.info(
            "whatsapp.history_not_shared tenant=%s phone_number_id=%s", tenant_id, phone_number_id
        )
        return run
    except ExternalProviderError as exc:
        run.state = "expired" if now > deadline else "failed"
        run.error = str(exc)[:2000]
        await session.flush()
        raise
    run.request_id = request_id
    run.state = "requested"
    run.requested_at = now
    await session.flush()
    logger.info(
        "whatsapp.sync_requested tenant=%s phone_number_id=%s type=%s request_id=%s",
        tenant_id,
        phone_number_id,
        sync_type,
        request_id,
    )
    return run


async def request_all(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    phone_number_id: str,
    waba_id: str | None,
    epoch: str,
    onboarding_completed_at: datetime,
    token: str,
    http: httpx.AsyncClient,
    now: datetime | None = None,
) -> dict[str, WhatsAppSyncRun | None]:
    """Ask for contacts and history, each independently.

    One refusal must not cost the other: contacts are the part that makes the inbox usable, and a
    merchant who declined history still wants their contact list.
    """
    out: dict[str, WhatsAppSyncRun | None] = {}
    for sync_type in (WHATSAPP_SYNC_CONTACTS, WHATSAPP_SYNC_HISTORY):
        try:
            out[sync_type] = await request_sync(
                session,
                tenant_id,
                phone_number_id=phone_number_id,
                waba_id=waba_id,
                epoch=epoch,
                onboarding_completed_at=onboarding_completed_at,
                sync_type=sync_type,
                token=token,
                http=http,
                now=now,
            )
        except ExternalProviderError as exc:
            logger.warning(
                "whatsapp.sync_request_failed tenant=%s phone_number_id=%s type=%s error=%s",
                tenant_id,
                phone_number_id,
                sync_type,
                exc,
            )
            out[sync_type] = None
    return out


def channel_sync_state(
    contacts: WhatsAppSyncRun | None,
    history: WhatsAppSyncRun | None,
    *,
    offboarded: bool = False,
    now: datetime | None = None,
) -> str:
    """The one word the settings screen shows for this connection's data sync.

    READY means BOTH halves are settled: contacts synced (or never required) AND history either
    completed or explicitly declined. Anything else says what is still running, so "connected"
    never silently implies "synced".
    """
    if offboarded:
        return STATE_OFFBOARDED
    if contacts is None and history is None:
        return STATE_CONNECTED_PENDING_SYNC
    for run in (contacts, history):
        if run is not None and run.state in ("failed", "expired"):
            return STATE_SYNC_FAILED
    if contacts is not None and contacts.state not in ("completed", "not_shared"):
        return (
            STATE_CONTACTS_SYNC_IN_PROGRESS
            if contacts.state == "in_progress"
            else STATE_CONTACTS_SYNC_PENDING
        )
    if history is not None and history.state == "not_shared":
        return STATE_HISTORY_NOT_SHARED
    if history is not None and history.state != "completed":
        return (
            STATE_HISTORY_SYNC_IN_PROGRESS
            if history.state in ("in_progress", "requested")
            else STATE_HISTORY_SYNC_PENDING
        )
    return STATE_READY


def is_ready(state: str) -> bool:
    """READY or an explicit history refusal: both mean nothing is still owed to Meta."""
    return state in (STATE_READY, STATE_HISTORY_NOT_SHARED)


async def load_runs(
    session: AsyncSession, tenant_id: uuid.UUID, *, phone_number_id: str, epoch: str
) -> dict[str, WhatsAppSyncRun | None]:
    """Both sync rows for one connection, by kind."""
    return {
        sync_type: await _get_run(
            session,
            tenant_id,
            phone_number_id=phone_number_id,
            sync_type=sync_type,
            epoch=epoch,
        )
        for sync_type in (WHATSAPP_SYNC_CONTACTS, WHATSAPP_SYNC_HISTORY)
    }


async def record_chunk(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    phone_number_id: str,
    epoch: str,
    sync_type: str,
    phase: int | None = None,
    chunk_order: int | None = None,
    progress: int | None = None,
    messages_stored: int = 0,
) -> WhatsAppSyncRun | None:
    """Fold one webhook batch into the run's progress.

    Chunks arrive out of order and more than once, so nothing here assumes the previous chunk was
    the last one: progress only moves forward, the per-phase high-water mark is the maximum seen,
    and a chunk that arrives twice changes no number.
    """
    run = await _get_run(
        session, tenant_id, phone_number_id=phone_number_id, sync_type=sync_type, epoch=epoch
    )
    if run is None:
        return None
    run.state = "completed" if (progress or 0) >= 100 else "in_progress"
    if progress is not None:
        run.progress = max(run.progress or 0, min(100, int(progress)))
    phases = dict(run.phases or {})
    if phase is not None:
        bucket = dict(phases.get(str(phase)) or {})
        bucket["chunks"] = int(bucket.get("chunks") or 0) + 1
        if chunk_order is not None:
            bucket["last_order"] = max(int(bucket.get("last_order") or -1), int(chunk_order))
        phases[str(phase)] = bucket
        run.phases = phases
    run.chunks_seen = (run.chunks_seen or 0) + 1
    run.messages_stored = (run.messages_stored or 0) + max(0, messages_stored)
    if run.state == "completed":
        run.completed_at = datetime.now(UTC)
    await session.flush()
    return run
