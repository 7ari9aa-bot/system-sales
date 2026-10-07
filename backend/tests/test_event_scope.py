"""§19/§153 — the envelope's scope fields, the versioned read half, and
per-aggregate ordering detection in the durable event log.

The §19 event contract names ``workspace_id`` and ``location_id`` between
``tenant_id`` and the aggregate identity; the envelope carried neither, so
events could not express sub-tenant scope (§151's RLS hierarchy needs them
downstream). ``schema_version`` was also write-only: every producer pinned it
to 1 and the read half ignored it entirely, so a versioned consumer/adapter
for an evolved event had nowhere to hook in (§153: "old events must stay
understandable via a versioned consumer/adapter"). And ``aggregate_version``
rode on the envelope but no code ever checked it — an out-of-order replay
into ``event_log`` (the durable projection) went unnoticed (§153's
same-aggregate ordering policy).

These tests pin the gaps, driving the REAL writer and the REAL relay
write-path (no DB for the unit cases; the event_log persistence case needs
CI Postgres).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events.outbox import OutboxRelay
from app.core.events.schemas import (
    ROUTING_KEYS,
    EventEnvelope,
    build_envelope,
    deserialize,
    register_event,
    serialize,
)
from app.core.events.writer import add_outbox_event


def _magic_session() -> MagicMock:
    session = MagicMock()
    session.flush = AsyncMock()
    return session


class _StubResult:
    """Scripted result for the relay's pre-insert ordering probe."""

    def __init__(self, value: Any = None) -> None:
        self._value = value

    def scalar(self) -> Any:
        return self._value


class _CapturingSession:
    """Records every execute's params and answers the ordering probe.

    ``max_version`` is what the aggregate's stored max(aggregate_version)
    reports; None means "no history for this aggregate".
    """

    def __init__(self, max_version: Any = None) -> None:
        self.params: list[Any] = []
        self._max_version = max_version

    async def execute(self, statement: Any, params: Any = None, **_kw: Any) -> _StubResult:
        self.params.append(params)
        # The ordering probe is the only execute that passes aggregate params
        # WITHOUT event_id (the INSERT carries event_id).
        if isinstance(params, dict) and "event_id" not in params:
            return _StubResult(self._max_version)
        return _StubResult()


# ---------------------------------------------------------------------------
# 1. The envelope carries §19's scope fields end to end
# ---------------------------------------------------------------------------


def test_build_envelope_carries_scope_fields() -> None:
    workspace_id = uuid.uuid4()
    location_id = uuid.uuid4()
    envelope = build_envelope(
        "order.created",
        tenant_id=uuid.uuid4(),
        aggregate_type="order",
        aggregate_id=uuid.uuid4(),
        workspace_id=workspace_id,
        location_id=location_id,
    )
    assert envelope.workspace_id == workspace_id
    assert envelope.location_id == location_id


def test_serialize_deserialize_round_trips_scope_fields() -> None:
    workspace_id = uuid.uuid4()
    location_id = uuid.uuid4()
    envelope = build_envelope(
        "order.created",
        tenant_id=uuid.uuid4(),
        aggregate_type="order",
        aggregate_id=uuid.uuid4(),
        workspace_id=workspace_id,
        location_id=location_id,
    )
    restored = deserialize(serialize(envelope))
    assert restored.workspace_id == workspace_id
    assert restored.location_id == location_id


def test_legacy_wire_without_scope_deserializes_to_none() -> None:
    """Rows published before scope fields existed must keep deserializing."""
    envelope = build_envelope(
        "order.created",
        tenant_id=uuid.uuid4(),
        aggregate_type="order",
        aggregate_id=uuid.uuid4(),
    )
    fields = serialize(envelope)
    meta = json.loads(fields["meta"])
    meta.pop("workspace_id", None)
    meta.pop("location_id", None)
    restored = deserialize({"payload": fields["payload"], "meta": json.dumps(meta)})
    assert restored.workspace_id is None
    assert restored.location_id is None


def test_user_meta_cannot_spoof_the_scope_routing_keys() -> None:
    """§151 will trust these claims: user meta must not be able to forge them."""
    evil = str(uuid.uuid4())
    fields = serialize(
        build_envelope(
            "order.created",
            tenant_id=uuid.uuid4(),
            aggregate_type="order",
            aggregate_id=uuid.uuid4(),
            meta={"workspace_id": evil, "location_id": evil},
        )
    )
    restored = deserialize(fields)
    assert restored.workspace_id is None
    assert restored.location_id is None
    assert restored.meta.get("workspace_id") is None
    assert {"workspace_id", "location_id"} <= ROUTING_KEYS


async def test_writer_stamps_scope_into_published_meta() -> None:
    """The REAL writer must carry scope onto the wire, like every other key."""
    workspace_id = uuid.uuid4()
    location_id = uuid.uuid4()
    row = await add_outbox_event(
        _magic_session(),
        aggregate_type="order",
        aggregate_id=uuid.uuid4(),
        event_type="order.created",
        tenant_id=uuid.uuid4(),
        workspace_id=workspace_id,
        location_id=location_id,
    )
    assert row.meta["workspace_id"] == str(workspace_id)
    assert row.meta["location_id"] == str(location_id)
    restored = deserialize({"payload": row.payload, "meta": row.meta})
    assert restored.workspace_id == workspace_id
    assert restored.location_id == location_id


# ---------------------------------------------------------------------------
# 2. §153 versioned consumer dispatch — schema_version selects the adapter
# ---------------------------------------------------------------------------


class SchemaV2Adapter(EventEnvelope):
    """A versioned consumer adapter registered for test.schema @ schema 2."""


def _register_v2_adapter() -> None:
    register_event("test.schema", schema_version=2)(SchemaV2Adapter)


def test_versioned_class_is_built_for_its_schema_version() -> None:
    _register_v2_adapter()
    envelope = build_envelope(
        "test.schema",
        tenant_id=uuid.uuid4(),
        aggregate_type="test",
        aggregate_id=uuid.uuid4(),
        schema_version=2,
    )
    assert isinstance(envelope, SchemaV2Adapter)


def test_deserialize_routes_by_schema_version_with_base_fallback() -> None:
    _register_v2_adapter()
    v2 = build_envelope(
        "test.schema",
        tenant_id=uuid.uuid4(),
        aggregate_type="test",
        aggregate_id=uuid.uuid4(),
        schema_version=2,
    )
    assert isinstance(deserialize(serialize(v2)), SchemaV2Adapter)

    v1 = build_envelope(
        "test.schema",
        tenant_id=uuid.uuid4(),
        aggregate_type="test",
        aggregate_id=uuid.uuid4(),
    )
    assert type(deserialize(serialize(v1))) is EventEnvelope


# ---------------------------------------------------------------------------
# 3. The relay persists scope into event_log and flags version regressions
# ---------------------------------------------------------------------------


def _order_row_and_fields(
    *,
    tenant_id: uuid.UUID,
    aggregate_id: uuid.UUID,
    aggregate_version: int | None,
    workspace_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
) -> tuple[dict, dict, dict]:
    envelope = build_envelope(
        "order.created",
        tenant_id=tenant_id,
        aggregate_type="order",
        aggregate_id=aggregate_id,
        workspace_id=workspace_id,
        location_id=location_id,
        aggregate_version=aggregate_version,
        payload={"order_id": str(aggregate_id)},
    )
    fields = serialize(envelope)
    row = {
        "id": uuid.uuid4(),
        "aggregate_type": "order",
        "aggregate_id": aggregate_id,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    payload = {"event_type": "order.created", **json.loads(fields["payload"])}
    return row, payload, json.loads(fields["meta"])


async def test_relay_event_log_persists_scope_fields() -> None:
    workspace_id = uuid.uuid4()
    location_id = uuid.uuid4()
    row, payload, meta = _order_row_and_fields(
        tenant_id=uuid.uuid4(),
        aggregate_id=uuid.uuid4(),
        aggregate_version=None,
        workspace_id=workspace_id,
        location_id=location_id,
    )
    session = _CapturingSession()
    await OutboxRelay(bus=MagicMock())._write_event_log(session, row, payload, meta)
    insert = next(p for p in session.params if p and "event_id" in p)
    assert insert["workspace_id"] == str(workspace_id)
    assert insert["location_id"] == str(location_id)


async def test_relay_flags_aggregate_version_regression(caplog) -> None:
    """§153: same aggregate → ordered. An event landing in the durable log
    with a version BELOW the max already stored is out-of-order — the relay
    must say so loudly instead of letting it pass silently."""
    row, payload, meta = _order_row_and_fields(
        tenant_id=uuid.uuid4(),
        aggregate_id=uuid.uuid4(),
        aggregate_version=3,
    )
    session = _CapturingSession(max_version=5)
    with caplog.at_level(logging.WARNING, logger="app.core.events.outbox"):
        await OutboxRelay(bus=MagicMock())._write_event_log(session, row, payload, meta)
    assert "aggregate_version_regression" in caplog.text
    # the history row is still written — event_log is append-only
    assert any(p and "event_id" in p for p in session.params)


async def test_event_log_scope_columns_round_trip_in_postgres(db: AsyncSession, tenant_ctx) -> None:
    """CI-only: the INSERT the relay runs must land the scope values in the
    real event_log columns (FKs to workspaces/locations, so this test uses a
    real workspace/location — the model/migration already has them)."""
    from app.modules.identity.models import Location, Workspace

    workspace = Workspace(
        tenant_id=tenant_ctx.tenant_id,
        name="Scope WS",
        slug=f"scope-ws-{uuid.uuid4().hex[:8]}",
    )
    db.add(workspace)
    await db.flush()
    location = Location(
        tenant_id=tenant_ctx.tenant_id,
        workspace_id=workspace.id,
        name="Scope Loc",
    )
    db.add(location)
    await db.flush()

    aggregate_id = uuid.uuid4()
    row, payload, meta = _order_row_and_fields(
        tenant_id=tenant_ctx.tenant_id,
        aggregate_id=aggregate_id,
        aggregate_version=7,
        workspace_id=workspace.id,
        location_id=location.id,
    )
    await OutboxRelay(bus=MagicMock())._write_event_log(db, row, payload, meta)
    await db.flush()
    stored = (
        await db.execute(
            text(
                "SELECT workspace_id, location_id, aggregate_version FROM event_log "
                "WHERE aggregate_id = :aid AND event_type = 'order.created'"
            ),
            {"aid": aggregate_id},
        )
    ).first()
    assert stored is not None
    assert str(stored.workspace_id) == str(workspace.id)
    assert str(stored.location_id) == str(location.id)
    assert stored.aggregate_version == 7
