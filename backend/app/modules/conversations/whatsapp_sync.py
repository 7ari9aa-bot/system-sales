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
    if run.state in {"pending", "dispatching", "in_progress", "completed", "requested"}:
        return False, "this connection already has a sync reservation or webhook activity; do not resend"
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


async def channel_epoch(
    session: AsyncSession, tenant_id: uuid.UUID, *, phone_number_id: str | None = None
) -> str | None:
    """The epoch of this tenant's live WhatsApp connection, or None when there is no channel.

    A webhook does not carry the epoch — it carries the phone number id — so the run row has to be
    found through the connection it belongs to.
    """
    from app.modules.platform.models import Integration

    row = (
        await session.execute(
            select(Integration).where(
                Integration.tenant_id == tenant_id,
                Integration.provider == "whatsapp",
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    config = row.config if isinstance(row.config, dict) else {}
    if phone_number_id and str(config.get("phone_number_id") or "") not in ("", phone_number_id):
        # A webhook for a number this workspace no longer owns: do not attribute its data.
        return None
    return epoch_for(config)


async def _request_sync_durable(
    tenant_id: uuid.UUID,
    *,
    phone_number_id: str,
    waba_id: str | None,
    epoch: str,
    onboarding_completed_at: datetime,
    sync_type: str,
    token: str,
    http: httpx.AsyncClient,
    now: datetime,
) -> WhatsAppSyncRun:
    """Persist the one-shot reservation in its own committed transaction before calling Meta.

    The HTTP request transaction may later roll back. This independent transaction makes the
    reservation survive that rollback, so a process crash cannot silently erase evidence that
    Meta may already have accepted the one-time request.
    """
    from app.core.db import SessionLocal, bind_tenant

    deadline = deadline_from(onboarding_completed_at)
    async with SessionLocal() as durable:
        async with durable.begin():
            await bind_tenant(durable, tenant_id)
            run = await _get_run(
                durable,
                tenant_id,
                phone_number_id=phone_number_id,
                sync_type=sync_type,
                epoch=epoch,
            )
            allowed, reason = may_request(run, now, deadline)
            if not allowed:
                if run is None:
                    raise ValidationError(f"Could not start the WhatsApp {sync_type} sync: {reason}.")
                return run
            run = WhatsAppSyncRun(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                phone_number_id=phone_number_id,
                waba_id=waba_id,
                sync_type=sync_type,
                onboarding_epoch=epoch,
                state="dispatching",
                attempts=1,
                deadline_at=deadline,
            )
            durable.add(run)
            await durable.flush()
        # Reservation is committed here, before any network side effect.

    try:
        request_id = await post_sync_request(
            http, phone_number_id=phone_number_id, token=token, sync_type=sync_type
        )
    except HistoryNotShared:
        async with SessionLocal() as durable:
            async with durable.begin():
                await bind_tenant(durable, tenant_id)
                run = await _get_run(
                    durable, tenant_id, phone_number_id=phone_number_id,
                    sync_type=sync_type, epoch=epoch
                )
                if run is not None:
                    run.state = "not_shared"
                    run.error = "the merchant chose not to share chat history"
                    run.requested_at = now
                    run.completed_at = datetime.now(UTC)
            return run
    except ExternalProviderError as exc:
        async with SessionLocal() as durable:
            async with durable.begin():
                await bind_tenant(durable, tenant_id)
                run = await _get_run(
                    durable, tenant_id, phone_number_id=phone_number_id,
                    sync_type=sync_type, epoch=epoch
                )
                if run is not None:
                    # Network failures may be ambiguous: keep the reservation non-retryable.
                    run.state = "dispatching" if exc.retryable else "failed"
                    run.error = str(exc)[:2000]
            raise
    except Exception:
        # Unknown transport outcome: leave the durable dispatching reservation in place.
        raise

    async with SessionLocal() as durable:
        async with durable.begin():
            await bind_tenant(durable, tenant_id)
            run = await _get_run(
                durable, tenant_id, phone_number_id=phone_number_id,
                sync_type=sync_type, epoch=epoch
            )
            if run is None:
                raise ExternalProviderError(
                    "WhatsApp sync reservation disappeared after Meta accepted the request."
                )
            run.request_id = request_id
            run.state = "requested"
            run.requested_at = now
        return run


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
    if isinstance(session, AsyncSession):
        return await _request_sync_durable(
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
    request_id: str | None = None,
    waba_id: str | None = None,
    chunk_key: str | None = None,
    contacts_snapshot_received: bool = False,
    not_shared: bool = False,
    error: str | None = None,
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
        if not phone_number_id:
            return None
        # The data arrived before the run row did — a request whose recording was lost with its
        # transaction, or a chunk that beat the flush. Creating the row keeps the progress (and
        # Meta's request id) visible instead of dropping the evidence on the floor.
        run = WhatsAppSyncRun(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            phone_number_id=phone_number_id,
            waba_id=waba_id,
            sync_type=sync_type,
            onboarding_epoch=epoch,
            state="in_progress",
            request_id=request_id,
        )
        session.add(run)
        await session.flush()
    if request_id and not run.request_id:
        run.request_id = request_id
    phases = dict(run.phases or {})
    seen = list(phases.get("_seen_chunk_keys") or [])
    effective_key = chunk_key or (
        f"{sync_type}:{phase}:{chunk_order}:{progress}:{request_id or ''}"
        if phase is not None or chunk_order is not None or progress is not None
        else None
    )
    if effective_key and effective_key in seen:
        return run
    if effective_key:
        # Keep bounded per-run dedupe metadata; a history transfer has a finite number of chunks.
        phases["_seen_chunk_keys"] = (seen + [effective_key])[-2048:]
    if progress is not None:
        run.progress = max(run.progress or 0, min(100, int(progress)))
    # History has Meta's explicit terminal marker. Contact state sync does not: the first
    # initial snapshot is the only observable initial-sync event; subsequent adds/updates are live.
    if not_shared and sync_type == WHATSAPP_SYNC_HISTORY:
        run.state = "not_shared"
        run.error = str(error or "the merchant chose not to share chat history")[:2000]
        run.completed_at = run.completed_at or datetime.now(UTC)
    elif sync_type == WHATSAPP_SYNC_CONTACTS and contacts_snapshot_received:
        run.state = "completed"
        run.progress = 100
        run.completed_at = run.completed_at or datetime.now(UTC)
    elif run.state == "not_shared":
        # A decline is terminal too: a late/duplicate history chunk cannot reopen it.
        pass
    elif (run.progress or 0) >= 100:
        run.state = "completed"
        run.completed_at = run.completed_at or datetime.now(UTC)
    elif run.state != "completed":
        run.state = "in_progress"
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


#: What each state means to a person, in the two languages the inbox speaks. The screen never
#: invents a sentence of its own: one word per state, so "connected" can never read as "synced".
STATE_COPY: dict[str, dict[str, str]] = {
    STATE_ONBOARDING: {"en": "Finishing the link with Meta", "ar": "بيكمّل الربط مع Meta"},
    STATE_CONNECTED_PENDING_SYNC: {
        "en": "Connected. Contacts and history are about to sync",
        "ar": "اتوصل. جهات الاتصال والمحادثات هتتزامن حالاً",
    },
    STATE_CONTACTS_SYNC_PENDING: {
        "en": "Waiting for Meta to send your WhatsApp contacts",
        "ar": "مستنيين Meta تبعت جهات اتصال واتساب",
    },
    STATE_CONTACTS_SYNC_IN_PROGRESS: {
        "en": "Importing your WhatsApp contacts",
        "ar": "بنجيب جهات اتصال واتساب",
    },
    STATE_CONTACTS_SYNC_COMPLETED: {
        "en": "Initial WhatsApp contacts received",
        "ar": "وصلت بيانات جهات الاتصال الأولية من واتساب",
    },
    STATE_HISTORY_SYNC_PENDING: {
        "en": "Waiting for Meta to send your chat history",
        "ar": "مستنيين Meta تبعت سجل المحادثات",
    },
    STATE_HISTORY_SYNC_IN_PROGRESS: {
        "en": "Importing your chat history",
        "ar": "بنجيب سجل المحادثات",
    },
    STATE_HISTORY_SYNC_COMPLETED: {
        "en": "Chat history imported",
        "ar": "سجل المحادثات اتجاب",
    },
    STATE_HISTORY_NOT_SHARED: {
        "en": "You chose not to share chat history. The app and FIHRIST both work",
        "ar": "اخترت إنك ما تشاركش سجل المحادثات. التطبيق وفهرست شغالين",
    },
    STATE_READY: {"en": "Contacts and history are synced", "ar": "جهات الاتصال والسجل اتزامنوا"},
    STATE_SYNC_FAILED: {
        "en": "Meta stopped the data sync. Re-link the number to try again",
        "ar": "Meta وقفت مزامنة البيانات. اربط الرقم تاني للمحاولة",
    },
    STATE_OFFBOARDED: {
        "en": "This number was removed from FIHRIST",
        "ar": "الرقم ده اتشال من فهرست",
    },
}


def run_snapshot(run: WhatsAppSyncRun | None) -> dict | None:
    """One sync row as the screen reads it: a word, a percentage, a count, a deadline.

    No request id and no raw Meta error: the id is internal bookkeeping and the error text is
    Meta's, not the shop's. ``progress`` is None when nothing was requested yet — an empty bar
    reads as "nothing happened", which is the honest picture.
    """
    if run is None:
        return None
    return {
        "sync_type": run.sync_type,
        "state": run.state,
        "progress": int(run.progress or 0),
        "messages_stored": int(run.messages_stored or 0),
        "chunks": int(run.chunks_seen or 0),
        "requested_at": run.requested_at.isoformat() if run.requested_at else None,
        "deadline_at": run.deadline_at.isoformat() if run.deadline_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "error": (run.error or None) and str(run.error)[:280],
    }


async def sync_snapshot(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    config: dict,
    offboarded: bool = False,
    now: datetime | None = None,
) -> dict:
    """The whole coexistence picture for one connection, computed from the run rows.

    Stored ``config["sync_state"]`` is only a cache written at connect time; it goes stale the
    moment a history chunk lands. This recomputes from Postgres, so the inbox banner and the
    settings card tell the same story as the webhook that just arrived.
    """
    now = now or datetime.now(UTC)
    phone_number_id = str(config.get("phone_number_id") or "")
    epoch = epoch_for(config)
    runs = (
        await load_runs(session, tenant_id, phone_number_id=phone_number_id, epoch=epoch)
        if phone_number_id
        else {WHATSAPP_SYNC_CONTACTS: None, WHATSAPP_SYNC_HISTORY: None}
    )
    contacts = runs.get(WHATSAPP_SYNC_CONTACTS)
    history = runs.get(WHATSAPP_SYNC_HISTORY)
    state = channel_sync_state(contacts, history, offboarded=offboarded, now=now)
    copy = STATE_COPY.get(state) or STATE_COPY[STATE_CONNECTED_PENDING_SYNC]
    deadlines = [r.deadline_at for r in (contacts, history) if r is not None and r.deadline_at]
    deadline = min(deadlines) if deadlines else None
    return {
        "onboarding_mode": config.get("onboarding_mode") or None,
        "coexistence_status": config.get("coexistence_status") or "unknown",
        "is_on_biz_app": config.get("is_on_biz_app")
        if isinstance(config.get("is_on_biz_app"), bool)
        else None,
        "platform_type": config.get("platform_type") or None,
        "sync_state": state,
        "sync_label": copy,
        "ready": is_ready(state),
        "offboarded": bool(offboarded),
        "deadline_at": deadline.isoformat() if deadline else None,
        "contacts": run_snapshot(contacts),
        "history": run_snapshot(history),
    }
