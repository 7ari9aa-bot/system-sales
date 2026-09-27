"""EVIDENCE hashes — the V12 §9 invariants, unit-tested with no database.

What is pinned here:

* ``content_hash`` is sha256 of the claim content and is COMPUTED, never
  accepted from the caller.
* The evidence-set hash is deterministic: the same facts in ANY order produce
  the same hash, and a changed resource_version changes it.
* A repeated claim from the SAME source collapses to ONE effective fact for
  the hash — repeated single-source claims are not independent confirmation —
  while the same content from a DIFFERENT source still counts on its own.
* Stale facts (freshness SLA breached or ``valid_until`` elapsed) are allowed
  into a set but flagged in the assembly provenance.

The service-level tests drive ``EvidenceService`` over a scripted fake session
(the house pattern from test_automation_routes.py): SQL is captured and
routed by table, so the tenant scoping of the reads is asserted on the
compiled statements, not on a live database.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.dialects import postgresql

from app.core.errors import NotFoundError, ValidationError
from app.modules.evidence.models import EvidenceFact
from app.modules.evidence.service import (
    EvidenceService,
    canonical_json,
    compute_content_hash,
    dedupe_triples,
    evidence_set_hash_from_triples,
    fact_staleness,
)

TENANT = uuid.UUID("22222222-2222-2222-2222-222222222222")
OTHER_TENANT = uuid.UUID("99999999-9999-9999-9999-999999999999")
NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fact(
    *,
    fact_id: uuid.UUID | None = None,
    claim: str = "product P1 costs 100",
    source: str | None = "crm",
    observed_at: datetime | None = NOW,
    freshness_sla_seconds: int | None = None,
    valid_until: datetime | None = None,
) -> EvidenceFact:
    return EvidenceFact(
        fact_id=fact_id or uuid.uuid4(),
        tenant_id=TENANT,
        claim=claim,
        content_hash=compute_content_hash(claim),
        source=source,
        source_type="SERVICE",
        observed_at=observed_at,
        resource_version=7,
        freshness_sla_seconds=freshness_sla_seconds,
        valid_until=valid_until,
        classification="INTERNAL",
        trust="OBSERVED",
        created_at=NOW,
    )


# ------------------------------------------------------- content hash --------


def test_content_hash_is_sha256_of_the_claim_text() -> None:
    assert compute_content_hash("stock=3") == _sha("stock=3")


def test_content_hash_is_deterministic_and_discriminating() -> None:
    assert compute_content_hash("same claim") == compute_content_hash("same claim")
    assert compute_content_hash("same claim") != compute_content_hash("same claim ")


async def test_create_fact_computes_content_hash_and_never_accepts_one() -> None:
    fact = await EvidenceService.create_fact(
        FakeSession(), TENANT, claim="invoice INV-1 total 150.00", source_type="DATABASE"
    )
    assert fact.content_hash == _sha("invoice INV-1 total 150.00")
    assert fact.tenant_id == TENANT
    # observed_at defaults to a real instant: unageable evidence is how a
    # stale claim sneaks past a freshness check.
    assert fact.observed_at is not None


async def test_create_fact_enforces_the_v12_vocabularies() -> None:
    with pytest.raises(ValidationError):
        await EvidenceService.create_fact(
            FakeSession(), TENANT, claim="x", trust="HEARSAY"
        )
    with pytest.raises(ValidationError):
        await EvidenceService.create_fact(
            FakeSession(), TENANT, claim="x", source_type="GOSSIP"
        )
    with pytest.raises(ValidationError):
        await EvidenceService.create_fact(
            FakeSession(), TENANT, claim="x", classification="TOP_SECRET"
        )
    with pytest.raises(ValidationError):
        await EvidenceService.create_fact(
            FakeSession(), TENANT, claim="x", confidence=1.5
        )
    with pytest.raises(ValidationError):
        await EvidenceService.create_fact(FakeSession(), TENANT, claim="   ")
    # the legal extremes pass
    await EvidenceService.create_fact(
        FakeSession(), TENANT, claim="x", trust="SYSTEM_ASSERTED", confidence=0.0
    )


# --------------------------------------------------------- pure hashing ------


def test_set_hash_is_order_independent() -> None:
    triples = [(str(uuid.UUID(int=i)), _sha(f"c{i}"), str(i)) for i in range(1, 6)]
    forward = evidence_set_hash_from_triples(triples)
    backward = evidence_set_hash_from_triples(list(reversed(triples)))
    shuffled = evidence_set_hash_from_triples([triples[i] for i in (2, 0, 4, 1, 3)])
    assert forward == backward == shuffled


def test_set_hash_changes_when_a_resource_version_changes() -> None:
    triples = [(str(uuid.UUID(int=i)), _sha(f"c{i}"), str(i)) for i in range(1, 4)]
    bumped = [triples[0], (triples[1][0], triples[1][1], "99"), triples[2]]
    assert evidence_set_hash_from_triples(triples) != evidence_set_hash_from_triples(
        bumped
    )


def test_same_source_repeats_collapse_but_other_sources_do_not() -> None:
    claim_hash = _sha("same claim")
    other_claim_hash = _sha("another claim")
    # (source_key, content_hash, fact_id, resource_version) entries:
    entries = [
        ("crm", claim_hash, str(uuid.UUID(int=1)), "7"),
        ("crm", claim_hash, str(uuid.UUID(int=2)), "7"),  # repeat, same source
        ("billing", claim_hash, str(uuid.UUID(int=3)), "7"),  # independent source
        ("crm", other_claim_hash, str(uuid.UUID(int=4)), "9"),  # different claim
    ]
    collapsed = dedupe_triples(entries)
    assert len(collapsed) == 3
    kept_ids = {t[0] for t in collapsed}
    assert str(uuid.UUID(int=1)) in kept_ids  # the LOWEST fact_id represents
    assert str(uuid.UUID(int=2)) not in kept_ids  # the repeat is gone
    assert str(uuid.UUID(int=3)) in kept_ids  # a different source is independent
    assert str(uuid.UUID(int=4)) in kept_ids  # a different claim is independent
    # and the collapse does not depend on the input order
    assert collapsed == dedupe_triples(list(reversed(entries)))


def test_set_hash_of_collapsed_set_uses_the_representative_triple() -> None:
    claim_hash = _sha("same claim")
    kept = str(uuid.UUID(int=1))
    dropped = str(uuid.UUID(int=2))
    # hashing [kept, dropped] equals hashing [kept] alone: the repeat added
    # zero confirmation to the set.
    assert (
        evidence_set_hash_from_triples(
            dedupe_triples(
                [("s", claim_hash, kept, "7"), ("s", claim_hash, dropped, "7")]
            )
        )
        == evidence_set_hash_from_triples([(kept, claim_hash, "7")])
    )


def test_canonical_json_matches_the_house_form() -> None:
    assert canonical_json({"b": 1, "a": "é"}) == '{"a":"é","b":1}'


# ------------------------------------------------------------ staleness ------


def test_stale_fact_is_flagged_not_rejected() -> None:
    fresh = _fact(freshness_sla_seconds=60)
    assert fact_staleness(fresh, NOW + timedelta(seconds=30)) == []

    sla_breached = _fact(freshness_sla_seconds=60)
    assert fact_staleness(sla_breached, NOW + timedelta(seconds=61)) == [
        "freshness_sla_breached"
    ]

    expired = _fact(valid_until=NOW - timedelta(seconds=1))
    assert "valid_until_elapsed" in fact_staleness(expired, NOW)


# ------------------------------------------------- service over fake session --


class FakeSession:
    """Routes the module's reads by table; records every statement."""

    def __init__(self, facts: list[EvidenceFact] | None = None) -> None:
        self.facts = list(facts or [])
        self.added: list = []
        self.sql: list[str] = []
        self.bound: list[dict] = []

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        for obj in self.added:
            for attr in ("fact_id", "evidence_set_id"):
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
        if "from evidence_facts" in sql.lower():
            return _Result(self.facts)
        if "from evidence_sets" in sql.lower():
            return _Result(self.added)
        raise AssertionError(f"unexpected statement: {sql[:160]}")


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


async def test_assembly_hashes_the_effective_facts_and_scopes_the_read() -> None:
    a = _fact(claim="same claim")
    a_repeat = _fact(claim="same claim")  # same source, same content -> collapses
    b = _fact(claim="different claim", source="billing")
    session = FakeSession([a, a_repeat, b])

    assembled = await EvidenceService.assemble_evidence_set(
        session, TENANT, [a.fact_id, a_repeat.fact_id, b.fact_id], now=NOW
    )
    row = assembled.evidence_set
    assert row.tenant_id == TENANT
    assert row.fact_count == 3  # three rows went in...
    assert assembled.provenance["effective_fact_count"] == 2  # ...two counted
    representative = min(a.fact_id, a_repeat.fact_id)
    expected = evidence_set_hash_from_triples(
        [
            (str(representative), a.content_hash, "7"),
            (str(b.fact_id), b.content_hash, "7"),
        ]
    )
    assert row.evidence_set_hash == expected
    # the read is tenant-scoped IN THE STATEMENT, not only by the fake's answer
    scope_sql = next(s for s in session.sql if "from evidence_facts" in s.lower())
    assert "evidence_facts.tenant_id =" in scope_sql
    assert TENANT in session.bound[session.sql.index(scope_sql)].values()


async def test_assembly_is_order_independent_and_stores_sorted_ids() -> None:
    a, b, c = _fact(claim="1"), _fact(claim="2"), _fact(claim="3")
    ids = [a.fact_id, b.fact_id, c.fact_id]
    one = await EvidenceService.assemble_evidence_set(
        FakeSession([a, b, c]), TENANT, ids, now=NOW
    )
    two = await EvidenceService.assemble_evidence_set(
        FakeSession([a, b, c]), TENANT, list(reversed(ids)), now=NOW
    )
    assert one.evidence_set.evidence_set_hash == two.evidence_set.evidence_set_hash
    assert one.evidence_set.fact_ids == sorted(ids)


async def test_assembly_flags_stale_members_in_provenance() -> None:
    fresh = _fact(claim="fresh", freshness_sla_seconds=3600)
    stale = _fact(
        claim="stale",
        freshness_sla_seconds=10,
        observed_at=NOW - timedelta(hours=2),
    )
    assembled = await EvidenceService.assemble_evidence_set(
        FakeSession([fresh, stale]), TENANT, [fresh.fact_id, stale.fact_id], now=NOW
    )
    flagged = assembled.provenance["stale"]
    assert [entry["fact_id"] for entry in flagged] == [str(stale.fact_id)]
    assert flagged[0]["reasons"] == ["freshness_sla_breached"]


async def test_assembly_refuses_facts_that_are_not_the_tenant_s() -> None:
    a = _fact()
    # the fake simulates RLS + the explicit scope: another tenant's facts
    # never come back, so the assembly refuses instead of silently shrinking.
    with pytest.raises(NotFoundError) as exc:
        await EvidenceService.assemble_evidence_set(
            FakeSession([]), OTHER_TENANT, [a.fact_id], now=NOW
        )
    assert exc.value.details["missing_fact_ids"] == [str(a.fact_id)]


async def test_assembly_refuses_an_empty_fact_list() -> None:
    with pytest.raises(ValidationError):
        await EvidenceService.assemble_evidence_set(FakeSession(), TENANT, [], now=NOW)
