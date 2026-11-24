"""The WhatsApp Business App data sync: requested once, inside 24 hours, followed to the end.

Meta's own rules, and the two ways a channel can look synced while it is not:

* the request must be sent within 24 hours of onboarding, and each kind may be sent ONCE per
  connection (a second one needs an offboarding and a fresh link);
* a response without a ``request_id`` cannot be followed, so it is not a success;
* a merchant who declined history (2593109) has a CONNECTED channel, not a broken one.

The DB-backed half (rows, uniqueness, chunk folding) needs Postgres and is covered by the service
tests CI runs; everything decided here is pure and runs everywhere.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from app.core.errors import ExternalProviderError, ValidationError
from app.modules.conversations import whatsapp_sync as sync
from app.modules.conversations.models import WhatsAppSyncRun


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _run(**overrides) -> WhatsAppSyncRun:
    """An unflushed run row — plain ORM state, no database needed."""
    fields = {
        "phone_number_id": "456",
        "sync_type": "history",
        "onboarding_epoch": "2026-11-24T00:00:00+00:00",
        "state": "pending",
    }
    fields.update(overrides)
    return WhatsAppSyncRun(**fields)


NOW = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


# ---------- the wire call ----------


async def test_the_request_uses_metas_documented_body() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.append(json.loads(request.content))
        assert request.url.path.endswith("/456/smb_app_data")
        return httpx.Response(200, json={"request_id": "req-1"})

    async with _client(handler) as client:
        request_id = await sync.post_sync_request(
            client, phone_number_id="456", token="t", sync_type="contacts"
        )

    assert request_id == "req-1"
    assert seen == [{"messaging_product": "whatsapp", "sync_type": "smb_app_state_sync"}]


async def test_history_uses_its_own_wire_value() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"request_id": "req-2"})

    async with _client(handler) as client:
        await sync.post_sync_request(client, phone_number_id="456", token="t", sync_type="history")
    assert seen[0]["sync_type"] == "history"


async def test_a_declined_history_is_not_a_failure() -> None:
    """2593109 is the merchant's choice; the channel stays connected."""
    async with _client(
        lambda request: httpx.Response(400, json={"error": {"code": 2593109}})
    ) as client:
        with pytest.raises(sync.HistoryNotShared):
            await sync.post_sync_request(
                client, phone_number_id="456", token="t", sync_type="history"
            )


async def test_the_same_code_on_a_contacts_request_is_a_real_refusal() -> None:
    async with _client(
        lambda request: httpx.Response(400, json={"error": {"code": 2593109}})
    ) as client:
        with pytest.raises(ExternalProviderError):
            await sync.post_sync_request(
                client, phone_number_id="456", token="t", sync_type="contacts"
            )


async def test_a_response_without_a_request_id_is_not_a_success() -> None:
    """Without a handle the transfer cannot be followed, so "ok" would be a lie."""
    async with _client(lambda request: httpx.Response(200, json={"success": True})) as client:
        with pytest.raises(ExternalProviderError, match="request id"):
            await sync.post_sync_request(
                client, phone_number_id="456", token="t", sync_type="contacts"
            )


async def test_an_error_body_inside_a_200_is_refused() -> None:
    async with _client(
        lambda request: httpx.Response(200, json={"error": {"message": "denied"}})
    ) as client:
        with pytest.raises(ExternalProviderError):
            await sync.post_sync_request(
                client, phone_number_id="456", token="t", sync_type="contacts"
            )


async def test_meta_outages_stay_retryable() -> None:
    async with _client(lambda request: httpx.Response(503, json={})) as client:
        with pytest.raises(ExternalProviderError) as exc_info:
            await sync.post_sync_request(
                client, phone_number_id="456", token="t", sync_type="contacts"
            )
    assert exc_info.value.retryable is True


async def test_an_unknown_sync_kind_never_reaches_meta() -> None:
    async with _client(lambda request: httpx.Response(200, json={"request_id": "x"})) as client:
        with pytest.raises(ValidationError):
            await sync.post_sync_request(
                client, phone_number_id="456", token="t", sync_type="call_log"
            )


# ---------- sent once ----------


def test_a_fresh_connection_inside_the_window_may_ask() -> None:
    allowed, reason = sync.may_request(None, NOW, sync.deadline_from(NOW - timedelta(hours=1)))
    assert allowed and reason == ""


def test_a_connection_past_the_window_may_not_ask() -> None:
    """Meta closes the door at 24 hours; after that the answer is a re-link, not a retry."""
    deadline = sync.deadline_from(NOW - timedelta(hours=25))
    allowed, reason = sync.may_request(None, NOW, deadline)
    assert not allowed and "24-hour" in reason


def test_a_run_that_already_has_a_request_id_is_never_sent_again() -> None:
    """The request Meta allows once must survive a retry, a restart and a second click."""
    run = _run(request_id="req-1", state="requested")
    allowed, reason = sync.may_request(run, NOW, sync.deadline_from(NOW))
    assert not allowed and "already asked" in reason


def test_a_failed_run_needs_a_re_link_not_a_retry() -> None:
    run = _run(state="failed")
    allowed, reason = sync.may_request(run, NOW, sync.deadline_from(NOW))
    assert not allowed and "re-linking" in reason


def test_a_declined_history_is_never_asked_again() -> None:
    run = _run(state="not_shared")
    allowed, reason = sync.may_request(run, NOW, sync.deadline_from(NOW))
    assert not allowed and "chat history" in reason


def test_the_window_is_24_hours_from_onboarding() -> None:
    start = datetime(2026, 11, 24, 9, 30, tzinfo=UTC)
    assert sync.deadline_from(start) == start + timedelta(hours=24)


# ---------- the connection's identity ----------


def test_the_epoch_comes_from_the_coexistence_stamp() -> None:
    assert sync.epoch_for({"coexistence_verified_at": "2026-11-24T00:00:00+00:00"}) == (
        "2026-11-24T00:00:00+00:00"
    )


def test_a_channel_without_the_stamp_still_has_one_stable_epoch() -> None:
    """Two requests for the same number must resolve to the same row, not two rows."""
    assert sync.epoch_for({"phone_number_id": "456"}) == sync.epoch_for({"phone_number_id": "456"})


# ---------- the state the screen shows ----------


def _contacts(state: str, **overrides) -> WhatsAppSyncRun:
    return _run(sync_type="contacts", state=state, **overrides)


def _history(state: str, **overrides) -> WhatsAppSyncRun:
    return _run(sync_type="history", state=state, **overrides)


def test_ready_needs_both_halves_settled() -> None:
    assert sync.channel_sync_state(_contacts("completed"), _history("completed")) == "READY"
    assert sync.channel_sync_state(_contacts("completed"), _history("not_shared")) == (
        "HISTORY_NOT_SHARED"
    )


def test_contacts_in_flight_is_not_ready() -> None:
    assert sync.channel_sync_state(_contacts("requested"), _history("completed")) == (
        "CONTACTS_SYNC_PENDING"
    )
    assert sync.channel_sync_state(_contacts("in_progress"), _history("completed")) == (
        "CONTACTS_SYNC_IN_PROGRESS"
    )


def test_history_in_flight_is_not_ready() -> None:
    assert sync.channel_sync_state(_contacts("completed"), _history("requested")) == (
        "HISTORY_SYNC_IN_PROGRESS"
    )


def test_a_refused_or_expired_request_is_visible() -> None:
    assert sync.channel_sync_state(_contacts("failed"), _history("completed")) == "SYNC_FAILED"
    assert sync.channel_sync_state(_contacts("completed"), _history("expired")) == "SYNC_FAILED"


def test_no_runs_yet_is_pending_sync_not_ready() -> None:
    assert sync.channel_sync_state(None, None) == "CONNECTED_PENDING_SYNC"


def test_an_offboarded_channel_outranks_every_other_state() -> None:
    assert sync.channel_sync_state(
        _contacts("completed"), _history("completed"), offboarded=True
    ) == ("OFFBOARDED")


def test_is_ready_accepts_a_declined_history() -> None:
    assert sync.is_ready("READY") is True
    assert sync.is_ready("HISTORY_NOT_SHARED") is True
    assert sync.is_ready("CONTACTS_SYNC_PENDING") is False


# ---------- the request path: sent once, and the row says so ----------
#
# These run the REAL ``request_sync`` against a session stub instead of Postgres, so the rules that
# matter most (one request per connection, request_id kept, the row written before the call) are
# checked on every machine, not only where a database happens to be configured.


class _FakeSession:
    """Enough of an AsyncSession for the request path: add + flush, no database."""

    def __init__(self) -> None:
        self.rows: list[WhatsAppSyncRun] = []
        self.flushes = 0

    def add(self, obj: object) -> None:
        self.rows.append(obj)  # type: ignore[arg-type]

    async def flush(self) -> None:
        self.flushes += 1


TENANT = uuid.uuid4()
EPOCH = "2026-11-24T00:00:00+00:00"
ONBOARDED = NOW - timedelta(minutes=30)


@pytest.fixture
def session(monkeypatch) -> _FakeSession:
    """The request path's session, with row lookup answered from memory."""
    fake = _FakeSession()

    async def _get_run(_session, tenant_id, *, phone_number_id, sync_type, epoch):
        for row in fake.rows:
            if (
                row.tenant_id == tenant_id
                and row.phone_number_id == phone_number_id
                and row.sync_type == sync_type
                and row.onboarding_epoch == epoch
            ):
                return row
        return None

    monkeypatch.setattr(sync, "_get_run", _get_run)
    return fake


def _ask(session, client, **overrides):
    kwargs = {
        "phone_number_id": "456",
        "waba_id": "999",
        "epoch": EPOCH,
        "onboarding_completed_at": ONBOARDED,
        "sync_type": sync.WHATSAPP_SYNC_HISTORY,
        "token": "t",
        "http": client,
        "now": NOW,
    }
    kwargs.update(overrides)
    return sync.request_sync(session, TENANT, **kwargs)


async def test_the_row_is_written_before_meta_is_called(session) -> None:
    """A crash between "sent" and "answered" must leave evidence, not a clean slate."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.extend(row.state for row in session.rows)
        return httpx.Response(200, json={"request_id": "req-1"})

    async with _client(handler) as client:
        await _ask(session, client)

    assert seen == ["pending"], "the run row must exist (and be flushed) before the request"


async def test_the_request_id_and_instant_are_persisted(session) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"request_id": "req-1"})

    async with _client(handler) as client:
        run = await _ask(session, client)

    assert run.request_id == "req-1"
    assert run.state == "requested"
    assert run.requested_at == NOW
    assert run.attempts == 1
    assert run.deadline_at == ONBOARDED + timedelta(hours=24)


async def test_a_second_request_sends_nothing_and_keeps_the_first_id(session) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"request_id": f"req-{len(calls)}"})

    async with _client(handler) as client:
        first = await _ask(session, client)
        second = await _ask(session, client)

    assert calls == [calls[0]], "Meta allows ONE request per connection; a retry must not send"
    assert second.request_id == first.request_id == "req-1"
    assert len(session.rows) == 1, "a retry must hit the same row, never a second one"


async def test_past_the_window_nothing_is_sent(session) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"request_id": "req-1"})

    async with _client(handler) as client:
        with pytest.raises(ValidationError, match="24-hour window"):
            await _ask(session, client, onboarding_completed_at=NOW - timedelta(hours=25))

    assert calls == []
    assert session.rows == []


async def test_a_refusal_is_recorded_as_failed_without_a_request_id(session) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"code": 100, "message": "nope"}})

    async with _client(handler) as client:
        with pytest.raises(ExternalProviderError):
            await _ask(session, client)

    (run,) = session.rows
    assert run.state == "failed"
    assert run.request_id is None
    assert "refused" in (run.error or "")


async def test_a_declined_history_is_recorded_as_not_shared(session) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"code": 2593109, "message": "declined"}})

    async with _client(handler) as client:
        run = await _ask(session, client)

    assert run.state == "not_shared"
    assert run.request_id is None
    assert sync.channel_sync_state(None, run) == sync.STATE_HISTORY_NOT_SHARED


# ---------- the migration has to carry tenant isolation ----------

SYNC_MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "migrations"
    / "versions"
    / "fe2026112401_whatsapp_coexistence_sync.py"
)


def test_the_sync_table_is_tenant_isolated_in_the_migration() -> None:
    """RLS is defence in depth; provision.py sweeps it too, but the migration must not lag."""
    ddl = SYNC_MIGRATION.read_text()
    assert "ENABLE ROW LEVEL SECURITY" in ddl
    assert "FORCE ROW LEVEL SECURITY" in ddl
    assert "tenant_isolation" in ddl
    assert "app.tenant_id" in ddl
    assert "DROP POLICY IF EXISTS tenant_isolation ON public.whatsapp_sync_runs" in ddl


async def test_replayed_chunk_key_does_not_double_count_progress_or_messages(session) -> None:
    run = _run()
    session.rows.append(run)
    kwargs = {
        "phone_number_id": "456",
        "epoch": EPOCH,
        "sync_type": sync.WHATSAPP_SYNC_HISTORY,
        "phase": 1,
        "chunk_order": 4,
        "progress": 45,
        "messages_stored": 3,
        "request_id": "req-1",
        "chunk_key": "chunk-stable-key",
    }
    first = await sync.record_chunk(session, TENANT, **kwargs)
    second = await sync.record_chunk(session, TENANT, **kwargs)
    assert first is second is run
    assert run.chunks_seen == 1
    assert run.messages_stored == 3
    assert run.progress == 45


async def test_initial_contacts_snapshot_settles_without_inventing_meta_progress(session) -> None:
    run = _run(sync_type=sync.WHATSAPP_SYNC_CONTACTS)
    session.rows.append(run)
    await sync.record_chunk(
        session,
        TENANT,
        phone_number_id="456",
        epoch=EPOCH,
        sync_type=sync.WHATSAPP_SYNC_CONTACTS,
        request_id="req-contacts",
        chunk_key="contacts-snapshot",
        contacts_snapshot_received=True,
    )
    assert run.state == "completed"
    assert run.progress == 100
    assert sync.channel_sync_state(run, _history("completed")) == sync.STATE_READY


async def test_history_webhook_decline_marks_run_not_shared(session) -> None:
    run = _run(sync_type=sync.WHATSAPP_SYNC_HISTORY)
    session.rows.append(run)
    await sync.record_chunk(
        session,
        TENANT,
        phone_number_id="456",
        epoch=EPOCH,
        sync_type=sync.WHATSAPP_SYNC_HISTORY,
        request_id="req-history",
        chunk_key="declined-history",
        not_shared=True,
        error="User declined history",
    )
    assert run.state == "not_shared"
    assert "declined" in run.error
