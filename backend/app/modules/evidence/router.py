"""EVIDENCE routes — facts and evidence sets (V12 §9).

Reads use plain ``TenantCtxDep`` (the Decision/Evidence surfaces exist so every
actor can SEE what backs a decision); writes are gated on ``settings:write`` —
the house convention for governance surfaces, because no new permission code
may be invented without a role ever being granted it (an invented code is an
unreachable door).

There are no UPDATE or DELETE routes by design: facts and sets are immutable
history (V12 §9) — a superseded fact is a new row, and a set is never edited
after it is hashed. The only writes are CREATE.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.modules.evidence import schemas
from app.modules.evidence.models import EvidenceFact, EvidenceSet
from app.modules.evidence.service import EvidenceService
from app.modules.identity.deps import TenantContext, TenantCtxDep, require_permission

router = APIRouter(prefix="/evidence", tags=["evidence"])

WriteCtx = Annotated[TenantContext, Depends(require_permission("settings:write"))]

# Query params are declared `Annotated[type, Query(...)] = <value>`, never
# `name: type = Query(...)` — the parameter-declaration rule gated by
# tests/test_route_parameter_declarations.py.
PageLimit = Annotated[int, Query(ge=1, le=schemas.PAGE_LIMIT_MAX)]
PageOffset = Annotated[int, Query(ge=0)]

#: An assembly is a bounded operation: the hash is computed in-process over
#: every member, so the request itself carries the bound.
MAX_SET_FACTS = 100


class FactCreate(BaseModel):
    """Body for ``POST /evidence/facts``."""

    claim: str = Field(min_length=1, max_length=10000)
    source_type: str | None = Field(default=None, max_length=31)
    subject_type: str | None = Field(default=None, max_length=255)
    subject_id: uuid.UUID | None = None
    claim_type: str | None = Field(default=None, max_length=127)
    source: str | None = Field(default=None, max_length=255)
    source_id: str | None = Field(default=None, max_length=255)
    observed_at: datetime | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    source_version: int | None = None
    resource_version: int | None = None
    freshness_sla_seconds: int | None = Field(default=None, ge=0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    provenance: dict = Field(default_factory=dict)
    classification: str = Field(default="INTERNAL", max_length=31)
    trust: str = Field(default="UNVERIFIED", max_length=31)


class SetCreate(BaseModel):
    """Body for ``POST /evidence/sets``."""

    fact_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_SET_FACTS)
    decision_id: uuid.UUID | None = None


def _fact_dict(fact: EvidenceFact) -> dict:
    return {
        "fact_id": fact.fact_id,
        "subject_type": fact.subject_type,
        "subject_id": fact.subject_id,
        "claim": fact.claim,
        "claim_type": fact.claim_type,
        "source": fact.source,
        "source_type": fact.source_type,
        "source_id": fact.source_id,
        "observed_at": fact.observed_at,
        "valid_from": fact.valid_from,
        "valid_until": fact.valid_until,
        "source_version": fact.source_version,
        "resource_version": fact.resource_version,
        "freshness_sla_seconds": fact.freshness_sla_seconds,
        "confidence": fact.confidence,
        "provenance": fact.provenance or {},
        "classification": fact.classification,
        "content_hash": fact.content_hash,
        "trust": fact.trust,
        "created_at": fact.created_at,
    }


@router.post("/facts", response_model=schemas.FactOut, status_code=201)
async def create_fact(ctx: WriteCtx, body: FactCreate):
    """Record one immutable evidence fact; the content_hash is computed here."""
    fact = await EvidenceService.create_fact(
        ctx.session,
        ctx.tenant_id,
        claim=body.claim,
        source_type=body.source_type,
        subject_type=body.subject_type,
        subject_id=body.subject_id,
        claim_type=body.claim_type,
        source=body.source,
        source_id=body.source_id,
        observed_at=body.observed_at,
        valid_from=body.valid_from,
        valid_until=body.valid_until,
        source_version=body.source_version,
        resource_version=body.resource_version,
        freshness_sla_seconds=body.freshness_sla_seconds,
        confidence=body.confidence,
        provenance=body.provenance,
        classification=body.classification,
        trust=body.trust,
    )
    return _fact_dict(fact)


@router.get("/facts", response_model=schemas.FactListOut)
async def list_facts(
    ctx: TenantCtxDep,
    subject_type: Annotated[str | None, Query(max_length=255)] = None,
    subject_id: uuid.UUID | None = None,
    content_hash: Annotated[str | None, Query(max_length=64)] = None,
    limit: PageLimit = schemas.PAGE_LIMIT_DEFAULT,
    offset: PageOffset = 0,
):
    """This tenant's facts, newest first, paged with a total."""
    conditions = [EvidenceFact.tenant_id == ctx.tenant_id]
    if subject_type is not None:
        conditions.append(EvidenceFact.subject_type == subject_type)
    if subject_id is not None:
        conditions.append(EvidenceFact.subject_id == subject_id)
    if content_hash is not None:
        conditions.append(EvidenceFact.content_hash == content_hash)
    total = (
        await ctx.session.execute(select(func.count(EvidenceFact.fact_id)).where(*conditions))
    ).scalar_one()
    rows = await ctx.session.execute(
        select(EvidenceFact)
        .where(*conditions)
        # created_at shares one now() across a transaction; fact_id is the
        # tie-break that makes the ORDER a total order (house rule).
        .order_by(EvidenceFact.created_at.desc(), EvidenceFact.fact_id.desc())
        .limit(limit)
        .offset(offset)
    )
    return {
        "items": [_fact_dict(fact) for fact in rows.scalars().all()],
        "total": int(total),
        "limit": limit,
        "offset": offset,
    }


@router.get("/facts/{fact_id}", response_model=schemas.FactOut)
async def get_fact(ctx: TenantCtxDep, fact_id: uuid.UUID):
    """One fact — another tenant's id is a 404, never a 403 (the id is not a permission)."""
    fact = await EvidenceService.get_fact(ctx.session, ctx.tenant_id, fact_id)
    return _fact_dict(fact)


@router.post("/sets", response_model=schemas.SetOut, status_code=201)
async def assemble_set(ctx: WriteCtx, body: SetCreate):
    """Assemble an immutable evidence set from this tenant's facts and hash it.

    Same-source repeats collapse for the hash; stale facts are admitted and
    flagged in the returned provenance.
    """
    assembled = await EvidenceService.assemble_evidence_set(
        ctx.session, ctx.tenant_id, body.fact_ids, decision_id=body.decision_id
    )
    row = assembled.evidence_set
    return {
        "evidence_set_id": row.evidence_set_id,
        "fact_ids": row.fact_ids,
        "fact_count": row.fact_count,
        "evidence_set_hash": row.evidence_set_hash,
        "decision_id": row.decision_id,
        "provenance": assembled.provenance,
        "created_at": row.created_at,
    }


@router.get("/sets", response_model=schemas.SetListOut)
async def list_sets(
    ctx: TenantCtxDep,
    limit: PageLimit = schemas.PAGE_LIMIT_DEFAULT,
    offset: PageOffset = 0,
):
    """This tenant's assembled sets, newest first, paged."""
    conditions = [EvidenceSet.tenant_id == ctx.tenant_id]
    total = (
        await ctx.session.execute(
            select(func.count(EvidenceSet.evidence_set_id)).where(*conditions)
        )
    ).scalar_one()
    rows = await ctx.session.execute(
        select(EvidenceSet)
        .where(*conditions)
        .order_by(EvidenceSet.created_at.desc(), EvidenceSet.evidence_set_id.desc())
        .limit(limit)
        .offset(offset)
    )
    return {
        "items": [
            {
                "evidence_set_id": row.evidence_set_id,
                "fact_ids": row.fact_ids,
                "fact_count": row.fact_count,
                "evidence_set_hash": row.evidence_set_hash,
                "decision_id": row.decision_id,
                "provenance": {},  # flags are per-assembly; fetch one set for them
                "created_at": row.created_at,
            }
            for row in rows.scalars().all()
        ],
        "total": int(total),
        "limit": limit,
        "offset": offset,
    }


@router.get("/sets/{evidence_set_id}", response_model=schemas.SetOut)
async def get_set(ctx: TenantCtxDep, evidence_set_id: uuid.UUID):
    """One set with its staleness provenance re-derived from the facts."""
    assembled = await EvidenceService.get_evidence_set(ctx.session, ctx.tenant_id, evidence_set_id)
    row = assembled.evidence_set
    return {
        "evidence_set_id": row.evidence_set_id,
        "fact_ids": row.fact_ids,
        "fact_count": row.fact_count,
        "evidence_set_hash": row.evidence_set_hash,
        "decision_id": row.decision_id,
        "provenance": assembled.provenance,
        "created_at": row.created_at,
    }
