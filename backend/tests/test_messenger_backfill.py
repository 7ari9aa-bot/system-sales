"""Messenger history is read from Meta and stored without waking anything.

Meta is a fake (``httpx.MockTransport``) that serves threads, a thread's message ids, and each
message's details, and can answer the way the real one does when a message is too old
("deleted") or the app is being throttled. The database is real.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import func, select

from app.modules.conversations.gateway import messenger_backfill as mb
from app.modules.conversations.models import Conversation, Message
from app.modules.customers.models import CustomerIdentity

PAGE = "page-1"
NOW = datetime.now(UTC)


def _iso(delta: timedelta) -> str:
    return (NOW - delta).strftime("%Y-%m-%dT%H:%M:%S+0000")


def _thread(tid, psid, name, age=timedelta(days=1)):
    return {
        "id": tid,
        "updated_time": _iso(age),
        "participants": {"data": [{"id": PAGE, "name": "Shop"}, {"id": psid, "name": name}]},
    }


def _msg(mid, sender, text, age, **extra):
    return {
        "id": mid,
        "created_time": _iso(age),
        "from": {"id": sender, "name": "x"},
        "message": text,
        **extra,
    }


class FakeMeta:
    """Threads, per-thread message ids (newest first), message details; counts every read."""

    def __init__(self, threads, messages, *, throttle_after=None, deleted=(), next_page=None):
        self.threads = threads
        self.messages = messages  # id -> message dict
        self.by_thread: dict[str, list[str]] = {}
        self.throttle_after = throttle_after
        self.deleted = set(deleted)
        self.next_page = next_page
        self.reads = 0
        self.calls: list[str] = []

    def thread_messages(self, tid, ids):
        self.by_thread[tid] = ids

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        self.calls.append(str(url))
        self.reads += 1
        if self.throttle_after is not None and self.reads > self.throttle_after:
            return httpx.Response(429, json={"error": {"code": 4, "message": "limit"}})
        path = url.path.rsplit("/", 1)[-1]
        params = dict(url.params)
        if path == "conversations":
            body = {"data": self.threads}
            if self.next_page:
                body["paging"] = {"cursors": {"after": self.next_page}, "next": "https://x"}
            return httpx.Response(200, json=body)
        if path in self.by_thread:
            limit = int(params["fields"].split("limit(")[1].split(")")[0])
            ids = self.by_thread[path][:limit]
            return httpx.Response(
                200,
                json={
                    "messages": {"data": [{"id": i, "created_time": "x"} for i in ids]},
                    "id": path,
                },
            )
        if path in self.deleted:
            return httpx.Response(
                400, json={"error": {"code": 100, "message": "This message was deleted"}}
            )
        if path in self.messages:
            return httpx.Response(200, json=self.messages[path])
        return httpx.Response(404, json={"error": {"code": 100, "message": "unknown"}})

    def client(self):
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


async def _run(db, tenant_ctx, meta, **kw):
    async with meta.client() as http:
        return await mb.run_page(
            db, tenant_ctx.tenant_id, page_id=PAGE, token="tok", http=http, pause=0, **kw
        )


async def _count(db, model, tenant_ctx, *where):
    return (
        await db.execute(
            select(func.count())
            .select_from(model)
            .where(model.tenant_id == tenant_ctx.tenant_id, *where)
        )
    ).scalar_one()


def _simple_meta(**kw):
    meta = FakeMeta(
        [_thread("t1", "psid-1", "Mona")],
        {
            "m1": _msg("m1", "psid-1", "هل متوفر؟", timedelta(days=2)),
            "m2": _msg("m2", PAGE, "نعم متوفر", timedelta(days=2) - timedelta(minutes=5)),
        },
        **kw,
    )
    meta.thread_messages("t1", ["m2", "m1"])  # newest first, as Meta lists them
    return meta


# ------------------------------------------------------------------ pure parsing


def test_meta_times_with_and_without_a_colon_in_the_offset_are_read():
    assert mb.parse_time("2022-07-12T19:11:07+0000") == datetime(2022, 7, 12, 19, 11, 7, tzinfo=UTC)
    assert mb.parse_time("2022-07-12T19:11:07+00:00") == datetime(
        2022, 7, 12, 19, 11, 7, tzinfo=UTC
    )
    assert mb.parse_time(1657653067).year == 2022
    assert mb.parse_time("nonsense") is None and mb.parse_time(None) is None


def test_a_page_reply_is_outbound_and_a_customer_message_is_inbound():
    mine = mb.message_parts(_msg("a", PAGE, "hi", timedelta(hours=1)), page_id=PAGE)
    theirs = mb.message_parts(_msg("b", "psid-1", "hi", timedelta(hours=1)), page_id=PAGE)
    assert mine["from_page"] is True and theirs["from_page"] is False


def test_a_message_with_no_words_and_no_attachment_is_not_stored():
    assert mb.message_parts(_msg("a", "p", "", timedelta(hours=1)), page_id=PAGE) is None
    assert mb.message_parts(_msg("a", "p", "   ", timedelta(hours=1)), page_id=PAGE) is None


def test_a_message_missing_its_id_sender_or_time_is_not_stored():
    base = _msg("a", "p", "hi", timedelta(hours=1))
    for broken in ({**base, "id": None}, {**base, "from": {}}, {**base, "created_time": None}):
        assert mb.message_parts(broken, page_id=PAGE) is None


def test_attachments_become_one_message_each_and_only_the_first_keeps_the_text():
    atts = {
        "data": [
            {"id": "1", "mime_type": "image/jpeg", "file_url": "https://cdn/1.jpg"},
            {"id": "2", "mime_type": "video/mp4", "file_url": "https://cdn/2.mp4"},
            {"id": "3", "mime_type": "audio/mpeg", "file_url": "https://cdn/3.mp3"},
            {"id": "4", "mime_type": "application/pdf", "file_url": "https://cdn/4.pdf"},
        ]
    }
    parsed = mb.message_parts(
        _msg("m", "p", "caption", timedelta(hours=1), attachments=atts), page_id=PAGE
    )
    assert [p["mid"] for p in parsed["parts"]] == ["m", "m#1", "m#2", "m#3"]
    assert [p["content_type"] for p in parsed["parts"]] == ["image", "video", "voice", "file"]
    assert [p["body"] for p in parsed["parts"]] == ["caption", None, None, None]


def test_an_attachment_without_a_link_is_kept_as_unsupported():
    atts = {"data": [{"id": "1", "mime_type": "image/jpeg"}]}
    parsed = mb.message_parts(
        _msg("m", "p", None, timedelta(hours=1), attachments=atts), page_id=PAGE
    )
    assert parsed["parts"][0]["content_type"] == "unsupported"
    assert parsed["parts"][0]["media_url"] is None


def test_the_customer_is_the_participant_who_is_not_the_page():
    assert mb.customer_of(_thread("t", "psid-9", "Sara"), page_id=PAGE) == ("psid-9", "Sara")
    only_page = {"id": "t", "participants": {"data": [{"id": PAGE}]}}
    assert mb.customer_of(only_page, page_id=PAGE) is None


# ------------------------------------------------------------------ writing


async def test_history_is_stored_with_its_real_times_and_directions(db, tenant_ctx):
    result = await _run(db, tenant_ctx, _simple_meta())
    assert (result.threads_seen, result.messages_written, result.customers_created) == (1, 2, 1)
    rows = (
        (
            await db.execute(
                select(Message)
                .where(Message.tenant_id == tenant_ctx.tenant_id)
                .order_by(Message.created_at)
            )
        )
        .scalars()
        .all()
    )
    assert [(m.direction, m.sender_type, m.body) for m in rows] == [
        ("inbound", "customer", "هل متوفر؟"),
        ("outbound", "agent", "نعم متوفر"),
    ]
    assert rows[0].created_at < rows[1].created_at  # Meta's time, not "now"
    assert abs((NOW - timedelta(days=2)) - rows[0].created_at) < timedelta(minutes=1)
    assert {m.provider_metadata["source"] for m in rows} == {"messenger_backfill"}


async def test_running_it_twice_writes_nothing_the_second_time(db, tenant_ctx):
    await _run(db, tenant_ctx, _simple_meta())
    again = await _run(db, tenant_ctx, _simple_meta())
    assert again.messages_written == 0 and again.messages_known == 2
    assert await _count(db, Message, tenant_ctx) == 2


async def test_a_message_the_webhook_already_delivered_is_not_stored_again(db, tenant_ctx):
    meta = _simple_meta()
    await _run(db, tenant_ctx, meta)
    # Same provider id, as a live delivery would have stored it: a fresh run must see it as known.
    result = await _run(db, tenant_ctx, _simple_meta())
    assert result.messages_written == 0
    assert await _count(db, Message, tenant_ctx, Message.channel_message_id == "m1") == 1


async def _with_sla_policy(db, tenant_ctx):
    """A default SLA policy, so a clock WOULD start if anything asked for one."""
    from app.modules.operations.models import SLAPolicy

    db.add(
        SLAPolicy(
            tenant_id=tenant_ctx.tenant_id,
            name="default",
            first_response_minutes=60,
            is_default=True,
            status="active",
        )
    )
    await db.flush()


async def _sla_clocks(db, tenant_ctx) -> int:
    from app.modules.operations.models import SLAEvent

    return await _count(db, SLAEvent, tenant_ctx)


async def _outbox_for(db, tenant_ctx) -> int:
    from app.modules.platform.models import OutboxEvent

    return (
        await db.execute(
            select(func.count())
            .select_from(OutboxEvent)
            .where(OutboxEvent.payload["tenant_id"].astext == str(tenant_ctx.tenant_id))
        )
    ).scalar_one()


async def test_no_clock_starts_and_no_event_is_queued_for_old_messages(db, tenant_ctx):
    """A customer message from last month must not start a first-response clock or wake the AI."""
    await _with_sla_policy(db, tenant_ctx)
    await _run(db, tenant_ctx, _simple_meta())
    assert await _sla_clocks(db, tenant_ctx) == 0
    assert await _outbox_for(db, tenant_ctx) == 0


async def test_the_live_path_does_start_a_clock_and_queue_an_event_so_the_check_can_fail(
    db, tenant_ctx
):
    """The control for the test above: the same customer message through live ingest is exactly
    what backfill must avoid. If this stopped producing a clock, the test above would prove
    nothing."""
    from app.modules.conversations.gateway.base import InboundMessage
    from app.modules.conversations.gateway.ingest import IngestService

    await _with_sla_policy(db, tenant_ctx)
    live = InboundMessage(
        channel="messenger",
        customer_ref="psid-live",
        channel_message_id="live-1",
        body="hello",
        customer_name="Live",
    )
    await IngestService.ingest(
        db, tenant_id=tenant_ctx.tenant_id, message=live, idempotency_scope="messenger"
    )
    assert await _sla_clocks(db, tenant_ctx) == 1


async def test_a_backfilled_thread_is_not_unread_and_is_not_handed_to_anyone(db, tenant_ctx):
    await _run(db, tenant_ctx, _simple_meta())
    [conv] = (
        (
            await db.execute(
                select(Conversation).where(Conversation.tenant_id == tenant_ctx.tenant_id)
            )
        )
        .scalars()
        .all()
    )
    assert conv.unread_count == 0
    assert conv.status == "open" and conv.channel == "messenger"


async def test_the_reply_window_anchor_is_the_customers_last_message_not_the_pages(db, tenant_ctx):
    await _run(db, tenant_ctx, _simple_meta())
    [conv] = (
        (
            await db.execute(
                select(Conversation).where(Conversation.tenant_id == tenant_ctx.tenant_id)
            )
        )
        .scalars()
        .all()
    )
    customer_msg = NOW - timedelta(days=2)
    assert abs(conv.last_customer_message_at - customer_msg) < timedelta(minutes=1)
    assert conv.last_message_at > conv.last_customer_message_at  # the page replied after


async def test_an_old_message_never_moves_a_thread_back_in_time(db, tenant_ctx):
    """A live message already set the clocks; a backfilled older one must not rewind them."""
    await _run(db, tenant_ctx, _simple_meta())
    [conv] = (
        (
            await db.execute(
                select(Conversation).where(Conversation.tenant_id == tenant_ctx.tenant_id)
            )
        )
        .scalars()
        .all()
    )
    live = NOW - timedelta(minutes=3)
    conv.last_message_at = live
    conv.last_customer_message_at = live
    older = FakeMeta(
        [_thread("t1", "psid-1", "Mona")],
        {"m0": _msg("m0", "psid-1", "earlier", timedelta(days=5))},
    )
    older.thread_messages("t1", ["m0"])
    await _run(db, tenant_ctx, older)
    await db.refresh(conv)
    assert conv.last_message_at == live and conv.last_customer_message_at == live


async def test_an_existing_customer_and_thread_are_reused_not_duplicated(db, tenant_ctx):
    await _run(db, tenant_ctx, _simple_meta())
    meta = _simple_meta()
    meta.messages["m3"] = _msg("m3", "psid-1", "one more", timedelta(days=1))
    meta.thread_messages("t1", ["m3", "m2", "m1"])
    result = await _run(db, tenant_ctx, meta)
    assert result.customers_created == 0 and result.messages_written == 1
    assert (
        await _count(db, CustomerIdentity, tenant_ctx, CustomerIdentity.channel == "messenger") == 1
    )
    assert await _count(db, Conversation, tenant_ctx) == 1


async def test_another_tenants_history_is_invisible_to_this_one(db, tenant_ctx):
    await _run(db, tenant_ctx, _simple_meta())
    other = uuid.uuid4()
    assert (
        await db.execute(
            select(func.count()).select_from(Message).where(Message.tenant_id == other)
        )
    ).scalar_one() == 0


# ------------------------------------------------------------------ Meta's limits


async def test_a_message_too_old_to_read_is_skipped_and_counted_not_fatal(db, tenant_ctx):
    meta = _simple_meta(deleted={"m1"})
    result = await _run(db, tenant_ctx, meta)
    assert result.messages_unreadable == 1 and result.messages_written == 1
    assert result.stopped_reason is None


async def test_the_per_thread_cap_is_passed_to_meta(db, tenant_ctx):
    meta = _simple_meta()
    result = await _run(db, tenant_ctx, meta, max_messages=1)
    assert result.messages_written == 1  # only the newest id was asked for
    from urllib.parse import unquote

    assert any("messages.limit(1)" in unquote(c) for c in meta.calls)


async def test_a_throttled_run_stops_cleanly_and_can_resume_from_its_page(db, tenant_ctx):
    meta = _simple_meta(throttle_after=2)  # threads + ids answer, then Meta says slow down
    result = await _run(db, tenant_ctx, meta, cursor="CUR-1")
    assert result.stopped_reason == "rate_limited"
    assert result.next_cursor == "CUR-1"  # the page that was interrupted, so a retry resumes there


async def test_a_high_usage_header_stops_the_run_before_the_block(db, tenant_ctx):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"data": []}, headers={"x-app-usage": '{"call_count": 91, "total_time": 10}'}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await mb.run_page(
            db, tenant_ctx.tenant_id, page_id=PAGE, token="t", http=http, pause=0
        )
    assert result.stopped_reason == "rate_limited"


async def test_threads_older_than_the_window_end_the_run(db, tenant_ctx):
    old = _thread("t-old", "psid-9", "Old", age=timedelta(days=200))
    meta = FakeMeta([_thread("t1", "psid-1", "Mona"), old], _simple_meta().messages)
    meta.thread_messages("t1", ["m2", "m1"])
    meta.thread_messages("t-old", ["m1"])
    result = await _run(db, tenant_ctx, meta)
    assert result.threads_seen == 1 and result.stopped_reason == "window_reached"
    assert result.next_cursor is None


async def test_messages_before_the_cutoff_inside_a_recent_thread_are_left_out(db, tenant_ctx):
    meta = _simple_meta()
    result = await _run(db, tenant_ctx, meta, since=NOW - timedelta(days=1))
    assert result.messages_written == 0  # both are two days old


async def test_the_thread_cap_stops_the_run_and_more_pages_are_followed_by_cursor(db, tenant_ctx):
    threads = [_thread(f"t{i}", f"psid-{i}", f"C{i}") for i in range(3)]
    msgs = {f"m{i}": _msg(f"m{i}", f"psid-{i}", f"hi {i}", timedelta(days=1)) for i in range(3)}
    meta = FakeMeta(threads, msgs, next_page="NEXT")
    for i in range(3):
        meta.thread_messages(f"t{i}", [f"m{i}"])
    capped = await _run(db, tenant_ctx, meta, max_threads=2)
    assert capped.threads_seen == 2 and capped.stopped_reason == "thread_cap"

    follow = FakeMeta(threads[:1], {"m0": msgs["m0"]}, next_page="NEXT")
    follow.thread_messages("t0", ["m0"])
    page = await _run(db, tenant_ctx, follow, max_threads=50)
    assert page.next_cursor == "NEXT"


async def test_a_thread_with_no_other_participant_is_skipped(db, tenant_ctx):
    meta = FakeMeta(
        [
            {
                "id": "t",
                "updated_time": _iso(timedelta(days=1)),
                "participants": {"data": [{"id": PAGE}]},
            }
        ],
        {},
    )
    result = await _run(db, tenant_ctx, meta)
    assert result.threads_seen == 0 and await _count(db, Message, tenant_ctx) == 0


async def test_an_album_stored_in_part_is_completed_without_duplicating_what_is_there(
    db, tenant_ctx
):
    """The outer filter skips a message whose first id is stored, so a half-written album (a
    crash, or a webhook that delivered only its first photo) is only completed by the per-part
    check. Without it the parts already stored would be written a second time."""
    atts = {
        "data": [
            {"id": "1", "mime_type": "image/jpeg", "file_url": "https://cdn/1.jpg"},
            {"id": "2", "mime_type": "image/jpeg", "file_url": "https://cdn/2.jpg"},
            {"id": "3", "mime_type": "image/jpeg", "file_url": "https://cdn/3.jpg"},
        ]
    }
    parsed = mb.message_parts(
        _msg("album", "psid-1", "look", timedelta(days=1), attachments=atts), page_id=PAGE
    )
    first_only = {**parsed, "parts": parsed["parts"][:1]}
    result = mb.BackfillResult()
    conversation = await mb._conversation_for_customer(
        db, tenant_ctx.tenant_id, "psid-1", "M", result
    )
    assert await mb.store_message(db, tenant_ctx.tenant_id, conversation, first_only) == 1

    assert await mb.store_message(db, tenant_ctx.tenant_id, conversation, parsed) == 2
    ids = sorted(
        (
            await db.execute(
                select(Message.channel_message_id).where(Message.tenant_id == tenant_ctx.tenant_id)
            )
        )
        .scalars()
        .all()
    )
    assert ids == ["album", "album#1", "album#2"]
    assert await mb.store_message(db, tenant_ctx.tenant_id, conversation, parsed) == 0


# ------------------------------------------------------------------ circuit breaker


async def test_repeated_meta_5xx_open_the_breaker_and_the_next_run_does_not_call_meta(
    db, tenant_ctx
):
    """A dead Meta must be left alone: after the breaker opens, a run ends without a request."""
    import app.core.circuit_breaker as cb

    cb.reset_breakers()
    calls = {"n": 0}

    def down(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, text="down")

    async with httpx.AsyncClient(transport=httpx.MockTransport(down)) as http:
        threshold = cb.get_breaker(cb.PROVIDER_MESSENGER)._failure_threshold
        for _ in range(threshold):
            r = await mb.run_page(
                db, tenant_ctx.tenant_id, page_id=PAGE, token="t", http=http, pause=0
            )
            assert r.stopped_reason.startswith("meta_5")
        before = calls["n"]
        blocked = await mb.run_page(
            db, tenant_ctx.tenant_id, page_id=PAGE, token="t", http=http, pause=0
        )
    cb.reset_breakers()
    assert blocked.stopped_reason == "provider_unavailable"
    assert calls["n"] == before, "an open breaker must not reach Meta"


async def test_a_deleted_message_does_not_count_against_the_breaker(db, tenant_ctx):
    """Meta answering "deleted" for an old message is normal, not an outage."""
    import app.core.circuit_breaker as cb

    cb.reset_breakers()
    meta = _simple_meta(deleted={"m1", "m2"})
    threshold = cb.get_breaker(cb.PROVIDER_MESSENGER)._failure_threshold
    for _ in range(threshold + 2):
        result = await _run(db, tenant_ctx, meta)
        assert result.stopped_reason is None
    cb.reset_breakers()
