"""DECISIONS service (V12) — the one explicit decision state machine.

Every status change in the system goes through ``_apply_transition``: an
illegal jump is a ``ConflictError``, never a silent write. The transition map
below is the complete law:

    PROPOSED        -> VERIFIED | STALE | EXPIRED
    VERIFIED        -> PENDING_APPROVAL | APPROVED | DENIED | STALE | EXPIRED | REVOKED
    PENDING_APPROVAL-> APPROVED | DENIED | STALE | EXPIRED | REVOKED
    APPROVED        -> EXECUTED | STALE | EXPIRED | REVOKED
    STALE           -> EXPIRED
    DENIED / EXPIRED / REVOKED / EXECUTED  (terminal)

Two guards ride beside the machine:

* **TTL** — a decision past ``expires_at`` may not become APPROVED or
  EXECUTED: the guard redirects the transition to EXPIRED (the approval
  state with it) and the caller gets the EXPIRED decision back. The flip is
  a committed machine transition, not an exception path — raising after
  mutating would roll the EXPIRED state back with the request transaction.
  The world the evidence described is gone; approving against it would be
  authorizing a different decision.
* **§135 binding** — an approval binds to the EXACT decision row: the
  content_hash, evidence_set_hash and dependency_snapshot_hash are pinned at
  propose/verify time and have no update path, so approving
  ``decision_id`` approves that hash triple and nothing else. Wave B adds
  command_hash to the bound triple.

Expiry semantics inside the map: EXPIRED is reachable from every non-terminal
state, so the guard's flip is itself a legal machine transition, not a
side-channel. STALE -> EXPIRED is the one exit a stale decision has: a stale
decision is re-proposed, never revived.

Snapshot hashing: the dependency snapshot hash is sha256 over the sorted
(resource_id + resource_version + value_digest) triples of the decision's
dependency rows — sorted, so recording order does not matter, and sensitive
to any version bump, which is exactly what mark_stale keys on in Wave B.

The canonical-JSON helper here is deliberately duplicated from the evidence
module (3 lines): Wave B moves it to ``core/commands.py`` as the one
``command_hash`` authority, and neither module pays a cross-module edge for a
helper that small in the meantime.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.modules.decisions.models import (
    APPROVAL_STATES,
    DECISION_STATUSES,
    HIGH_RISK_TTL_SECONDS,
    RISK_LEVELS,
    Decision,
    DecisionDependency,
)

#: The one transition law. CURRENT -> allowed targets (module docstring).
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "PROPOSED": frozenset({"VERIFIED", "STALE", "EXPIRED"}),
    "VERIFIED": frozenset(
        {"PENDING_APPROVAL", "APPROVED", "DENIED", "STALE", "EXPIRED", "REVOKED"}
    ),
    "PENDING_APPROVAL": frozenset(
        {"APPROVED", "DENIED", "STALE", "EXPIRED", "REVOKED"}
    ),
    "APPROVED": frozenset({"EXECUTED", "STALE", "EXPIRED", "REVOKED"}),
    "STALE": frozenset({"EXPIRED"}),
    "DENIED": frozenset(),
    "EXPIRED": frozenset(),
    "REVOKED": frozenset(),
    "EXECUTED": frozenset(),
}

#: §66 actor vocabulary — decisions name WHO acted with the same words the
#: audit log uses, so lineage joins stay possible.
ACTOR_TYPES: frozenset[str] = frozenset(
    {"human", "ai", "automation", "system", "integration"}
)


def canonical_json(value: Any) -> str:
    """The one canonical JSON form (Wave B promotes this to core/commands.py)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def decision_content_hash(action: str, normalized_arguments: dict | None) -> str:
    """sha256 over (action + normalized_arguments) in canonical JSON form.

    sort_keys makes argument key order irrelevant; two proposals that differ
    only in dict ordering are the SAME decision, and must hash the same.
    """
    return sha256_hex(
        canonical_json(
            {"action": action, "normalized_arguments": normalized_arguments or {}}
        )
    )


def validate_transition(current: str, target: str) -> None:
    """The machine, as a pure function: illegal jumps raise ConflictError."""
    if target not in ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise ConflictError(
            f"illegal decision transition: {current} -> {target}",
            details={"from": current, "to": target},
        )


def snapshot_hash_from_rows(
    rows: Iterable[tuple[str, str, str | None]],
) -> str:
    """sha256 over sorted (resource_id + resource_version + value_digest).

    ``rows`` are (resource_id, resource_version, value_digest) strings; a
    NULL digest renders as "" so the sort key stays total.
    """
    lines = [
        "|".join((resource_id, resource_version, value_digest or ""))
        for resource_id, resource_version, value_digest in sorted(rows)
    ]
    return sha256_hex("\n".join(lines))


class DecisionService:
    # ------------------------------------------------------------- propose

    @staticmethod
    async def propose(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        action: str,
        risk_level: str,
        normalized_arguments: dict | None = None,
        actor_id: uuid.UUID | None = None,
        actor_type: str | None = None,
        agent_id: uuid.UUID | None = None,
        agent_version_id: uuid.UUID | None = None,
        run_id: uuid.UUID | None = None,
        intent: str | None = None,
        policy_version: int | None = None,
        evidence_set_id: uuid.UUID | None = None,
        evidence_set_hash: str | None = None,
        dependency_snapshot_hash: str | None = None,
        resource_versions: dict | None = None,
        request_id: str | None = None,
        trace_id: str | None = None,
        conversation_id: uuid.UUID | None = None,
        customer_id: uuid.UUID | None = None,
        expires_at: datetime | None = None,
    ) -> Decision:
        """Mint a PROPOSED decision with its computed content_hash."""
        if not isinstance(action, str) or not action.strip():
            raise ValidationError("action must be a non-empty string")
        if risk_level not in RISK_LEVELS:
            raise ValidationError(
                "unknown risk_level",
                details={"risk_level": risk_level, "allowed": sorted(RISK_LEVELS)},
            )
        if actor_type is not None and actor_type not in ACTOR_TYPES:
            raise ValidationError(
                "unknown actor_type",
                details={"actor_type": actor_type, "allowed": sorted(ACTOR_TYPES)},
            )
        now = datetime.now(UTC)
        if expires_at is None and risk_level in {"HIGH", "CRITICAL"}:
            # V12's TTL rule: HIGH/CRITICAL decisions age out in 60 seconds
            # unless the caller pinned an explicit (shorter or longer) window.
            expires_at = now + timedelta(seconds=HIGH_RISK_TTL_SECONDS)
        decision = Decision(
            tenant_id=tenant_id,
            action=action,
            risk_level=risk_level,
            normalized_arguments=normalized_arguments or {},
            content_hash=decision_content_hash(action, normalized_arguments),
            decision_status="PROPOSED",
            approval_state="NOT_REQUIRED",
            actor_id=actor_id,
            actor_type=actor_type,
            agent_id=agent_id,
            agent_version_id=agent_version_id,
            run_id=run_id,
            intent=intent,
            policy_version=policy_version,
            evidence_set_id=evidence_set_id,
            evidence_set_hash=evidence_set_hash,
            dependency_snapshot_hash=dependency_snapshot_hash,
            resource_versions=resource_versions or {},
            request_id=request_id,
            trace_id=trace_id,
            conversation_id=conversation_id,
            customer_id=customer_id,
            created_at=now,
            expires_at=expires_at,
        )
        session.add(decision)
        await session.flush()
        return decision

    # ---------------------------------------------------------------- read

    @staticmethod
    async def get(
        session: AsyncSession, tenant_id: uuid.UUID, decision_id: uuid.UUID
    ) -> Decision:
        decision = (
            await session.execute(
                select(Decision).where(
                    Decision.tenant_id == tenant_id, Decision.decision_id == decision_id
                )
            )
        ).scalar_one_or_none()
        if decision is None:
            raise NotFoundError("decision not found")
        return decision

    # ------------------------------------------------------- state machine

    @staticmethod
    @staticmethod
    def _is_expired(decision: Decision) -> bool:
        """V12 §17: now() past expires_at means the instant of authority is gone."""
        return (
            decision.expires_at is not None
            and datetime.now(UTC) > decision.expires_at
        )

    async def _apply_transition(
        session: AsyncSession,
        decision: Decision,
        target: str,
        *,
        approval_state: str | None = None,
    ) -> Decision:
        """The ONE writer of decision_status/approval_state.

        Expiry is enforced here for the transitions that authorize execution
        (APPROVED, EXECUTED): a past-TTL decision is redirected to EXPIRED —
        a legal machine transition from every non-terminal state — and the
        caller gets the EXPIRED decision back instead of the one it asked
        for. The flip is a committed write, not an exception path: raising
        after mutating would roll the EXPIRED state back with the request
        transaction (get_db commits on success only), leaving a decision
        that looks live but is past its TTL. Every other transition obeys
        the map verbatim.
        """
        current = decision.decision_status
        if current not in DECISION_STATUSES:  # pragma: no cover — DB corrupt
            raise ConflictError(f"decision is in an unknown state: {current}")
        if target in {"APPROVED", "EXECUTED"} and _past_ttl(decision):
            target = "EXPIRED"
            if approval_state == "PENDING":
                approval_state = "EXPIRED"
        validate_transition(decision.decision_status, target)
        decision.decision_status = target
        if approval_state is not None:
            if approval_state not in APPROVAL_STATES:
                raise ValidationError(
                    "unknown approval_state",
                    details={
                        "approval_state": approval_state,
                        "allowed": sorted(APPROVAL_STATES),
                    },
                )
            decision.approval_state = approval_state
        await session.flush()
        return decision

    @staticmethod
    async def verify(
        session: AsyncSession, tenant_id: uuid.UUID, decision_id: uuid.UUID
    ) -> Decision:
        """PROPOSED -> VERIFIED: the evidence/version pins held at check time."""
        decision = await DecisionService.get(session, tenant_id, decision_id)
        return await DecisionService._apply_transition(session, decision, "VERIFIED")

    @staticmethod
    async def require_approval(
        session: AsyncSession, tenant_id: uuid.UUID, decision_id: uuid.UUID
    ) -> Decision:
        """VERIFIED -> PENDING_APPROVAL: §135's durable approval is opened."""
        decision = await DecisionService.get(session, tenant_id, decision_id)
        return await DecisionService._apply_transition(
            session, decision, "PENDING_APPROVAL", approval_state="PENDING"
        )

    @staticmethod
    async def approve(
        session: AsyncSession, tenant_id: uuid.UUID, decision_id: uuid.UUID
    ) -> Decision:
        """-> APPROVED with the §135 binding.

        The binding is structural: the hashes being approved were pinned on
        the row (content_hash at propose, the evidence/snapshot hashes at
        mint time) and have no update path, so this call approves exactly the
        verified proposition. A LOW/MEDIUM decision arrives here VERIFIED
        (approval_state NOT_REQUIRED); a HIGH/CRITICAL one arrives
        PENDING_APPROVAL and its approval_state flips to APPROVED.
        """
        decision = await DecisionService.get(session, tenant_id, decision_id)
        if DecisionService._is_expired(decision):
            # V12 §27: a TTL-expired decision cannot be approved or executed —
            # the only legal exit from an expired instant is EXPIRED itself.
            return await DecisionService._apply_transition(
                session, decision, "EXPIRED", approval_state="EXPIRED"
            )
        approval_state = (
            "APPROVED" if decision.approval_state == "PENDING" else decision.approval_state
        )
        return await DecisionService._apply_transition(
            session, decision, "APPROVED", approval_state=approval_state
        )

    @staticmethod
    async def deny(
        session: AsyncSession, tenant_id: uuid.UUID, decision_id: uuid.UUID
    ) -> Decision:
        """-> DENIED (terminal): decided once; a denied decision is never revived."""
        decision = await DecisionService.get(session, tenant_id, decision_id)
        return await DecisionService._apply_transition(
            session, decision, "DENIED", approval_state="DENIED"
        )

    @staticmethod
    async def mark_stale(
        session: AsyncSession, tenant_id: uuid.UUID, decision_id: uuid.UUID
    ) -> Decision:
        """-> STALE: a dependency moved; the decision must be re-proposed."""
        decision = await DecisionService.get(session, tenant_id, decision_id)
        return await DecisionService._apply_transition(session, decision, "STALE")

    @staticmethod
    async def mark_executed(
        session: AsyncSession, tenant_id: uuid.UUID, decision_id: uuid.UUID
    ) -> Decision:
        """APPROVED -> EXECUTED (terminal): the effect was applied."""
        decision = await DecisionService.get(session, tenant_id, decision_id)
        if DecisionService._is_expired(decision):
            return await DecisionService._apply_transition(session, decision, "EXPIRED")
        return await DecisionService._apply_transition(session, decision, "EXECUTED")

    # ------------------------------------------------------- dependencies

    @staticmethod
    async def record_dependency(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        decision_id: uuid.UUID,
        *,
        resource_type: str,
        resource_id: uuid.UUID,
        resource_version: int,
        value: Any | None = None,
        value_digest: str | None = None,
        source: str | None = None,
        source_version: str | None = None,
        observed_at: datetime | None = None,
        valid_from: datetime | None = None,
        valid_until: datetime | None = None,
        freshness_sla_seconds: int | None = None,
        classification: str,
        content_hash: str,
    ) -> DecisionDependency:
        """Pin one resource version into the decision's dependency snapshot.

        ``value_digest`` is computed from ``value`` (canonical JSON) when a
        value is given; passing neither is a refusal, not a NULL digest. The
        decision's dependency_snapshot_hash is re-derived afterwards, so the
        row always names the snapshot it actually holds.
        """
        if not resource_type.strip():
            raise ValidationError("resource_type must be a non-empty string")
        if not classification.strip():
            raise ValidationError("classification must be a non-empty string")
        if not content_hash.strip():
            raise ValidationError("content_hash must be a non-empty string")
        if value_digest is None and value is None:
            raise ValidationError(
                "record_dependency needs a value (to digest) or a value_digest"
            )
        decision = await DecisionService.get(session, tenant_id, decision_id)
        now = datetime.now(UTC)
        dependency = DecisionDependency(
            tenant_id=tenant_id,
            decision_id=decision.decision_id,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_version=resource_version,
            value_digest=(
                value_digest if value_digest is not None else sha256_hex(canonical_json(value))
            ),
            source=source,
            source_version=source_version,
            observed_at=observed_at if observed_at is not None else now,
            valid_from=valid_from if valid_from is not None else now,
            valid_until=valid_until,
            freshness_sla_seconds=freshness_sla_seconds,
            classification=classification,
            content_hash=content_hash,
        )
        session.add(dependency)
        await session.flush()
        await DecisionService.snapshot_hash(session, tenant_id, decision.decision_id)
        return dependency

    @staticmethod
    async def snapshot_hash(
        session: AsyncSession, tenant_id: uuid.UUID, decision_id: uuid.UUID
    ) -> str:
        """Recompute the dependency snapshot hash and pin it on the decision."""
        decision = await DecisionService.get(session, tenant_id, decision_id)
        rows = (
            await session.execute(
                select(
                    DecisionDependency.resource_id,
                    DecisionDependency.resource_version,
                    DecisionDependency.value_digest,
                ).where(
                    DecisionDependency.tenant_id == tenant_id,
                    DecisionDependency.decision_id == decision_id,
                )
            )
        ).all()
        digest = snapshot_hash_from_rows(
            [(str(r.resource_id), str(r.resource_version), r.value_digest) for r in rows]
        )
        decision.dependency_snapshot_hash = digest
        await session.flush()
        return digest


def _past_ttl(decision: Decision) -> bool:
    """Whether the decision's TTL has elapsed (never true without expires_at)."""
    if decision.expires_at is None:
        return False
    return datetime.now(UTC) > decision.expires_at
