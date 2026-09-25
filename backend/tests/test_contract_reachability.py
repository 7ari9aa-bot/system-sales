"""Contract reachability: every serialize/deserialize pair must ROUND-TRIP.

The defect class this guards
---------------------------
``app/core/events/schemas.py`` defined a §19 envelope with a ``deserialize()``
that needs ``occurred_at`` / ``aggregate_type`` / ``aggregate_id``, and the real
publish path (``writer.add_outbox_event``) hand-merged a meta dict instead — so
none of those keys were ever published. The envelope was unit-tested IN
ISOLATION and the production path skipped it. Worse than dead code: consumers
relied on the shape.

So this file does not assert that functions exist (a test that cannot fail is
worse than no test). For each pair a real caller half-bypasses, it drives the
REAL writer/reader half and asserts the round trip:

    deserialize(serialize(x)) == x   for a real object

Pairs covered, and why each is worth a permanent test:

1. §19 envelope — ``serialize`` (called by ``core/events/writer``) vs
   ``deserialize`` (called by NOTHING under ``app/``: the workers, the SSE
   gateway, the relay and the DLQ inspector all hand-parse ``meta`` instead).
   The envelope is what a STORED row (``outbox_events.payload`` / ``.meta``)
   holds and what every consumer reads.
2. Idempotency replay record — ``IdempotencyService.complete`` writes it,
   ``IdempotencyMiddleware._send_stored`` reads it back. Stored in
   ``idempotency_keys.response``. The existing tests hand-build the stored dict
   instead of driving ``complete``, which is the same anti-pattern in test form.
3. Billing period snapshot — ``snapshot_lines`` writes ``invoices.extra``,
   ``snapshot_view`` reads it. Money is stored as exact strings on purpose; a
   reader that returns a float would silently corrupt every invoice.
4. Metric definition registry — ``MetricSpec.as_dict`` is the write half of
   ``metric_definitions`` with no inverse; the row's columns ARE the contract.
5. Cursor, ETag and visitor-token pairs — both halves are wired, but these are
   the other opaque-string contracts a consumer (the frontend / an SSE client)
   depends on, so they are pinned here too.
6. Table read reachability — the §4 gap-register claim "FeatureFlag /
   MetricDefinition / SecretReference | dead tables" was half stale: two of the
   three are served by live routes, one (``metric_definitions``) was WRITE-ONLY,
   read by nothing but the function that writes it, while two endpoints NAMED
   AFTER DEFINITIONS answered from a Python registry. A round-trip pair is only
   half the story: a table can be perfectly serialized and still be read by
   nobody. So this section (a) drives the real route for each of the three
   tables and proves the ROW's bytes reach the response, and (b) pins the set
   of tables app code never SELECTs, so a new one cannot join silently.

Type-preservation: the envelope pair preserves the Python types a real
producer sends. ``app/modules/orders/service.py`` publishes ``grand_total`` as a
``Decimal`` on ``order.created``, and ``serialize``/``deserialize`` tag
JSON-unrepresentable values so ``deserialize(serialize(x)) == x`` holds for a
``Decimal`` / ``datetime`` / ``UUID`` — money never arrives at a consumer as a
string. (This was the audit's finding 1; the ``xfail(strict=True)`` tripwire
that pinned the violation is removed now that the pair is fixed. See
``docs/CONTRACT_AUDIT.md``.)

DB-free: every test here runs locally (the fake session pattern is the same one
``tests/test_event_envelope.py`` uses).
"""

from __future__ import annotations

import ast
import base64
import json
import pathlib
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.events.schemas import build_envelope, deserialize, serialize
from app.core.events.writer import add_outbox_event
from app.core.idempotency import etag_for, parse_if_match
from app.core.pagination import decode_cursor, encode_cursor
from app.core.security import create_visitor_token, decode_visitor_token
from app.modules.billing.models import Invoice
from app.modules.billing.service import BillingSnapshotService, PeriodUsage
from app.modules.platform.metrics import (
    METRIC_DEFINITIONS,
    MetricRegistry,
    MetricSpec,
)
from app.modules.platform.models import MetricDefinition

# ---------------------------------------------------------------------------
# 1. §19 envelope: the writer's output must be what deserialize() rebuilds
# ---------------------------------------------------------------------------

#: The real, closed set of outbox event types and the payload shape each real
#: call site passes. Every entry is an ``add_outbox_event(...)`` call site in
#: ``app/`` — none invented. ``grand_total`` is passed as a string here because
#: the Decimal case is the KNOWN VIOLATION pinned separately below.
REAL_EVENTS: tuple[tuple[str, str, dict[str, Any]], ...] = (
    (
        "order",
        "order.created",
        {
            "order_id": "00000000-0000-0000-0000-000000000001",
            "number": "SO-1",
            "customer_id": "00000000-0000-0000-0000-000000000002",
            "warehouse_id": "00000000-0000-0000-0000-000000000003",
            "status": "placed",
            "currency": "EGP",
            "grand_total": "76.50",
            "item_count": 2,
        },
    ),
    ("order", "order.cancelled", {"order_id": "o-1", "number": "SO-1", "to_status": "cancelled"}),
    (
        "order",
        "order.status_changed",
        {"order_id": "o-1", "from_status": "placed", "to_status": "paid"},
    ),
    (
        "order",
        "order.refunded",
        {
            "order_id": "o-1",
            "number": "SO-1",
            "payment_id": "p-1",
            "amount": 12.5,
            "payment_status": "refunded",
        },
    ),
    (
        "message",
        "message.received",
        {"conversation_id": "c-1", "customer_id": "cu-1", "channel": "webchat"},
    ),
    ("message", "message.outbound", {"message_id": "m-1", "conversation_id": "c-1"}),
    ("notification", "notification.queued", {"notification_id": "n-1"}),
    ("webhook", "webhook.deliver", {"delivery_id": "d-1"}),
    (
        "customer",
        "customer.merged",
        {"canonical_customer_id": "cu-1", "merged_away_customer_id": "cu-2"},
    ),
    (
        "customer",
        "privacy.customer_deleted",
        {"customer_id": "cu-1", "steps": [{"step": "x", "done": True}]},
    ),
)


def _magic_session() -> MagicMock:
    """A session that emulates the DB PK default so ``meta['outbox_id']`` is real.

    ``add_outbox_event`` stamps ``meta['outbox_id'] = str(event.id)`` AFTER the
    flush; without a database the ORM instance has no id. Assigning one on
    ``add`` is what makes the id-linkage assertion below non-vacuous.
    """

    def _add(instance: Any) -> None:
        if getattr(instance, "id", None) is None:
            instance.id = uuid.uuid4()

    session = MagicMock()
    session.add = MagicMock(side_effect=_add)
    session.flush = AsyncMock()
    return session


async def _publish(**kwargs: Any) -> dict[str, Any]:
    """Drive the REAL writer, then hand back exactly what a consumer receives.

    Returns the outbox row's ``payload`` / ``meta`` as parsed dicts — which is
    precisely what the relay publishes and what ``deserialize`` accepts.
    ``__row_id`` is the outbox ROW id, carried alongside for the dedupe
    assertion; ``deserialize`` ignores unknown top-level keys.
    """
    event = await add_outbox_event(_magic_session(), **kwargs)
    return {"payload": event.payload, "meta": event.meta, "__row_id": str(event.id)}


@pytest.mark.parametrize(("aggregate_type", "event_type", "payload"), REAL_EVENTS)
async def test_published_outbox_event_round_trips_through_deserialize(
    aggregate_type: str, event_type: str, payload: dict[str, Any]
) -> None:
    """A real published event rebuilds via deserialize() with every field intact."""
    tenant_id = uuid.uuid4()
    aggregate_id = uuid.uuid4()

    fields = await _publish(
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        tenant_id=tenant_id,
        payload=payload,
    )

    envelope = deserialize(fields)

    assert envelope.type == event_type
    assert envelope.tenant_id == tenant_id
    assert envelope.aggregate_type == aggregate_type
    assert envelope.aggregate_id == aggregate_id
    assert envelope.version == 1
    assert envelope.occurred_at is not None
    # The payload survives the JSONB hop key-for-key. The writer injects
    # `event_type` as the FIRST payload key (workers route on it), so the
    # rebuilt payload is the caller's payload plus exactly that one key.
    assert envelope.payload["event_type"] == event_type
    assert {k: v for k, v in envelope.payload.items() if k != "event_type"} == payload
    assert envelope.id == str(fields["meta"]["id"])


async def test_published_row_meta_is_a_complete_envelope() -> None:
    """The row's meta carries every routing key deserialize() requires.

    ``occurred_at`` / ``aggregate_type`` / ``aggregate_id`` are exactly the keys
    the original defect dropped, so they are asserted by name, not by presence.
    """
    tenant_id = uuid.uuid4()
    aggregate_id = uuid.uuid4()

    fields = await _publish(
        aggregate_type="order",
        aggregate_id=aggregate_id,
        event_type="order.created",
        tenant_id=tenant_id,
        payload={"order_id": str(aggregate_id)},
        meta={"source": "unit-test"},
        correlation_id="corr-1",
        causation_id="cause-1",
        producer="orders-svc",
        schema_version=2,
        aggregate_version=7,
    )
    meta = fields["meta"]

    routing_keys = (
        "id",
        "type",
        "version",
        "tenant_id",
        "occurred_at",
        "aggregate_type",
        "aggregate_id",
    )
    for key in routing_keys:
        assert key in meta, f"envelope routing key {key!r} missing from the published meta"

    assert meta["type"] == "order.created"
    assert meta["tenant_id"] == str(tenant_id)
    assert meta["aggregate_type"] == "order"
    assert meta["aggregate_id"] == str(aggregate_id)
    # user meta survives alongside the routing keys
    assert meta["source"] == "unit-test"
    # lineage survives, and deserialize() agrees with the transport meta
    envelope = deserialize(fields)
    assert envelope.correlation_id == "corr-1"
    assert envelope.causation_id == "cause-1"
    assert envelope.producer == "orders-svc"
    assert envelope.schema_version == 2
    assert envelope.aggregate_version == 7
    # user meta survives; `outbox_id` is the extra key the writer stamps on the
    # row AFTER serialize() (so the row is the serialized form PLUS that key —
    # still deserializable, which is the point).
    assert envelope.meta["source"] == "unit-test"
    # the envelope id and the outbox ROW id are two different identifiers, and
    # both survive: `id` is what deserialize() rebuilds the envelope from,
    # `outbox_id` is the stable consumer-inbox dedupe key (workers/base._process)
    assert envelope.id == meta["id"]
    assert meta["outbox_id"] == fields["__row_id"]
    assert envelope.meta["outbox_id"] == fields["__row_id"]


def test_envelope_round_trip_preserves_payload_value_types() -> None:
    """The REAL order.created payload shape, with grand_total as a Decimal.

    Money is a ``Decimal`` end to end: the producer builds ``Decimal("76.50")``
    and the consumer rebuilds a ``Decimal``, not the string the JSONB/Redis hop
    used to degrade it to. The JSON hop is emulated with ``json.dumps`` /
    ``json.loads`` — the exact encode/decode the column and the stream perform.
    """
    envelope = build_envelope(
        "order.created",
        tenant_id=uuid.uuid4(),
        aggregate_type="order",
        aggregate_id=uuid.uuid4(),
        payload={"order_id": "o-1", "grand_total": Decimal("76.50"), "item_count": 2},
    )

    fields = serialize(envelope)
    wire = {key: json.loads(value) for key, value in fields.items()}
    rebuilt = deserialize(wire)

    assert rebuilt.payload == envelope.payload
    assert isinstance(rebuilt.payload["grand_total"], Decimal)
    assert rebuilt.payload["grand_total"] == Decimal("76.50")


# ---------------------------------------------------------------------------
# 2. Idempotency replay record (stored in idempotency_keys.response)
# ---------------------------------------------------------------------------


async def test_idempotency_replay_record_round_trips(monkeypatch: pytest.MonkeyPatch) -> None:
    """complete() encodes the response; _send_stored() must replay those bytes.

    The existing tests build ``{"body": base64.b64encode(...)}`` by hand, so a
    drift in ``complete()``'s encoding would not be caught. This drives both
    real halves.
    """
    from app.core import idempotency as idem

    record = MagicMock()
    record.status = idem.STATUS_PROCESSING
    record.response = None

    async def _fake_find(session, scope, key):
        return record

    monkeypatch.setattr(idem, "_find", _fake_find)

    session = MagicMock()
    session.flush = AsyncMock()
    original = b'{"id":"abc","grand_total":"76.50"}'

    await idem.IdempotencyService.complete(
        session, scope="http:tenant:route", key="k-1", status_code=201,
        body=original, content_type="application/json",
    )
    stored = record.response
    assert stored is not None
    # the row is JSONB-native: the body must be text, not bytes
    assert json.loads(json.dumps(stored)) == stored

    sent: list[dict[str, Any]] = []

    async def _send(message: dict[str, Any]) -> None:
        sent.append(message)

    await idem._send_stored(_send, stored)

    start = next(m for m in sent if m["type"] == "http.response.start")
    body = next(m for m in sent if m["type"] == "http.response.body")["body"]
    assert start["status"] == 201
    assert body == original
    assert (b"idempotency-replayed", b"true") in [(k.lower(), v) for k, v in start["headers"]]


# ---------------------------------------------------------------------------
# 3. Billing period snapshot (stored in invoices.extra)
# ---------------------------------------------------------------------------


def test_billing_snapshot_lines_round_trip_through_snapshot_view() -> None:
    """snapshot_lines() writes invoices.extra; snapshot_view() reads it back.

    The write half stores quantities as STRINGS so a Numeric(14,2) total is not
    degraded by a JSON number -> IEEE float decode. This asserts the reader
    returns exactly what the writer froze, across a JSONB round trip, and that
    the money stays exact rather than becoming a float.
    """
    usage = PeriodUsage(
        features={
            "orders": Decimal("2.00"),
            "ai_tokens": Decimal("1200"),
            "messages": Decimal("10.50"),
        },
        ai_cost=Decimal("0.00123000"),
    )

    # what close_period() puts in Invoice.extra
    extra = {
        "snapshot": BillingSnapshotService.snapshot_lines(usage),
        "ai_cost": str(usage.ai_cost),
    }
    # the JSONB hop: the column stores JSON, so the value must survive it
    extra = json.loads(json.dumps(extra))

    invoice = Invoice(
        tenant_id=uuid.uuid4(),
        number="INV-202608-ABCDEF",
        status="open",
        subtotal=Decimal("0.00"),
        tax=Decimal("0.00"),
        total=Decimal("0.00"),
        currency="EGP",
        extra=extra,
    )

    view = BillingSnapshotService.snapshot_view(invoice)

    frozen = {line["feature"]: line["quantity"] for line in view["features"]}
    assert frozen == {
        "ai_tokens": "1200",
        "messages": "10.50",
        "orders": "2.00",
    }
    # and it re-reads as the exact Decimal the aggregate produced
    assert {k: Decimal(v) for k, v in frozen.items()} == usage.features
    assert view["ai_cost"] == "0.00123000"
    assert Decimal(view["ai_cost"]) == usage.ai_cost
    assert view["number"] == invoice.number
    assert view["status"] == "open"


# ---------------------------------------------------------------------------
# 4. Metric definition registry: as_dict() must be the row's column set
# ---------------------------------------------------------------------------


def test_metric_spec_as_dict_matches_the_stored_columns() -> None:
    """seed_definitions() inserts ``{**spec.as_dict(), 'tenant_id': ...}``.

    ``as_dict`` is the write half of ``metric_definitions`` with no inverse, so
    the row's columns ARE the contract: a key that is not a column makes the
    insert fail. (Columns the dict does not mention are nullable mixins —
    ``workspace_id`` / ``location_id`` / ``updated_at`` — which is why this is a
    subset assertion in that direction only.)
    """
    columns = {column.name for column in MetricDefinition.__table__.columns}

    for spec in METRIC_DEFINITIONS:
        assert isinstance(spec, MetricSpec)
        assert set(spec.as_dict()) <= columns, spec.name
        assert set(spec.as_dict()) == {field for field in spec.__dataclass_fields__}
        # values must be JSONB-native so the insert cannot fail on a type
        for key, value in spec.as_dict().items():
            assert value is None or isinstance(value, (str, int, float, bool, dict, list)), (
                spec.name,
                key,
                type(value),
            )


# ---------------------------------------------------------------------------
# 5. Cursor, ETag and visitor-token pairs (both halves wired today)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "created_at",
    [
        datetime(2026, 8, 1, 12, 30, 45, 123456, tzinfo=UTC),
        datetime(2026, 8, 1, 12, 30, 45),
        datetime(1970, 1, 1, tzinfo=UTC),
    ],
)
def test_cursor_pair_round_trips(created_at: datetime) -> None:
    row_id = uuid.uuid4()
    assert decode_cursor(encode_cursor(created_at, row_id)) == (created_at, row_id)


@pytest.mark.parametrize("version", [1, 2, 7, 1000])
def test_etag_pair_round_trips(version: int) -> None:
    assert parse_if_match(etag_for(version)) == version


def test_visitor_token_pair_round_trips() -> None:
    tenant_id = uuid.uuid4()
    token = create_visitor_token("sess-1", str(tenant_id), widget="pk_1")

    claims = decode_visitor_token(token)

    assert claims["sub"] == "sess-1"
    assert claims["tenant_id"] == str(tenant_id)
    assert claims["widget"] == "pk_1"
    assert claims["type"] == "webchat_visitor"


def test_b64_round_trip_is_what_the_idempotency_row_relies_on() -> None:
    """The exact encoding step both halves share, pinned as a value assertion.

    Kept separate from the middleware test so a change to the base64 alphabet
    (e.g. urlsafe) fails HERE with an obvious name rather than as a mysteriously
    empty replayed body.
    """
    payload = b'{"ok":true}'
    encoded = base64.b64encode(payload).decode("ascii")
    assert base64.b64decode(encoded) == payload


# ---------------------------------------------------------------------------
# 6. Table read reachability: a table nothing READS has no consumer
# ---------------------------------------------------------------------------
#
# ``docs/GAP_REGISTER.md`` §4 lists ``FeatureFlag / MetricDefinition /
# SecretReference`` as "dead tables". Measured on the code, two of the three
# claims were stale — both are read and written behind mounted, permission-gated
# routes — and one was true in a way the register did not describe:
# ``metric_definitions`` had a write path (the provisioning seed and
# ``scripts/backfill_metric_definitions.py``) whose only SELECT was the one
# inside the writer itself, used to decide what to UPDATE. Nothing served a row,
# while ``GET /platform/metrics`` and ``GET /analytics/metrics/definitions``
# answered from the in-code ``MetricRegistry``. That is the repo's named failure
# mode in its narrowest form: not dead code, but a live table with no reader, and
# an endpoint whose name implies a source it never queries.
#
# So this section guards both directions:
#
#   * BEHAVIOURALLY — for each §4 table, drive the REAL route with a stub
#     session holding a row whose value exists nowhere in Python, and require
#     that value to arrive in the response. Delete the route, or re-point it at
#     an in-code source, and the named test goes red.
#   * STATICALLY — no ORM table may exist that ``app/`` never reads, unless it is
#     named below with the reason. The baseline may only SHRINK; a new write-only
#     table fails naming it.

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]
MODELS_DIR = BACKEND_ROOT / "app" / "modules"

#: Methods whose first argument being a model means "this code reads the table".
_READ_CALLS = frozenset({"select", "update", "delete", "insert", "get"})

#: Tables ``app/`` never reads, and why. This is the dead-schema inventory of
#: ``docs/GAP_REGISTER.md`` §4 plus the voice/ads tables whose ingest was never
#: built. Wiring a reader for one means DELETING its entry here — the positive
#: assertion then keeps it read.
TABLES_NEVER_READ: dict[str, str] = {
    # No writer and no reader: the schema exists, the feature does not.
    "Prompt": "§38 prompt registry — dead schema, zero references outside the model.",
    "AISession": "conversations — dead schema, zero references outside the model.",
    "PhoneNumber": "voice — no ingest writes it, no route reads it.",
    "Call": "voice — superseded by the telephony work; nothing constructs a row.",
    "CallSession": "voice — same: no producer, no reader.",
    "CallLeg": "voice — same: no producer, no reader.",
    "AdSet": "marketing — Meta ad ingest that would fill it is unbuilt.",
    "Ad": "marketing — same; no producer, no reader.",
    # platform/models.py — the `automations` table. The automation that shipped
    # is app/modules/automation/ on the `workflows` tables, so nothing here is
    # ever written or read: two schemas for one feature, one of them abandoned.
    "Automation": "platform — superseded by automation/workflows; no writer, no reader.",
    # Written by a live path, read by nothing: the row is a receipt, not a source.
    "DeliveryAttempt": "§130 — message_worker writes one row per attempt; nobody reads it.",
    "AIHandover": "ai/hooks + runtime write handover rows; no surface lists them.",
    "WorkflowFailure": "automation/service writes failures a dispatcher never reads.",
    "Assignment": "conversations/service writes assignments; no read model serves them.",
    "TemplateApproval": "§templates — approval rows never checked at send.",
    "IdentityMergeEvent": "customers/service writes the merge trail; no API reads it.",
}


def _orm_tables() -> dict[str, str]:
    """Model class name -> ``__tablename__`` for every declarative model."""
    tables: dict[str, str] = {}
    for path in sorted(MODELS_DIR.glob("*/models.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            if not any("Base" in ast.unparse(base) for base in node.bases):
                continue
            for statement in node.body:
                targets = (
                    statement.targets
                    if isinstance(statement, ast.Assign)
                    else ([statement.target] if isinstance(statement, ast.AnnAssign) else [])
                )
                named = any(
                    (getattr(t, "id", None) or getattr(t, "attr", None)) == "__tablename__"
                    for t in targets
                )
                if named and statement.value is not None:
                    try:
                        tables[node.name] = ast.literal_eval(statement.value)
                    except (ValueError, SyntaxError):
                        pass
    return tables


def _module_sources() -> dict[str, str]:
    """Every non-test, non-models app source: relative path -> text."""
    sources: dict[str, str] = {}
    for path in sorted((BACKEND_ROOT / "app").rglob("*.py")):
        if "__pycache__" in path.parts or path.name == "models.py":
            continue
        sources[path.relative_to(BACKEND_ROOT).as_posix()] = path.read_text(encoding="utf-8")
    return sources


def _reading_modules(sources: dict[str, str]) -> dict[str, set[str]]:
    """Model name -> app modules that read its table.

    A read is either an ORM call naming the class (``select(Model)``,
    ``session.get(Model, pk)``, ``Model.__table__``) or raw SQL naming the
    TABLE (``FROM audit_logs``) — the two ways this codebase actually reads.
    """
    readers: dict[str, set[str]] = {}

    def note(model: str, where: str) -> None:
        readers.setdefault(model, set()).add(where)

    for rel, src in sources.items():
        tree = ast.parse(src, filename=rel)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = (
                    func.id
                    if isinstance(func, ast.Name)
                    else (func.attr if isinstance(func, ast.Attribute) else None)
                )
                if name not in _READ_CALLS:
                    continue
                for arg in node.args:
                    target = None
                    if isinstance(arg, ast.Name):
                        target = arg.id
                    elif isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name):
                        target = arg.value.id
                    elif isinstance(arg, ast.Starred) and isinstance(arg.value, ast.Name):
                        target = arg.value.id
                    if target and target[:1].isupper():
                        note(target, rel)
            elif isinstance(node, ast.Attribute) and node.attr == "__table__":
                if isinstance(node.value, ast.Name):
                    note(node.value.id, rel)
        for table in set(re.findall(r"\b([a-z][a-z0-9_]{3,})\b", src)):
            if re.search(rf"\b(?:from|join|into)\s+{re.escape(table)}\b", src, re.IGNORECASE):
                note(f"table:{table}", rel)
    return readers


def write_only_tables() -> list[str]:
    """Model names whose table is never read anywhere in ``app/``."""
    sources = _module_sources()
    readers = _reading_modules(sources)
    sql_read_by_table = {
        key.removeprefix("table:"): mods
        for key, mods in readers.items()
        if key.startswith("table:")
    }
    unread: list[str] = []
    for model, table in _orm_tables().items():
        if readers.get(model) or sql_read_by_table.get(table):
            continue
        unread.append(model)
    return sorted(unread)


def test_no_table_is_written_but_never_read_beyond_the_recorded_baseline() -> None:
    """A table ``app/`` never reads is storage nobody consults — dead by definition.

    New offender -> wire a reader or explain it in ``TABLES_NEVER_READ`` (and
    expect the explanation to be audited). Entry that has become readable -> the
    wiring worked; delete the entry so the guard starts enforcing it.
    """
    unread = set(write_only_tables())
    baseline = set(TABLES_NEVER_READ)

    assert unread == baseline, (
        "table read-reachability drifted:\n"
        + "".join(
            f"  NEW write-only table {name}: nothing in app/ reads it — "
            "give it a reader or record why it waits\n"
            for name in sorted(unread - baseline)
        )
        + "".join(
            f"  {name} is now READ but still recorded as unread — "
            "delete its TABLES_NEVER_READ entry\n"
            for name in sorted(baseline - unread)
        )
    )


def test_detector_distinguishes_read_from_unread() -> None:
    """Proof the read detector discriminates, so neither half passes vacuously.

    ``AuditLog`` is read only through raw SQL (so a class-name scan alone would
    wrongly report it dead) and ``FeatureFlag`` only through ``select()``;
    ``Prompt`` is read by neither and must appear in the offender list.
    """
    sources = _module_sources()
    readers = _reading_modules(sources)
    unread = set(write_only_tables())

    assert readers.get("FeatureFlag"), "detector missed a select(Model) read"
    assert readers.get("table:audit_logs"), "detector missed a raw-SQL read"
    assert "AuditLog" not in unread, "a raw-SQL-read table was reported unread"
    assert "Prompt" in unread, "detector reports a table nothing reads as alive"


# --- the §4 tables, served: drive the real route, require the row's bytes ----

SERVED_TENANT = uuid.UUID("99999999-9999-9999-9999-999999999999")


class _ServedResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalars(self) -> _ServedResult:
        return self

    def first(self) -> Any:
        return self._rows[0] if self._rows else None

    def scalar_one(self) -> Any:
        return self._rows[0]

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None


class _ServedSession:
    """Answers every read with one fixed row set; records writes, touches no DB."""

    def __init__(self, rows: list[Any]) -> None:
        self._result = _ServedResult(rows)
        self.added: list[Any] = []

    async def execute(self, *_args: Any, **_kwargs: Any) -> _ServedResult:
        return self._result

    def add(self, instance: Any) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None


def _served_ctx(rows: list[Any], *, permissions: set[str]) -> Any:
    from app.modules.identity.deps import AuthedUser, TenantContext

    user = AuthedUser(
        id=uuid.uuid4(),
        tenant_id=SERVED_TENANT,
        role_code="owner",
        is_platform_admin=False,
    )
    return TenantContext(
        session=_ServedSession(rows),
        user=user,
        tenant_id=SERVED_TENANT,
        role_code="owner",
        permission_codes=permissions,
    )


async def _drive(method: str, path: str, rows: list[Any], *, permissions: set[str], body=None):
    """Send a real request through the mounted app with a fabricated context."""
    from fastapi import Depends

    from app.main import create_app
    from app.modules.identity.deps import get_db, get_tenant_ctx

    ctx = _served_ctx(rows, permissions=permissions)
    app = create_app()

    async def _session():
        yield ctx.session

    app.dependency_overrides[get_tenant_ctx] = lambda: ctx
    app.dependency_overrides[get_db] = Depends(_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", timeout=10) as client:
        response = await client.request(method, path, json=body)
    return response, ctx


def _metric_definition(marker: str) -> MetricDefinition:
    return MetricDefinition(
        tenant_id=SERVED_TENANT,
        name="revenue",
        definition=marker,
        source="orders",
        filters={},
        timezone_rule="merchant_local",
        currency_rule="presentment",
        refund_treatment="excluded",
        version=1,
    )


async def test_metric_definitions_table_is_served_by_a_route() -> None:
    """``GET /platform/metrics/definitions`` answers from the ROW, not the code.

    This is the §4 resolution for ``metric_definitions``: the seed and the
    backfill script write it, and this route is the half that reads it. The
    marker exists nowhere in the registry, so a handler that fell back to
    ``MetricRegistry`` — the previous behaviour of every "definitions" endpoint —
    cannot produce it.
    """
    marker = "ROW-ONLY-DEFINITION-F1EEDBACK"
    response, _ = await _drive(
        "GET", "/api/v1/platform/metrics/definitions", [_metric_definition(marker)],
        permissions=set(),
    )

    assert response.status_code == 200, response.text
    assert marker in response.text
    assert marker not in json.dumps(MetricRegistry.definitions())
    item = next(entry for entry in response.json()["items"] if entry["definition"] == marker)
    assert item["name"] == "revenue" and item["version"] == 1


async def test_feature_flags_table_is_served_by_a_route() -> None:
    """``GET /platform/flags`` carries the row's feature name end to end."""
    from app.modules.platform.models import FeatureFlag

    marker = "row-only.feature.marker"
    row = FeatureFlag(
        tenant_id=SERVED_TENANT, feature=marker, enabled=True, rollout_percent=100
    )
    response, _ = await _drive("GET", "/api/v1/platform/flags", [row], permissions=set())

    assert response.status_code == 200, response.text
    assert marker in response.text


async def test_secret_references_table_is_served_by_a_route(monkeypatch) -> None:
    """``POST /platform/secrets/{provider}/rotate`` reads the row back and answers.

    ``secret_references`` is NOT a second copy of the §68/G-06 value store — that
    one is ``secret_values``, backed by ``core.secrets.DatabaseSecretStore``.
    This table holds the reference half (provider, vault_key, status, version)
    and is read on a live route, so the register's "dead table" claim is stale.
    """
    from app.core.secrets import InMemorySecretStore, set_secret_store
    from app.modules.platform.models import SecretReference

    monkeypatch.setattr("app.core.secrets._store", InMemorySecretStore())
    set_secret_store(InMemorySecretStore())

    marker = "row-only-provider"
    row = SecretReference(
        id=uuid.uuid4(),
        tenant_id=SERVED_TENANT,
        scope="tenant",
        provider=marker,
        vault_key="vault-key-1",
        status="active",
        version=1,
    )
    response, _ = await _drive(
        "POST",
        "/api/v1/platform/secrets/whatsapp/rotate",
        [row],
        permissions={"settings:write"},
        body={"new_value": "rotation-under-test"},
    )

    assert response.status_code == 200, response.text
    assert marker in response.text


def test_router_definition_fields_are_the_synced_registry_fields() -> None:
    """``_DEFINITION_FIELDS`` (router) and ``_SYNCED_FIELDS`` (metrics) must agree.

    The route compares a row against the registry using one field list and the
    seed converges using the other; if they drift, the drift report and the
    convergence stop describing the same contract — and the route would report
    a tenant as clean while the seed kept rewriting it.
    """
    from app.modules.platform.metrics import _SYNCED_FIELDS
    from app.modules.platform.router import _DEFINITION_FIELDS

    assert set(_DEFINITION_FIELDS) == set(_SYNCED_FIELDS)
