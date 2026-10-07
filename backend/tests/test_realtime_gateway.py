"""8.3 close-out — the SSE gateway's FIRST dedicated test file.

The auth matrix (active member / deactivated / removed member / suspended
workspace / tenant-less token / stream-only query tokens) already lives in
tests/test_conversations_stream_auth.py and is NOT duplicated here. What was
missing — and what this file pins — is the DELIVERY half of the gateway:

1. cursor semantics (``_build_cursor``): absent cursor starts at ``$``; a
   fresh cursor is passed through UNCHANGED (the §149 no-skip fix); an old
   cursor is clamped to the retention floor so ``?cursor=0-0`` cannot replay
   retained history; a malformed cursor degrades to ``$``;
2. tenant isolation per FRAME, fail-closed: a mismatched tenant_id and an
   unparseable envelope are dropped, never delivered (§149);
3. real delivery over a fake Redis Streams backend — the right frames with
   the right ``id:`` fields, resume WITHOUT redelivery, and heartbeats on an
   idle stream (the mid-stream suspension re-check terminates the stream
   with a ``tenant_suspended`` error frame instead of hanging forever).
"""

from __future__ import annotations

import json
import time
import uuid

import pytest
from fakeredis import aioredis as fakeredis_aioredis

from app.core.events.schemas import build_envelope, serialize
from app.modules.realtime import router as realtime

# ------------------------------------------------------------- helpers ------


class _FakeRequest:
    """Yields False for the first N polls, then True forever."""

    def __init__(self, live_polls: int) -> None:
        self._live = live_polls

    async def is_disconnected(self) -> bool:
        if self._live > 0:
            self._live -= 1
            return False
        return True


def _bus_fields(tenant_id: uuid.UUID) -> dict[str, str]:
    """A REAL registered event envelope, serialized to the bus field layout."""
    envelope = build_envelope(
        event_type="customer.merged",
        tenant_id=tenant_id,
        aggregate_type="customer",
        aggregate_id=uuid.uuid4(),
        payload={"note": "gateway-test"},
    )
    return serialize(envelope)


def _next_id(offset_ms: int) -> str:
    return f"{int(time.time() * 1000) + offset_ms}-0"


async def _collect(gen, *, max_chunks: int = 60):
    frames: list[bytes] = []
    heartbeats = 0
    for _ in range(max_chunks):
        try:
            chunk = await gen.__anext__()
        except (StopAsyncIteration, asyncio.CancelledError):
            break
        if chunk.startswith(b":"):
            heartbeats += 1
            continue
        frames.append(chunk)
    return frames, heartbeats


# ------------------------------------------- 1. cursor semantics (pure) ------

import asyncio  # noqa: E402  (used by _collect above)


async def test_an_absent_cursor_starts_at_now() -> None:
    assert await realtime._build_cursor(None, ["a", "b"]) == {
        "a": "$",
        "b": "$",
    }


async def test_a_fresh_cursor_passes_through_unchanged() -> None:
    # The §149 fix: bumping the sequence here skipped the very next entry in
    # a burst — the client cursor IS the last id seen and must be consumed
    # exclusively as-is.
    fresh = _next_id(5_000)
    assert await realtime._build_cursor(fresh, ["message.events"]) == {"message.events": fresh}


async def test_an_old_cursor_is_clamped_to_the_retention_floor() -> None:
    result = await realtime._build_cursor("0-0", ["message.events"])
    ms = int(result["message.events"].split("-", 1)[0])
    floor = int(time.time() * 1000) - realtime._CURSOR_CLAMP_MS
    assert abs(ms - floor) < 5_000, "0-0 must clamp to now-60s, not replay history"


async def test_a_malformed_cursor_degrades_to_now() -> None:
    assert await realtime._build_cursor("not-a-cursor", ["s"]) == {"s": "$"}


# --------------------------------- 2. frame encoding (pure) ------------------


def test_a_frame_carries_its_event_id_and_json_payload() -> None:
    raw = realtime._sse_frame({"stream": "s", "id": "1-0"}, event_id="1-0")
    assert raw.startswith(b"id: 1-0\ndata: ")
    body = json.loads(raw.split(b"data: ", 1)[1].strip())
    assert body == {"stream": "s", "id": "1-0"}


# ---------------------- 3. delivery, isolation, resume (fakeredis) ----------


@pytest.fixture()
def fake_redis(monkeypatch):
    client = fakeredis_aioredis.FakeRedis(decode_responses=False)

    def _factory():
        # The router stores the client WITHOUT awaiting: get_redis() is sync.
        return client

    monkeypatch.setattr(realtime, "get_redis", _factory)
    monkeypatch.setattr(realtime, "_BLOCK_MS", 50)
    monkeypatch.setattr(realtime, "_HEARTBEAT_INTERVAL_S", 0.05)

    # The lifecycle re-check hits the real DB; the suspension frame is its
    # own dedicated test below — the delivery tests pin it open.
    async def _open(tenant_id: str) -> bool:
        return True

    monkeypatch.setattr(realtime, "_tenant_may_stream", _open)
    return client


async def test_only_the_owning_tenants_events_are_delivered(fake_redis) -> None:
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    stream = "message.events"
    id_a = await fake_redis.xadd(stream, _bus_fields(tenant_a), id=_next_id(1_000))
    await fake_redis.xadd(stream, _bus_fields(tenant_b), id=_next_id(2_000))
    # An unparseable frame: the gateway drops it fail-closed, never delivers.
    await fake_redis.xadd(stream, {"payload": b"not-json", "meta": b"{}"}, id=_next_id(3_000))

    gen = realtime._event_stream(
        tenant_id=str(tenant_a),
        user_id=str(uuid.uuid4()),
        streams=[stream],
        cursor="0-1",
        request=_FakeRequest(live_polls=3),
    )
    frames, _ = await _collect(gen)

    assert len(frames) == 1, frames
    body = json.loads(frames[0].split(b"data: ", 1)[1].strip())
    assert body["payload"] == {"note": "gateway-test"}
    assert body["id"] == (id_a.decode() if isinstance(id_a, bytes) else id_a)


async def test_resume_from_the_last_id_never_redelivers(fake_redis) -> None:
    tenant = uuid.uuid4()
    stream = "message.events"
    first, second = _next_id(1_000), _next_id(2_000)
    await fake_redis.xadd(stream, _bus_fields(tenant), id=first)
    await fake_redis.xadd(stream, _bus_fields(tenant), id=second)

    gen = realtime._event_stream(
        tenant_id=str(tenant),
        user_id=str(uuid.uuid4()),
        streams=[stream],
        cursor="0-1",
        request=_FakeRequest(live_polls=3),
    )
    frames, _ = await _collect(gen)
    delivered = [json.loads(f.split(b"data: ", 1)[1].strip())["id"] for f in frames]
    assert delivered == [first, second]

    # Reconnect with the cursor of the LAST frame: nothing may be replayed.
    gen2 = realtime._event_stream(
        tenant_id=str(tenant),
        user_id=str(uuid.uuid4()),
        streams=[stream],
        cursor=delivered[-1],
        request=_FakeRequest(live_polls=2),
    )
    frames2, _ = await _collect(gen2)
    assert frames2 == [], "a resumed stream must start AFTER the cursor"


async def test_an_idle_stream_sends_heartbeats(fake_redis) -> None:
    gen = realtime._event_stream(
        tenant_id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()),
        streams=["message.events"],
        cursor=None,
        request=_FakeRequest(live_polls=12),
    )
    frames, heartbeats = await _collect(gen, max_chunks=30)
    assert frames == [], "an idle stream carries no data frames"
    assert heartbeats >= 1, "the keep-alive heartbeat must fire on idle streams"


async def test_a_suspended_workspace_ends_the_stream_with_a_reason(fake_redis, monkeypatch) -> None:
    async def _closed(tenant_id: str) -> bool:
        return False

    monkeypatch.setattr(realtime, "_tenant_may_stream", _closed)
    gen = realtime._event_stream(
        tenant_id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()),
        streams=["message.events"],
        cursor=None,
        request=_FakeRequest(live_polls=12),
    )
    frames, _ = await _collect(gen, max_chunks=30)
    assert frames, "the suspension must TELL the client why, not just close"
    body = json.loads(frames[-1].split(b"data: ", 1)[1].strip())
    assert body["error"]["code"] == "tenant_suspended"
