"""§176 gate scenario 13 — Redis outage, then replay (§21, §128, §163).

The architecture's promise is that Redis is TRANSPORT, not truth:

    Redis failure != data loss.  Pending events stay in the outbox until Redis is
    back, then the relay republishes them.

The existing tests for the relay only cover the field mapping of `event_log`;
none ran the drain loop against a real database. These do, with a bus whose
availability the test controls, so the outage is an actual failing `publish()`
rather than a mock of the relay's internals.

Sessions: `OutboxRelay` imports `SessionLocal` by name at module load, so it is
patched on the `outbox` module itself (patching `get_sessionmaker` would not
reach it). The relay then runs on the test's rolled-back connection.

DB-backed: needs PostgreSQL as the `sales_app` role; skips via `db_url`
otherwise.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.events.outbox import OutboxRelay
from app.core.events.writer import add_outbox_event

pytestmark = [pytest.mark.gate]

BATCH = 100
MAX_ATTEMPTS = 5


class SwitchableBus:
    """An EventBus whose `publish` fails while `up` is False (a Redis outage)."""

    def __init__(self) -> None:
        self.up = True
        self.published: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    async def publish(
        self, stream: str, payload: dict[str, Any], meta: dict[str, Any] | None = None
    ) -> str:
        if not self.up:
            raise ConnectionError("Error 111 connecting to redis:6379. Connection refused.")
        self.published.append((stream, payload, meta or {}))
        return f"{len(self.published)}-0"

    def outbox_ids(self) -> list[str]:
        return [meta["outbox_id"] for _, _, meta in self.published]


@pytest.fixture
async def relay_on_test_connection(monkeypatch, db):
    """Run the relay's own sessions on the test's connection (and its rollback)."""
    conn = await db.connection()
    factory = async_sessionmaker(
        bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    monkeypatch.setattr("app.core.events.outbox.SessionLocal", factory)
    return factory


async def _stage(db, tenant_id: uuid.UUID, count: int) -> list[str]:
    ids: list[str] = []
    for n in range(count):
        event = await add_outbox_event(
            db,
            aggregate_type="order",
            aggregate_id=uuid.uuid4(),
            event_type="order.created",
            tenant_id=tenant_id,
            payload={"n": n},
        )
        ids.append(str(event.id))
    # `add_outbox_event` stamps `outbox_id` into meta AFTER its own flush and
    # leaves the commit (hence the final flush) to the caller. The relay reads
    # through raw SQL on another session, which never sees a dirty ORM object —
    # so flush explicitly, exactly as a real caller's commit would.
    await db.flush()
    return ids


async def _rows(db, ids: list[str]) -> dict[str, dict[str, Any]]:
    result = await db.execute(
        text(
            "SELECT id::text AS id, status, attempts, last_error FROM outbox_events "
            "WHERE id = ANY(CAST(:ids AS uuid[]))"
        ),
        {"ids": ids},
    )
    return {r.id: {"status": r.status, "attempts": r.attempts, "error": r.last_error}
            for r in result}


async def _event_log_count(db, ids: list[str]) -> int:
    return (
        await db.execute(
            text("SELECT count(*) FROM event_log WHERE event_id = ANY(CAST(:ids AS uuid[]))"),
            {"ids": ids},
        )
    ).scalar_one()


async def _age(db, ids: list[str], minutes: int) -> None:
    """Make rows look `minutes` old, as if the outage had lasted that long.

    `now()` is the TRANSACTION time in Postgres, so a row created in this test
    cannot age by itself — the clock is moved by rewriting its timestamps. P-02
    moved the failed-row cool-down onto the durable `not_before` schedule, so
    this ages BOTH the staging clock (`created_at`, still used by the
    publishing-strand reclaim and the `not_before IS NULL` legacy floor) and the
    earned schedule (`not_before`) — pushing a row's `not_before` into the past
    is exactly what the passage of `minutes` of real outage time would do.
    """
    await db.execute(
        text(
            "UPDATE outbox_events "
            "   SET created_at = now() - make_interval(mins => :m), "
            "       not_before = CASE WHEN not_before IS NULL THEN NULL "
            "                          ELSE now() - make_interval(mins => :m) END "
            " WHERE id = ANY(CAST(:ids AS uuid[]))"
        ),
        {"m": minutes, "ids": ids},
    )


async def test_gate_redis_outage_loses_nothing_and_replays_once(
    db, tenant_ctx, relay_on_test_connection
):
    bus = SwitchableBus()
    relay = OutboxRelay(bus)
    ids = await _stage(db, tenant_ctx.tenant_id, count=3)

    # --- Redis is DOWN: the relay drains, publishes nothing, and does not crash. ---
    bus.up = False
    published = await relay._drain_once(batch=BATCH, max_attempts=MAX_ATTEMPTS)
    assert published == 0
    assert [i for i in bus.outbox_ids() if i in ids] == []

    rows = await _rows(db, ids)
    assert set(rows) == set(ids), "an outbox row was lost during the outage"
    assert {r["status"] for r in rows.values()} == {"failed"}
    assert all("Connection refused" in (r["error"] or "") for r in rows.values())
    # Nothing was written to the replay history for events that never went out.
    assert await _event_log_count(db, ids) == 0

    # --- Redis comes BACK after a long outage (cool-down elapsed). ---
    bus.up = True
    await _age(db, ids, minutes=6)
    published = await relay._drain_once(batch=BATCH, max_attempts=MAX_ATTEMPTS)
    assert published >= 3

    mine = [i for i in bus.outbox_ids() if i in ids]
    assert sorted(mine) == sorted(ids), "every staged event must be republished"
    assert len(mine) == len(set(mine)), f"an event was published twice: {mine}"

    rows = await _rows(db, ids)
    assert {r["status"] for r in rows.values()} == {"published"}
    # The durable replay history (§152) now has each event exactly once.
    assert await _event_log_count(db, ids) == 3

    # --- A further drain must be a no-op: no duplicate publication. ---
    before = len([i for i in bus.outbox_ids() if i in ids])
    await relay._drain_once(batch=BATCH, max_attempts=MAX_ATTEMPTS)
    assert len([i for i in bus.outbox_ids() if i in ids]) == before


async def test_gate_relay_crash_between_claim_and_publish_is_reclaimed(
    db, tenant_ctx, relay_on_test_connection
):
    """§128: a row stranded in 'publishing' by a dead relay is re-queued and sent."""
    bus = SwitchableBus()
    relay = OutboxRelay(bus)
    [event_id] = await _stage(db, tenant_ctx.tenant_id, count=1)

    # The relay claimed the row, then died before it could publish or mark it.
    await db.execute(
        text("UPDATE outbox_events SET status = 'publishing', attempts = 1 WHERE id = :i"),
        {"i": event_id},
    )
    await _age(db, [event_id], minutes=6)

    await relay._drain_once(batch=BATCH, max_attempts=MAX_ATTEMPTS)

    assert [i for i in bus.outbox_ids() if i == event_id] == [event_id]
    assert (await _rows(db, [event_id]))[event_id]["status"] == "published"


async def test_gate_recent_publishing_row_is_not_stolen(
    db, tenant_ctx, relay_on_test_connection
):
    """The reclaim must not race a LIVE relay: a fresh 'publishing' row is left alone."""
    bus = SwitchableBus()
    relay = OutboxRelay(bus)
    [event_id] = await _stage(db, tenant_ctx.tenant_id, count=1)

    await db.execute(
        text("UPDATE outbox_events SET status = 'publishing', attempts = 1 WHERE id = :i"),
        {"i": event_id},
    )
    await _age(db, [event_id], minutes=1)  # well inside the 5-minute lease

    await relay._drain_once(batch=BATCH, max_attempts=MAX_ATTEMPTS)

    assert [i for i in bus.outbox_ids() if i == event_id] == []
    assert (await _rows(db, [event_id]))[event_id]["status"] == "publishing"


async def test_gate_replayed_event_keeps_the_same_dedupe_key(
    db, tenant_ctx, relay_on_test_connection
):
    """At-least-once delivery is only safe because the consumer's dedupe key is
    stable. The key is the OUTBOX row id, so a reclaimed-and-republished event
    must present the same `outbox_id` both times (§127)."""
    bus = SwitchableBus()
    relay = OutboxRelay(bus)
    [event_id] = await _stage(db, tenant_ctx.tenant_id, count=1)

    # First attempt fails, second succeeds after the cool-down.
    bus.up = False
    await relay._drain_once(batch=BATCH, max_attempts=MAX_ATTEMPTS)
    bus.up = True
    await _age(db, [event_id], minutes=6)
    await relay._drain_once(batch=BATCH, max_attempts=MAX_ATTEMPTS)

    sent = [meta for _, _, meta in bus.published if meta.get("outbox_id") == event_id]
    assert len(sent) == 1
    assert sent[0]["outbox_id"] == event_id


async def _failed_schedule(db, event_id: str):
    """Return a failed row's (status, not_before, attempts) as Postgres sees them."""
    row = (
        await db.execute(
            text(
                "SELECT status, not_before, attempts FROM outbox_events WHERE id = :i"
            ),
            {"i": event_id},
        )
    ).first()
    return row


async def test_gate_a_failed_row_is_not_hammered_once_per_drain(
    db, tenant_ctx, relay_on_test_connection
):
    """P-02 hot-loop guard, on real rows: a down bus is retried on its cool-down.

    The defect: ``_MARK_FAILED_SQL`` stamped no ``not_before`` and
    ``_RECLAIM_FAILED_SQL`` woke on the immutable ``created_at``, so once a row
    was older than the re-queue bound the relay re-claimed and republished the
    SAME poisoned row every drain against a bus that was still down. After the
    fix the failure stamps a durable schedule, so a second drain that does NOT
    advance the clock must leave the row untouched — one publish attempt per
    cool-down, not one per poll. This is the behaviour that CI proves; the
    DB-free file pins the statements that make it true.
    """
    bus = SwitchableBus()
    relay = OutboxRelay(bus)
    [event_id] = await _stage(db, tenant_ctx.tenant_id, count=1)

    # --- Bus is DOWN: the row is attempted once and comes back 'failed' with a
    # FUTURE not_before (the durable cool-down). ---
    bus.up = False
    await relay._drain_once(batch=BATCH, max_attempts=MAX_ATTEMPTS)

    status, not_before, attempts = await _failed_schedule(db, event_id)
    assert status == "failed"
    assert not_before is not None, "a failed row earned no durable cool-down schedule"
    # now() is transaction time; the schedule must sit in the future so the next
    # drain cannot claim it. Compare against Postgres's own clock.
    is_future = (
        await db.execute(
            text("SELECT :nb::timestamptz > now()"), {"nb": not_before}
        )
    ).scalar_one()
    assert is_future, f"failed row's not_before is not in the future: {not_before}"
    assert attempts == 1

    # --- Drain AGAIN, without aging anything: the bus is STILL down and the
    # cool-down has NOT elapsed, so the row must not be touched at all. ---
    first_publishes = len([i for i in bus.outbox_ids() if i == event_id])
    await relay._drain_once(batch=BATCH, max_attempts=MAX_ATTEMPTS)
    second_publishes = len([i for i in bus.outbox_ids() if i == event_id])

    assert first_publishes == 0 and second_publishes == 0, (
        "the relay published during a down bus"
    )
    status2, _, _ = await _failed_schedule(db, event_id)
    assert status2 == "failed", (
        "a not-yet-due failed row was re-queued before its cool-down elapsed — "
        "the P-02 hot loop is back"
    )
