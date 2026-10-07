"""EVIDENCE service (V12 §9) — facts, deterministic set assembly, freshness.

Two invariants carry the whole module:

1. **Hashes are computed, never accepted.** ``content_hash`` is sha256 of the
   claim content and ``evidence_set_hash`` is sha256 over the sorted
   (fact_id + content_hash + resource_version) triples — sorted, so the same
   facts in any order produce the same set, and an edit to any member is
   detectable by re-hashing.

2. **A repeated claim from one source is not confirmation.** Within one
   assembly, facts are deduplicated by ``(source, content_hash)``: the same
   source repeating the same claim contributes ONE effective fact to the hash
   (the representative is the lowest fact_id, so the collapse is deterministic
   and order-independent). A DIFFERENT source carrying the same content_hash
   is still independent — the dedup key is the pair, not the hash alone.

Staleness is a flag, not a rejection: a fact past its ``freshness_sla_seconds``
or its ``valid_until`` may still enter a set (the operator decides), but the
assembly result names it in ``provenance`` so no consumer can mistake a stale
set for a fresh one. Flags are DERIVED per assembly — facts are immutable, so
re-deriving is exact and nothing stale-flagged has to be persisted twice.

The canonical-JSON helper here is deliberately duplicated from the decisions
module (3 lines): Wave B moves it to ``core/commands.py`` as the one
``command_hash`` authority, and neither module pays a cross-module edge for a
helper that small in the meantime.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.modules.evidence.models import (
    CLASSIFICATIONS,
    SOURCE_TYPES,
    TRUST_LEVELS,
    EvidenceFact,
    EvidenceSet,
)


def canonical_json(value: Any) -> str:
    """The one canonical JSON form (Wave B promotes this to core/commands.py)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_content_hash(claim: str) -> str:
    """sha256 of the claim content (utf-8 bytes of the exact text)."""
    return sha256_hex(claim)


# --- pure assembly helpers (unit-tested without a DB) -----------------------
#
# A triple is (fact_id, content_hash, resource_version) with resource_version
# rendered as "" when absent; the dedup key is (source_key, content_hash) with
# a missing source rendered as "". Sentinels are safe: fact_id is a uuid string
# (hex + hyphens) and content_hash is hex — neither contains "|" or ":".

_TRIPLE_SEP = "|"
_LINE_SEP = "\n"


def fact_triple(fact: EvidenceFact) -> tuple[str, str, str]:
    return (
        str(fact.fact_id),
        fact.content_hash,
        "" if fact.resource_version is None else str(fact.resource_version),
    )


def dedupe_triples(
    entries: Iterable[tuple[str, str, str, str]],
) -> list[tuple[str, str, str]]:
    """Collapse same-(source, content_hash) repeats to one effective triple.

    ``entries`` are (source_key, content_hash, fact_id, resource_version).
    The representative of a duplicate group is the lowest fact_id, so the
    result — and therefore the set hash — does not depend on input order.
    """
    by_key: dict[tuple[str, str], tuple[str, str, str]] = {}
    for source_key, content_hash, fact_id, resource_version in entries:
        key = (source_key, content_hash)
        candidate = (fact_id, content_hash, resource_version)
        current = by_key.get(key)
        if current is None or candidate[0] < current[0]:
            by_key[key] = candidate
    return sorted(by_key.values())


def evidence_set_hash_from_triples(triples: Iterable[tuple[str, str, str]]) -> str:
    """sha256 over the sorted (fact_id + content_hash + resource_version) lines."""
    lines = [_TRIPLE_SEP.join(triple) for triple in sorted(triples)]
    return sha256_hex(_LINE_SEP.join(lines))


def fact_staleness(fact: EvidenceFact, now: datetime) -> list[str]:
    """Why this fact is stale right now — empty list means fresh-enough."""
    reasons: list[str] = []
    if (
        fact.freshness_sla_seconds is not None
        and fact.observed_at is not None
        and now > fact.observed_at + timedelta(seconds=fact.freshness_sla_seconds)
    ):
        reasons.append("freshness_sla_breached")
    if fact.valid_until is not None and now > fact.valid_until:
        reasons.append("valid_until_elapsed")
    return reasons


@dataclass(slots=True)
class AssembledSet:
    """The set row plus the assembly-time provenance (staleness flags)."""

    evidence_set: EvidenceSet
    provenance: dict = field(default_factory=dict)


class EvidenceService:
    # ---------------------------------------------------------------- facts

    @staticmethod
    async def create_fact(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        claim: str,
        source_type: str | None = None,
        subject_type: str | None = None,
        subject_id: uuid.UUID | None = None,
        claim_type: str | None = None,
        source: str | None = None,
        source_id: str | None = None,
        observed_at: datetime | None = None,
        valid_from: datetime | None = None,
        valid_until: datetime | None = None,
        source_version: int | None = None,
        resource_version: int | None = None,
        freshness_sla_seconds: int | None = None,
        confidence: float | None = None,
        provenance: dict | None = None,
        classification: str = "INTERNAL",
        trust: str = "UNVERIFIED",
    ) -> EvidenceFact:
        """Insert one immutable fact with its computed content_hash.

        ``observed_at`` defaults to now: a fact with no observation instant is
        unageable, and unageable evidence is exactly how a stale claim sneaks
        past a freshness check. Callers with a real observation pass it.
        """
        if not isinstance(claim, str) or not claim.strip():
            raise ValidationError("claim must be a non-empty string")
        if source_type is not None and source_type not in SOURCE_TYPES:
            raise ValidationError(
                "unknown source_type",
                details={"source_type": source_type, "allowed": sorted(SOURCE_TYPES)},
            )
        if classification not in CLASSIFICATIONS:
            raise ValidationError(
                "unknown classification",
                details={"classification": classification, "allowed": sorted(CLASSIFICATIONS)},
            )
        if trust not in TRUST_LEVELS:
            raise ValidationError(
                "unknown trust value",
                details={"trust": trust, "allowed": sorted(TRUST_LEVELS)},
            )
        if confidence is not None and not 0.0 <= confidence <= 1.0:
            raise ValidationError("confidence must be between 0.0 and 1.0")

        fact = EvidenceFact(
            tenant_id=tenant_id,
            claim=claim,
            content_hash=compute_content_hash(claim),
            subject_type=subject_type,
            subject_id=subject_id,
            claim_type=claim_type,
            source=source,
            source_type=source_type,
            source_id=source_id,
            observed_at=observed_at if observed_at is not None else datetime.now(UTC),
            valid_from=valid_from,
            valid_until=valid_until,
            source_version=source_version,
            resource_version=resource_version,
            freshness_sla_seconds=freshness_sla_seconds,
            confidence=confidence,
            provenance=provenance or {},
            classification=classification,
            trust=trust,
        )
        session.add(fact)
        await session.flush()
        return fact

    @staticmethod
    async def get_fact(
        session: AsyncSession, tenant_id: uuid.UUID, fact_id: uuid.UUID
    ) -> EvidenceFact:
        fact = (
            await session.execute(
                select(EvidenceFact).where(
                    EvidenceFact.tenant_id == tenant_id, EvidenceFact.fact_id == fact_id
                )
            )
        ).scalar_one_or_none()
        if fact is None:
            raise NotFoundError("evidence fact not found")
        return fact

    # ---------------------------------------------------------------- sets

    @staticmethod
    async def assemble_evidence_set(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        fact_ids: list[uuid.UUID],
        *,
        now: datetime | None = None,
        decision_id: uuid.UUID | None = None,
    ) -> AssembledSet:
        """Assemble an immutable set from the given facts and hash it.

        All facts must belong to the tenant (the query is tenant-scoped AND the
        missing ones are named — a set must never silently contain less than
        the caller asked for). Stale facts are admitted and flagged. Same-source
        repeats collapse for the hash (module docstring, invariant 2).
        """
        unique_ids = sorted(set(fact_ids))
        if not unique_ids:
            raise ValidationError("an evidence set needs at least one fact")

        rows = (
            (
                await session.execute(
                    select(EvidenceFact).where(
                        EvidenceFact.tenant_id == tenant_id,
                        EvidenceFact.fact_id.in_(unique_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        found = {row.fact_id: row for row in rows}
        missing = [str(fid) for fid in unique_ids if fid not in found]
        if missing:
            raise NotFoundError(
                "evidence fact(s) not found for this tenant",
                details={"missing_fact_ids": missing},
            )

        current = now if now is not None else datetime.now(UTC)
        stale: list[dict] = []
        entries: list[tuple[str, str, str, str]] = []
        for fid in unique_ids:
            fact = found[fid]
            reasons = fact_staleness(fact, current)
            if reasons:
                stale.append({"fact_id": str(fid), "reasons": reasons})
            entries.append(
                (
                    fact.source or "",
                    fact.content_hash,
                    str(fid),
                    "" if fact.resource_version is None else str(fact.resource_version),
                )
            )

        effective = dedupe_triples(entries)
        evidence_set = EvidenceSet(
            tenant_id=tenant_id,
            fact_ids=unique_ids,
            fact_count=len(unique_ids),
            evidence_set_hash=evidence_set_hash_from_triples(effective),
            decision_id=decision_id,
        )
        session.add(evidence_set)
        await session.flush()
        return AssembledSet(
            evidence_set=evidence_set,
            provenance={
                "fact_count": len(unique_ids),
                "effective_fact_count": len(effective),
                "stale": stale,
                "computed_at": current.isoformat(),
            },
        )

    @staticmethod
    async def get_evidence_set(
        session: AsyncSession, tenant_id: uuid.UUID, evidence_set_id: uuid.UUID
    ) -> AssembledSet:
        """Load one set and re-derive its provenance from the immutable facts.

        Re-deriving is exact (facts never change) and is what makes the
        staleness report trustworthy years later: it reflects the facts, not a
        snapshot taken at assembly time.
        """
        evidence_set = (
            await session.execute(
                select(EvidenceSet).where(
                    EvidenceSet.tenant_id == tenant_id,
                    EvidenceSet.evidence_set_id == evidence_set_id,
                )
            )
        ).scalar_one_or_none()
        if evidence_set is None:
            raise NotFoundError("evidence set not found")

        rows = (
            (
                await session.execute(
                    select(EvidenceFact).where(
                        EvidenceFact.tenant_id == tenant_id,
                        EvidenceFact.fact_id.in_(evidence_set.fact_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        current = datetime.now(UTC)
        stale = [
            {"fact_id": str(row.fact_id), "reasons": reasons}
            for row in rows
            if (reasons := fact_staleness(row, current))
        ]
        effective = dedupe_triples(
            [
                (
                    row.source or "",
                    row.content_hash,
                    str(row.fact_id),
                    "" if row.resource_version is None else str(row.resource_version),
                )
                for row in rows
            ]
        )
        return AssembledSet(
            evidence_set=evidence_set,
            provenance={
                "fact_count": len(evidence_set.fact_ids),
                "effective_fact_count": len(effective),
                "stale": stale,
                "computed_at": current.isoformat(),
            },
        )
