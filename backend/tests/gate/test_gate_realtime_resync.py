"""§176 gate scenario 21 — realtime reconnect and resync, FOR REAL (§149).

The gate that stood here before this file asserted only that the realtime
router *has a route whose path contains "stream"/"events"*. It could not fail:
a router exposing a plain JSON list endpoint satisfies it. Nothing drove the
SSE generator, so none of §149's actual promises were proven:

    Reconnect -> re-authenticate -> re-check tenant/role
    -> resume from cursor where possible
    -> otherwise resync authoritative state

These tests drive the real generator (`_event_stream`) against a real
Redis-Streams server — `fakeredis`, an in-process implementation of the Redis
protocol spoken by redis-py — through the real producer
(`RedisStreamsBus.publish` carrying the §19 envelope wire format the outbox
relay writes). The cursor a client receives is then fed into a SECOND,
independent connection, which is exactly what the browser does after a dropped
stream. Redis itself is never stubbed here; what is under test is the gateway's
resume / isolation / clamp behaviour, and it runs end to end.

No PostgreSQL needed: this file runs locally and in CI.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import fakeredis.aioredis
import pytest

from app.core.events.bus import RedisStreamsBus
from app.core.events.schemas import build_envelope, serialize
from app.modules.realtime import router as rt

pytestmark = [pytest.mark.gate]

STREAM = "order.events"


@pytest.fixture(autouse=True)
def _short_polls(monkeypatch):
    """Idle XREADs block 5 s by default; shrink it so an empty poll is cheap.

    Transport timing only — nothing in the resume/isolation logic is changed.
    """
    monkeypatch.setattr(rt, "_BLOCK_MS", 50)


class _NeverDisconnected:
    """Request stub: the client stays connected until the test stops pulling."""

    async def is_disconnected(self) -> bool:
        return False


class _StopsAfter:
    """Request stub that reports a client disconnect after `polls` polls."""

    def __init__(self, polls: int) -> None:
        self._remaining = polls

    async def is_disconnected(self) -> bool:
        if self._remaining <= 0:
            return True
        self._remaining -= 1
        return False


@pytest.fixture
async def fake_redis():
    client = fakeredis.aioredis.FakeRedis(decode_responses=False)
    yield client
    await client.flushall()
    await client.aclose()


@pytest.fixture
def gateway_on(monkeypatch, fake_redis):
    """Point the gateway's `get_redis` at the test server.

    This is the transport seam — the same client the app builds from
    `redis_url` — not the rule under test: the generator's cursor handling,
    envelope decoding and tenant filtering all still execute for real.
    """
    monkeypatch.setattr(rt, "get_redis", lambda: fake_redis)
    return fake_redis


async def _publish(client, *, tenant_id: uuid.UUID, order_ref: str) -> str:
    """Publish one event the way the outbox relay does; return the stream id."""
    envelope = build_envelope(
        "order.created",
        tenant_id=tenant_id,
        aggregate_type="order",
        aggregate_id=uuid.uuid4(),
        payload={"order_ref": order_ref, "total": "150.00"},
    )
    wire = serialize(envelope)
    bus = RedisStreamsBus(client)
    return await bus.publish(STREAM, json.loads(wire["payload"]), json.loads(wire["meta"]))


async def _publish_at(client, entry_id: str, *, tenant_id: uuid.UUID, order_ref: str) -> str:
    """Publish with an EXPLICIT stream id.

    Redis hands out `<epoch-ms>-<seq>`, so two events in the same millisecond
    differ only in the sequence. Timing them naturally would make the test
    flaky; pinning the ids makes the collision deterministic.
    """
    envelope = build_envelope(
        "order.created",
        tenant_id=tenant_id,
        aggregate_type="order",
        aggregate_id=uuid.uuid4(),
        payload={"order_ref": order_ref, "total": "150.00"},
    )
    wire = serialize(envelope)
    await client.xadd(
        STREAM,
        {
            "id": str(uuid.uuid4()),
            "ts": str(time.time()),
            "payload": wire["payload"],
            "meta": wire["meta"],
        },
        id=entry_id,
    )
    return entry_id


def _decode(frame: bytes) -> dict[str, Any]:
    data_line = next(line for line in frame.decode().split("\n") if line.startswith("data:"))
    return json.loads(data_line[len("data:") :].strip())


async def _collect(
    tenant_id: uuid.UUID,
    *,
    cursor: str | None,
    stop_after: int | None = None,
    polls: int = 2,
    streams: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Run one SSE 'connection' and return the decoded frames it emitted."""
    frames: list[dict[str, Any]] = []
    agen = rt._event_stream(
        tenant_id=str(tenant_id),
        user_id="u-1",
        streams=streams or [STREAM],
        cursor=cursor,
        request=_StopsAfter(polls) if stop_after is None else _NeverDisconnected(),
    )
    try:
        async for raw in agen:
            if raw.startswith(b":"):  # heartbeat comment, not a data frame
                continue
            frames.append(_decode(raw))
            if stop_after is not None and len(frames) >= stop_after:
                break
    finally:
        await agen.aclose()
    return frames


async def test_gate_reconnect_from_the_last_frame_resumes_without_gap_or_repeat(
    gateway_on,
) -> None:
    """§149: resume from cursor — the client must see 4,5 and never 1,2,3 again."""
    tenant = uuid.uuid4()
    refs = [f"ORD-{n}" for n in range(1, 6)]
    for ref in refs:
        await _publish(gateway_on, tenant_id=tenant, order_ref=ref)

    first_connection = await _collect(tenant, cursor="0-0", stop_after=3)
    assert [f["payload"]["order_ref"] for f in first_connection] == refs[:3]
    last_id = first_connection[-1]["id"]

    second_connection = await _collect(tenant, cursor=last_id)
    assert [f["payload"]["order_ref"] for f in second_connection] == refs[3:], (
        f"the reconnect lost or repeated events: cursor={last_id} "
        f"got={[(f['id'], f['payload']['order_ref']) for f in second_connection]}"
    )
    # The ids keep advancing monotonically across the reconnect.
    assert second_connection[0]["id"] > last_id


async def test_gate_two_events_in_one_millisecond_both_survive_the_reconnect(
    gateway_on,
) -> None:
    """§149 deterministically: a burst in one millisecond must not eat an event.

    The client's cursor is the LAST id it received, and Redis XREAD is already
    exclusive of the id it is given — so resuming has to ask for that exact id.
    Bumping the sequence too loses the next entry whenever it shares the
    millisecond with the cursor, which is the normal shape of a burst (several
    order events in the same ms). Silent loss, on every reconnect.
    """
    tenant = uuid.uuid4()
    ms = int(time.time() * 1000)
    await _publish_at(gateway_on, f"{ms}-0", tenant_id=tenant, order_ref="A")
    await _publish_at(gateway_on, f"{ms}-1", tenant_id=tenant, order_ref="B")
    await _publish_at(gateway_on, f"{ms}-2", tenant_id=tenant, order_ref="C")

    first = await _collect(tenant, cursor=f"{ms}-0")
    assert [f["payload"]["order_ref"] for f in first] == ["B", "C"], (
        f"resuming from {ms}-0 lost an event in the same millisecond"
    )

    resumed_from_b = await _collect(tenant, cursor=f"{ms}-1")
    assert [f["payload"]["order_ref"] for f in resumed_from_b] == ["C"]


async def test_gate_a_cursor_of_zero_never_replays_the_retained_stream(
    gateway_on,
) -> None:
    """C1: `?cursor=0-0` must not hand a client the whole retained stream.

    Stream ids carry epoch milliseconds, so an ancient cursor is pulled up to
    the clamp floor. A frame older than the floor is unreachable even though it
    is still physically in Redis — otherwise one leaked token replays every
    tenant's history.
    """
    ancient = "1000-0"  # 1970 — long before any real event
    await gateway_on.xadd(
        STREAM,
        {
            "id": "forged",
            "payload": json.dumps({"event_type": "order.created", "order_ref": "ANCIENT"}),
            "meta": json.dumps({"type": "order.created"}),
        },
        id=ancient,
    )
    tenant = uuid.uuid4()
    await _publish(gateway_on, tenant_id=tenant, order_ref="RECENT")

    frames = await _collect(tenant, cursor="0-0")

    assert all(f["id"] != ancient for f in frames), "clamped cursor replayed history"
    assert [f["payload"]["order_ref"] for f in frames] == ["RECENT"]


async def test_gate_an_ancient_cursor_is_clamped_on_the_server_clock(
    gateway_on,
) -> None:
    """The clamp floor comes from wall-clock ms, never from the client's claim."""
    floor_ms = int(time.time() * 1000) - rt._CURSOR_CLAMP_MS
    start = (await rt._build_cursor("1-0", [STREAM]))[STREAM]
    ms, _seq = start.rsplit("-", 1)
    assert int(ms) >= floor_ms, f"cursor not clamped: {start} < {floor_ms}-0"

    # A cursor inside the window is passed through UNCHANGED: XREAD is already
    # exclusive of the id it is given, so bumping it would skip an entry.
    recent_ms = int(time.time() * 1000)
    assert (await rt._build_cursor(f"{recent_ms}-3", [STREAM]))[STREAM] == (f"{recent_ms}-3")
    # No cursor at all -> "now" only; a fresh client never gets a backlog.
    assert (await rt._build_cursor(None, [STREAM]))[STREAM] == "$"


async def test_gate_a_reconnect_never_delivers_another_tenants_event(
    gateway_on,
) -> None:
    """Isolation survives the reconnect: foreign frames are dropped while the
    read position still advances past them."""
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    await _publish(gateway_on, tenant_id=theirs, order_ref="THEIRS-1")
    await _publish(gateway_on, tenant_id=mine, order_ref="MINE-1")
    await _publish(gateway_on, tenant_id=theirs, order_ref="THEIRS-2")
    await _publish(gateway_on, tenant_id=mine, order_ref="MINE-2")

    first = await _collect(mine, cursor="0-0", stop_after=1)
    assert [f["payload"]["order_ref"] for f in first] == ["MINE-1"]

    resumed = await _collect(mine, cursor=first[-1]["id"])
    assert [f["payload"]["order_ref"] for f in resumed] == ["MINE-2"]
    assert all("THEIRS" not in f["payload"]["order_ref"] for f in first + resumed)


async def test_gate_a_frame_without_a_valid_envelope_is_dropped_not_streamed(
    gateway_on,
) -> None:
    """Fail CLOSED on the wire: a partial or hand-made frame never reaches a
    client, and it does not kill the stream for the events behind it."""
    tenant = uuid.uuid4()
    await gateway_on.xadd(
        STREAM,
        {
            "id": "x",
            "payload": json.dumps({"event_type": "order.created"}),
            "meta": "{}",
        },
    )
    await gateway_on.xadd(STREAM, {"id": "y", "payload": "not-json", "meta": "{}"})
    await _publish(gateway_on, tenant_id=tenant, order_ref="OK")

    frames = await _collect(tenant, cursor="0-0")
    assert [f["payload"]["order_ref"] for f in frames] == ["OK"]


async def test_gate_a_suspended_workspace_has_its_stream_closed(monkeypatch, fake_redis) -> None:
    """§149/§48: revalidation is not connect-time only.

    A stream outlives the request that opened it, so the workspace state is
    re-read on the heartbeat; when it no longer may use the API the generator
    must END without streaming the pending frame. The heartbeat is forced due by
    shrinking the interval, and the entry is already in the stream, so a stream
    that failed to close WOULD emit it — the test can genuinely fail.
    """
    monkeypatch.setattr(rt, "get_redis", lambda: fake_redis)
    monkeypatch.setattr(rt, "_HEARTBEAT_INTERVAL_S", -1.0)
    tenant = uuid.uuid4()
    await _publish(fake_redis, tenant_id=tenant, order_ref="MUST-NOT-STREAM")

    checked: list[str] = []

    async def deny(tenant_id: str) -> bool:
        checked.append(tenant_id)
        return False

    monkeypatch.setattr(rt, "_tenant_may_stream", deny)

    frames = [
        raw
        async for raw in rt._event_stream(
            tenant_id=str(tenant),
            user_id="u-1",
            streams=[STREAM],
            cursor="0-0",
            request=_NeverDisconnected(),
        )
    ]

    assert checked == [str(tenant)], "the mid-stream re-check never ran"
    data_frames = [f for f in frames if not f.startswith(b":")]
    # The suspended tenant's EVENT must never stream — but the close now
    # carries ONE reason frame (tenant_suspended, via the error envelope) so
    # the client does not mistake the refusal for a network drop and
    # reconnect into it forever.
    assert all(b"MUST-NOT-STREAM" not in f for f in data_frames), (
        "a suspended workspace kept receiving its events"
    )
    assert any(b"tenant_suspended" in f for f in data_frames), (
        "the close carries no reason — the client would treat it as a drop"
    )
