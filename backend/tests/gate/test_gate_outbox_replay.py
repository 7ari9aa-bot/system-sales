"""Published-outbox recovery after Redis loss (§163).

DB-backed because the recovery query must agree with the consumer inbox and
the stable outbox id. Requires the same real-Postgres gate environment as the
other tests in this directory.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.events.replay import replay_unprocessed_published
from app.core.events.writer import add_outbox_event
from app.modules.platform.models import ProcessedEvent


class RecordingBus:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    async def publish(
        self, stream: str, payload: dict[str, Any], meta: dict[str, Any] | None = None
    ) -> str:
        self.published.append((stream, payload, meta or {}))
        return f"{len(self.published)}-0"


@pytest.mark.gate
async def test_published_outbox_recovery_previews_and_replays_only_unprocessed(
    db, tenant_ctx, monkeypatch
) -> None:
    connection = await db.connection()
    factory = async_sessionmaker(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    monkeypatch.setattr("app.core.events.replay.get_sessionmaker", lambda: factory)

    processed = await add_outbox_event(
        db,
        aggregate_type="message",
        aggregate_id=uuid.uuid4(),
        event_type="message.outbound",
        tenant_id=tenant_ctx.tenant_id,
        payload={"message_id": str(uuid.uuid4())},
    )
    await db.flush()
    processed.status = "published"
    db.add(
        ProcessedEvent(
            consumer_name="message-worker", event_id=processed.id, status="done"
        )
    )

    pending_aggregate_id = uuid.uuid4()
    pending_message_id = str(uuid.uuid4())
    pending = await add_outbox_event(
        db,
        aggregate_type="message",
        aggregate_id=pending_aggregate_id,
        event_type="message.outbound",
        tenant_id=tenant_ctx.tenant_id,
        payload={"message_id": pending_message_id},
    )
    await db.flush()
    pending.status = "published"
    pending_id = pending.id

    # A delayed retry is another published row but carries the original
    # dedupe id. Recovery should emit one copy of that logical event.
    retry = await add_outbox_event(
        db,
        aggregate_type="message",
        aggregate_id=pending_aggregate_id,
        event_type="message.outbound",
        tenant_id=tenant_ctx.tenant_id,
        payload={"message_id": pending_message_id},
    )
    await db.flush()
    retry.status = "published"
    retry.meta = {**retry.meta, "outbox_id": str(pending_id)}
    await db.flush()

    legacy = await add_outbox_event(
        db,
        aggregate_type="message",
        aggregate_id=uuid.uuid4(),
        event_type="message.outbound",
        tenant_id=tenant_ctx.tenant_id,
        payload={"message_id": str(uuid.uuid4())},
    )
    await db.flush()
    legacy.status = "published"
    legacy.meta = {
        key: value for key, value in legacy.meta.items()
        if key not in {"id", "outbox_id"}
    }

    # Legacy non-outbound messages lack a stable replay key and are left alone.
    unsafe_legacy = await add_outbox_event(
        db,
        aggregate_type="message",
        aggregate_id=uuid.uuid4(),
        event_type="message.received",
        tenant_id=tenant_ctx.tenant_id,
        payload={"conversation_id": str(uuid.uuid4())},
    )
    await db.flush()
    unsafe_legacy.status = "published"
    unsafe_legacy.meta = {
        key: value for key, value in unsafe_legacy.meta.items()
        if key not in {"id", "outbox_id"}
    }

    bus = RecordingBus()
    preview = await replay_unprocessed_published(bus, "message.events")
    assert preview.eligible == 2
    assert preview.published == 0
    assert bus.published == []

    replay = await replay_unprocessed_published(bus, "message.events", execute=True)
    assert replay.eligible == 2
    assert replay.published == 2
    assert len(bus.published) == 2
    assert {stream for stream, _payload, _meta in bus.published} == {"message.events"}
    assert {meta["outbox_id"] for _stream, _payload, meta in bus.published} == {
        str(pending_id), str(legacy.id)
    }


async def test_published_outbox_recovery_rejects_unknown_stream() -> None:
    with pytest.raises(ValueError, match="unsupported recovery stream"):
        await replay_unprocessed_published(RecordingBus(), "order.events")


async def test_published_outbox_recovery_bounds_batch_size() -> None:
    with pytest.raises(ValueError, match="batch_size must be between"):
        await replay_unprocessed_published(
            RecordingBus(), "message.events", batch_size=0
        )
