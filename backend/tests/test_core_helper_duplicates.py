"""Regression guards for two contract findings in ``docs/CONTRACT_AUDIT.md``.

(a) Finding 5 — ``app/core/db.get_session`` was a SECOND request-session
    dependency. It had zero callers in ``app/`` and, unlike
    ``identity/deps.get_db``, was not the session the tenant-binding chain uses:
    ``get_tenant_ctx`` depends on ``DbSession`` (``Depends(get_db)``) and binds
    the RLS tenant GUC onto *that* session. A route that adopted ``get_session``
    would therefore get a different, unbound session — RLS silently stops
    applying. A duplicate that is subtly wrong is worse than one that is merely
    redundant, so it is deleted. ``test_get_session_landmine_is_deleted`` fails
    if anyone reintroduces a parallel session dependency.

(b) Finding 2 — ``app/workers/inspector.list_dlq`` hand-parsed the §19 envelope
    (``payload`` / ``meta``), re-deriving the field names. It now reads through
    ``schemas.deserialize()``, so the contract is exercised on the read path and
    the item's ``id`` is the ENVELOPE id rather than the per-XADD bus uuid the
    hand-parser returned. Production ``outbox_events`` predates the envelope, so
    the legacy tolerance is preserved: a row with no routing keys (or malformed
    JSON) is still listed instead of crashing the DLQ inspector.

DB-free: the Redis client is a fake and no session is opened, so this runs both
locally and in CI.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from app.core.events.schemas import build_envelope, serialize
from app.workers.inspector import list_dlq

# ---------------------------------------------------------------------------
# (a) the duplicate session dependency
# ---------------------------------------------------------------------------


def test_get_session_landmine_is_deleted() -> None:
    """There is exactly one session dependency, and it is the tenant-bound one.

    ``get_session`` (``app/core/db.py``) duplicated ``identity/deps.get_db`` but
    was NOT the callable ``get_tenant_ctx`` binds the RLS GUC onto. Adopting it
    would hand a route a second, unbound session — the exact silent isolation
    failure golden rule 4 exists to prevent. Zero callers, so it is deleted;
    this assertion is the tripwire that keeps it deleted.
    """
    from app.core import db

    assert not hasattr(db, "get_session"), (
        "app.core.db.get_session was deleted (CONTRACT_AUDIT finding 5): a "
        "second session dependency that skips the tenant-binding chain. Use "
        "identity.deps.DbSession / get_db instead of re-adding it."
    )


async def test_get_db_opens_one_transaction_around_the_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The surviving dependency wraps the yielded session in ONE transaction.

    That transaction is what makes ``bind_tenant``'s
    ``set_config(..., is_local := true)`` (the ``app.tenant_id`` GUC)
    transaction-scoped. ``get_session`` did not do this, which is why keeping it
    as a "duplicate" was a landmine rather than harmless redundancy.
    """
    from app.modules.identity import deps

    events: list[str] = []

    class _Transaction:
        async def __aenter__(self) -> _Transaction:
            events.append("begin")
            return self

        async def __aexit__(self, *exc: Any) -> bool:
            events.append("commit")
            return False

    class _FakeSession:
        async def __aenter__(self) -> _FakeSession:
            events.append("enter")
            return self

        async def __aexit__(self, *exc: Any) -> bool:
            events.append("exit")
            return False

        def begin(self) -> _Transaction:
            return _Transaction()

    # get_db resolves the factory through app.core.db.get_sessionmaker PER
    # CALL (not an import-time binding) — that per-call resolution is what
    # lets conftest bind the app's sessions to a test transaction, so this
    # guard patches the same seam the binding does.
    monkeypatch.setattr("app.core.db.get_sessionmaker", lambda: lambda: _FakeSession())

    dependency = deps.get_db()
    session = await dependency.__anext__()
    assert session is not None
    # the transaction is open for the whole time the caller holds the session
    assert events == ["enter", "begin"]

    with pytest.raises(StopAsyncIteration):
        await dependency.__anext__()
    assert events == ["enter", "begin", "commit", "exit"]


# ---------------------------------------------------------------------------
# (b) the DLQ inspector reads the envelope through deserialize()
# ---------------------------------------------------------------------------


class _FakeRedis:
    """Just enough of ``redis.asyncio.Redis`` for ``list_dlq``'s XRANGE."""

    def __init__(self, entries: list[tuple[str, dict[str, Any]]]) -> None:
        self._entries = entries

    async def xrange(self, stream: str, **kwargs: Any) -> list[tuple[str, dict[str, Any]]]:
        return self._entries


def _dlq_fields(envelope_fields: dict[str, str], **extra_meta: Any) -> dict[str, Any]:
    """Build the Redis Streams field map ``send_to_dlq`` writes for an envelope.

    ``RedisStreamsBus.send_to_dlq`` re-publishes the consumed event's
    ``payload`` / ``meta`` (the serialized envelope) plus the DLQ provenance,
    under a FRESH per-XADD bus ``id`` — which is exactly why the hand-parser's
    ``fields["id"]`` was not the envelope id.
    """
    meta = {**json.loads(envelope_fields["meta"]), **extra_meta}
    return {
        "id": str(uuid.uuid4()),
        "ts": "1715000000.0",
        "payload": envelope_fields["payload"],
        "meta": json.dumps(meta),
    }


async def test_list_dlq_round_trips_a_real_envelope() -> None:
    """A real published event is rebuilt through ``deserialize()`` in list_dlq."""
    tenant_id = uuid.uuid4()
    aggregate_id = uuid.uuid4()
    envelope = build_envelope(
        "order.created",
        tenant_id=tenant_id,
        aggregate_type="order",
        aggregate_id=aggregate_id,
        payload={"order_id": str(aggregate_id), "grand_total": Decimal("76.50")},
        meta={"attempts": 3},
    )
    fields = _dlq_fields(serialize(envelope), dlq_reason="boom", source_stream="order.events")
    # the per-XADD bus uuid is deliberately NOT the envelope id
    bus_id = fields["id"]
    assert bus_id != envelope.id

    client = _FakeRedis([("1715000000000-0", fields)])

    items = await list_dlq(client, "order.events.dlq")

    assert len(items) == 1
    item = items[0]
    assert item["entry_id"] == "1715000000000-0"
    assert item["envelope"] is True
    # the ENVELOPE id, not the bus uuid the hand-parser returned
    assert item["id"] == envelope.id
    assert item["id"] != bus_id
    assert item["type"] == "order.created"
    assert item["tenant_id"] == str(tenant_id)
    assert item["aggregate_type"] == "order"
    assert item["aggregate_id"] == str(aggregate_id)
    assert item["occurred_at"] == envelope.occurred_at.isoformat()
    # going through the contract preserves Python types: money stays Decimal
    assert isinstance(item["payload"]["grand_total"], Decimal)
    assert item["payload"]["grand_total"] == Decimal("76.50")
    # DLQ provenance is user meta (not a routing key), so it survives
    assert item["meta"]["dlq_reason"] == "boom"
    assert item["meta"]["source_stream"] == "order.events"
    assert item["meta"]["attempts"] == 3


async def test_list_dlq_tolerates_a_legacy_row_without_an_envelope() -> None:
    """A row written before the envelope existed is listed, not crashed.

    Production ``outbox_events`` predates the writer fix, so a dead entry can
    carry a payload/meta with no envelope routing keys at all. The inspector
    must still show exactly what is stuck.
    """
    legacy = {
        "id": "legacy-row-1",
        "ts": "1714000000.0",
        "payload": json.dumps({"order_id": "o-1"}),
        "meta": json.dumps({"attempts": 2}),
    }
    client = _FakeRedis([("1714000000000-0", legacy)])

    items = await list_dlq(client, "order.events.dlq")

    assert len(items) == 1
    item = items[0]
    assert item["envelope"] is False
    assert item["entry_id"] == "1714000000000-0"
    assert item["id"] == "legacy-row-1"
    assert item["payload"] == {"order_id": "o-1"}
    assert item["meta"] == {"attempts": 2}


async def test_list_dlq_preserves_malformed_content_under_raw() -> None:
    """Unparseable JSON is preserved under ``_raw`` instead of raising."""
    malformed = {
        "id": "broken-1",
        "payload": "{not json",
        "meta": "[]",  # valid JSON, but not an object
    }
    client = _FakeRedis([("1714000000000-0", malformed)])

    items = await list_dlq(client, "order.events.dlq")

    assert items[0]["envelope"] is False
    assert items[0]["payload"] == {"_raw": "{not json"}
    assert items[0]["meta"] == {"_raw": "[]"}


async def test_list_dlq_reports_an_envelope_occurred_at_not_the_bus_timestamp() -> None:
    """``occurred_at`` comes from the envelope, never the DLQ row's ``ts``."""
    occurred_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    envelope = build_envelope(
        "order.refunded",
        tenant_id=uuid.uuid4(),
        aggregate_type="order",
        aggregate_id=uuid.uuid4(),
        payload={"amount": 12.5},
        occurred_at=occurred_at,
    )
    fields = _dlq_fields(serialize(envelope), dlq_reason="r")

    items = await list_dlq(_FakeRedis([("1715000000000-0", fields)]), "order.events.dlq")

    assert items[0]["occurred_at"] == occurred_at.isoformat()
    assert items[0]["occurred_at"] != fields["ts"]
