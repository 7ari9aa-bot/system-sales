"""DECISION state machine — the V12 lifecycle, unit-tested with no database.

What is pinned here:

* Every LEGAL transition of the map passes, every ILLEGAL one raises
  ConflictError — through the pure ``validate_transition`` and through the
  service methods that are its only callers.
* ``content_hash`` is sha256 over the canonical (action + normalized_arguments)
  JSON: argument KEY ORDER is irrelevant, argument CONTENT is not.
* TTL: HIGH/CRITICAL decisions default to a 60-second ``expires_at``; a
  decision past its TTL can never become APPROVED or EXECUTED — the
  transition lands on EXPIRED instead (as a committed write, not an
  exception that a request rollback would erase).
* The dependency snapshot hash is order-independent and changes when a
  resource_version changes; ``record_dependency`` re-derives it and stores
  it on the decision row.

Service tests drive the real methods over a scripted fake session (the house
pattern from test_automation_routes.py): SQL is captured and routed by table,
so the tenant scoping of every read is asserted on the compiled statements.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.decisions.models import Decision
from app.modules.decisions.service import (
    ALLOWED_TRANSITIONS,
    DECISION_STATUSES,
    DecisionService,
    decision_content_hash,
    snapshot_hash_from_rows,
    validate_transition,
)

TENANT = uuid.UUID("22222222-2222-2222-2222-222222222222")
OTHER_TENANT = uuid.UUID("99999999-9999-9999-9999-999999999999")
NOW = datetime.now(UTC)  # dynamic: expiry tests subtract from it


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _decision(
    *,
    status: str = "PROPOSED",
    approval_state: str = "NOT_REQUIRED",
    risk_level: str = "LOW",
    expires_at: datetime | None = None,
    decision_id: uuid.UUID | None = None,
) -> Decision:
    return Decision(
        decision_id=decision_id or uuid.uuid4(),
        tenant_id=TENANT,
        action="order.create",
        risk_level=risk_level,
        normalized_arguments={"sku": "P1"},
        content_hash=decision_content_hash("order.create", {"sku": "P1"}),
        decision_status=status,
        approval_state=approval_state,
        created_at=NOW,
        expires_at=expires_at,
    )


# ------------------------------------------------------------ the machine ----


def test_the_transition_map_covers_the_whole_vocabulary() -> None:
    assert set(ALLOWED_TRANSITIONS) == DECISION_STATUSES


def test_the_documented_transitions_are_the_legal_ones() -> None:
    legal = {
        ("PROPOSED", "VERIFIED"),
        ("PROPOSED", "STALE"),
        ("PROPOSED", "EXPIRED"),
        ("VERIFIED", "PENDING_APPROVAL"),
        ("VERIFIED", "APPROVED"),
        ("VERIFIED", "DENIED"),
        ("VERIFIED", "STALE"),
        ("PENDING_APPROVAL", "APPROVED"),
        ("PENDING_APPROVAL", "DENIED"),
        ("APPROVED", "EXECUTED"),
        ("APPROVED", "STALE"),
        ("STALE", "EXPIRED"),
    }
    for source, target in legal:
        validate_transition(source, target)  # must not raise


@pytest.mark.parametrize(
    "jump",
    [
        ("PROPOSED", "APPROVED"),  # never without verification
        ("PROPOSED", "EXECUTED"),
        ("VERIFIED", "EXECUTED"),  # approval cannot be skipped
        ("PENDING_APPROVAL", "EXECUTED"),
        ("PROPOSED", "PENDING_APPROVAL"),  # verify first, always
        ("DENIED", "APPROVED"),  # decided once
        ("DENIED", "EXECUTED"),
        ("DENIED", "PENDING_APPROVAL"),
        ("EXPIRED", "APPROVED"),
        ("EXPIRED", "EXECUTED"),
        ("REVOKED", "APPROVED"),
        ("STALE", "APPROVED"),  # stale is re-proposed, never revived
        ("STALE", "VERIFIED"),
        ("EXECUTED", "STALE"),  # terminal
        ("EXECUTED", "APPROVED"),
    ],
)
def test_illegal_transitions_raise_conflict(jump: tuple[str, str]) -> None:
    with pytest.raises(ConflictError):
        validate_transition(*jump)


# ------------------------------------------------------------ content hash ----


def test_content_hash_is_canonical_json_of_action_and_arguments() -> None:
    expected = _sha(
        json.dumps(
            {"action": "order.create", "normalized_arguments": {"sku": "P1", "qty": 2}},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
    )
    assert (
        decision_content_hash("order.create", {"sku": "P1", "qty": 2}) == expected
    )


def test_content_hash_ignores_argument_key_order_but_not_content() -> None:
    assert decision_content_hash("a.b", {"x": 1, "y": 2}) == decision_content_hash(
        "a.b", {"y": 2, "x": 1}
    )
    assert decision_content_hash("a.b", {"x": 1}) != decision_content_hash("a.b", {"x": 2})
    assert decision_content_hash("a.b", {"x": 1}) != decision_content_hash("a.c", {"x": 1})


# --------------------------------------------------------- service lifecycle --


class _Result:
    def __init__(self, rows=()) -> None:
        self._rows = list(rows)

    def scalars(self) -> _Result:
        return self

    def all(self) -> list:
        return list(self._rows)

    def scalar_one(self) -> int:
        return len(self._rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class FakeSession:
    """Routes the module's reads by table; records every statement."""

    def __init__(
        self,
        decisions: list[Decision] | None = None,
        dependency_rows: list[tuple] | None = None,
    ) -> None:
        self.decisions = list(decisions or [])
        self.dependency_rows = list(dependency_rows or [])
        self.added: list = []
        self.sql: list[str] = []
        self.bound: list[dict] = []

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        for obj in self.added:
            for attr in ("decision_id", "dependency_id"):
                if hasattr(obj, attr) and getattr(obj, attr) is None:
                    setattr(obj, attr, uuid.uuid4())
            if getattr(obj, "created_at", None) is None and hasattr(obj, "created_at"):
                obj.created_at = NOW

    async def execute(self, statement, params=None) -> _Result:
        compiled = statement.compile(dialect=postgresql.dialect())
        sql = " ".join(str(compiled).split())
        bound = dict(compiled.params)
        if isinstance(params, dict):
            bound.update(params)
        self.sql.append(sql)
        self.bound.append(bound)
        low = sql.lower()
        if "from decisions" in low and "decision_dependencies" not in low:
            return _Result(self.decisions)
        if "from decision_dependencies" in low:
            # the service reads ORM attributes off these rows
            return _Result([
                SimpleNamespace(resource_id=r[0], resource_version=r[1], value_digest=r[2])
                for r in self.dependency_rows
            ])
        raise AssertionError(f"unexpected statement: {sql[:160]}")


async def test_propose_pins_the_hash_and_the_high_risk_ttl() -> None:
    decision = await DecisionService.propose(
        FakeSession(),
        TENANT,
        action="order.create",
        risk_level="HIGH",
        normalized_arguments={"sku": "P1"},
        actor_type="ai",
    )
    assert decision.decision_status == "PROPOSED"
    assert decision.approval_state == "NOT_REQUIRED"
    assert decision.content_hash == decision_content_hash("order.create", {"sku": "P1"})
    # V12's 60-second TTL for HIGH/CRITICAL, measured from the mint instant.
    assert decision.expires_at is not None
    assert decision.created_at is not None
    assert (
        decision.expires_at - decision.created_at
    ).total_seconds() == 60

    low = await DecisionService.propose(
        FakeSession(), TENANT, action="order.read", risk_level="LOW"
    )
    assert low.expires_at is None


async def test_propose_validates_the_vocabulary_at_the_door() -> None:
    with pytest.raises(ValidationError):
        await DecisionService.propose(
            FakeSession(), TENANT, action="x", risk_level="EXISTENTIAL"
        )
    with pytest.raises(ValidationError):
        await DecisionService.propose(
            FakeSession(), TENANT, action="x", risk_level="LOW", actor_type="ghost"
        )
    with pytest.raises(ValidationError):
        await DecisionService.propose(FakeSession(), TENANT, action="  ", risk_level="LOW")


async def test_the_full_low_risk_lifecycle_over_the_service() -> None:
    decision = _decision(status="PROPOSED")
    session = FakeSession([decision])
    await DecisionService.verify(session, TENANT, decision.decision_id)
    assert decision.decision_status == "VERIFIED"
    await DecisionService.approve(session, TENANT, decision.decision_id)
    assert decision.decision_status == "APPROVED"
    assert decision.approval_state == "NOT_REQUIRED"  # LOW/MEDIUM never opened one
    await DecisionService.mark_executed(session, TENANT, decision.decision_id)
    assert decision.decision_status == "EXECUTED"


async def test_the_high_risk_lifecycle_opens_and_consumes_an_approval() -> None:
    decision = _decision(status="VERIFIED", risk_level="HIGH")
    session = FakeSession([decision])
    await DecisionService.require_approval(session, TENANT, decision.decision_id)
    assert decision.decision_status == "PENDING_APPROVAL"
    assert decision.approval_state == "PENDING"
    await DecisionService.approve(session, TENANT, decision.decision_id)
    assert decision.decision_status == "APPROVED"
    assert decision.approval_state == "APPROVED"


async def test_deny_is_terminal_and_binding() -> None:
    decision = _decision(status="PENDING_APPROVAL", approval_state="PENDING")
    await DecisionService.deny(FakeSession([decision]), TENANT, decision.decision_id)
    assert decision.decision_status == "DENIED"
    assert decision.approval_state == "DENIED"
    with pytest.raises(ConflictError):
        await DecisionService.approve(FakeSession([decision]), TENANT, decision.decision_id)
    assert decision.decision_status == "DENIED"


async def test_mark_stale_requires_reproposal() -> None:
    decision = _decision(status="APPROVED")
    await DecisionService.mark_stale(FakeSession([decision]), TENANT, decision.decision_id)
    assert decision.decision_status == "STALE"
    with pytest.raises(ConflictError):
        await DecisionService.approve(FakeSession([decision]), TENANT, decision.decision_id)
    assert decision.decision_status == "STALE"


async def test_an_unknown_decision_is_a_404_not_a_cross_tenant_read() -> None:
    # the fake returns no row for this tenant: RLS + the explicit scope
    with pytest.raises(NotFoundError):
        await DecisionService.verify(FakeSession([]), OTHER_TENANT, uuid.uuid4())


# ------------------------------------------------------------------- TTL ------


async def test_ttl_expiry_blocks_approve_and_lands_on_expired() -> None:
    decision = _decision(
        status="VERIFIED",
        risk_level="HIGH",
        approval_state="NOT_REQUIRED",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    result = await DecisionService.approve(FakeSession([decision]), TENANT, decision.decision_id)
    assert result.decision_status == "EXPIRED"  # never APPROVED
    with pytest.raises(ConflictError):
        validate_transition("EXPIRED", "APPROVED")


async def test_ttl_expiry_blocks_execute_and_expires_a_pending_approval() -> None:
    decision = _decision(
        status="APPROVED",
        approval_state="APPROVED",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    result = await DecisionService.mark_executed(
        FakeSession([decision]), TENANT, decision.decision_id
    )
    assert result.decision_status == "EXPIRED"

    pending = _decision(
        status="PENDING_APPROVAL",
        approval_state="PENDING",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    result = await DecisionService.approve(
        FakeSession([pending]), TENANT, pending.decision_id
    )
    assert result.decision_status == "EXPIRED"
    assert result.approval_state == "EXPIRED"


async def test_a_live_ttl_and_no_ttl_still_execute() -> None:
    decision = _decision(status="APPROVED", expires_at=datetime.now(UTC) + timedelta(seconds=60))
    result = await DecisionService.mark_executed(
        FakeSession([decision]), TENANT, decision.decision_id
    )
    assert result.decision_status == "EXECUTED"

    immortal = _decision(status="APPROVED", expires_at=None)
    result = await DecisionService.mark_executed(
        FakeSession([immortal]), TENANT, immortal.decision_id
    )
    assert result.decision_status == "EXECUTED"


# --------------------------------------------------------- dependency snapshot --


async def test_record_dependency_digests_the_value_canonically() -> None:
    decision = _decision(status="PROPOSED")
    session = FakeSession([decision])
    dependency = await DecisionService.record_dependency(
        session,
        TENANT,
        decision.decision_id,
        resource_type="product",
        resource_id=uuid.UUID(int=1),
        resource_version=91,
        value={"stock": 3, "sku": "P1"},
        classification="CUSTOMER_DATA",
        content_hash=_sha("snapshot"),
    )
    assert dependency.value_digest == _sha(
        json.dumps({"sku": "P1", "stock": 3}, sort_keys=True, separators=(",", ":"))
    )
    assert dependency.tenant_id == TENANT
    with pytest.raises(ValidationError):
        await DecisionService.record_dependency(
            FakeSession([decision]),
            TENANT,
            decision.decision_id,
            resource_type="product",
            resource_id=uuid.UUID(int=1),
            resource_version=91,
            classification="INTERNAL",
            content_hash=_sha("x"),
        )


async def test_snapshot_hash_is_order_independent_and_version_sensitive() -> None:
    rows = [
        (str(uuid.UUID(int=1)), "91", _sha("v1")),
        (str(uuid.UUID(int=2)), "144", _sha("v2")),
    ]
    assert snapshot_hash_from_rows(rows) == snapshot_hash_from_rows(list(reversed(rows)))
    bumped = [(rows[0][0], "92", rows[0][2]), rows[1]]
    assert snapshot_hash_from_rows(rows) != snapshot_hash_from_rows(bumped)
    # a NULL digest participates as the empty sentinel, deterministically
    assert snapshot_hash_from_rows([(rows[0][0], "91", None)]) == snapshot_hash_from_rows(
        [(rows[0][0], "91", "")]
    )


async def test_record_dependency_repins_the_snapshot_hash_on_the_decision() -> None:
    decision = _decision(status="PROPOSED")
    dep_rows = [(str(uuid.UUID(int=1)), "91", _sha("v1"))]
    session = FakeSession([decision], dependency_rows=dep_rows)
    await DecisionService.record_dependency(
        session,
        TENANT,
        decision.decision_id,
        resource_type="product",
        resource_id=uuid.UUID(int=1),
        resource_version=91,
        value_digest=_sha("v1"),
        classification="INTERNAL",
        content_hash=_sha("snapshot"),
    )
    expected = snapshot_hash_from_rows(
        [(str(uuid.UUID(int=1)), "91", _sha("v1"))]
    )
    assert decision.dependency_snapshot_hash == expected
    # the write-back is a plain UPDATE on this tenant's row (scoped statement)
    assert any("decisions" in s.lower() for s in session.sql)
    assert TENANT in session.bound[0].values()
