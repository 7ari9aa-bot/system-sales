"""Analysis persistence (spec §12.4/§15) — save once, read forever.

``save_analysis`` writes the immutable evidence snapshot plus its graded
findings in the caller's transaction. ``load_analysis`` returns them as
plain dicts for the GET route. The pack is stored EXACTLY as hashed: the
content_hash in the row is the proof that what was published is what is
stored.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.analytics.contracts import EvidencePack, Finding
from app.modules.analytics.models import AnalysisEvidence, AnalysisFinding


async def save_analysis(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    question: str,
    outcome: str,
    pack: EvidencePack,
    findings: list[Finding],
    run_id: uuid.UUID | None = None,
    model: str | None = None,
    prompt_version: str | None = None,
) -> uuid.UUID:
    """Persist one published analysis; returns the evidence id."""
    pack_dict = pack.model_dump(mode="json")
    content_hash = pack.content_hash or hashlib.sha256(
        json.dumps(pack_dict, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    row = AnalysisEvidence(
        tenant_id=tenant_id,
        run_id=run_id,
        question=question,
        outcome=outcome,
        pack=pack_dict,
        content_hash=content_hash,
        model=model,
        prompt_version=prompt_version,
    )
    session.add(row)
    await session.flush()
    for finding in findings:
        session.add(
            AnalysisFinding(
                tenant_id=tenant_id,
                evidence_id=row.id,
                statement=finding.statement,
                finding_type=finding.type,
                relationship=finding.relationship.value,
                confidence=finding.confidence,
                confidence_reasons=finding.confidence_reasons,
                materiality=Decimal(str(finding.materiality)),
                evidence_refs=finding.evidence_refs,
            )
        )
    await session.flush()
    return row.id


async def load_analysis(
    session: AsyncSession, tenant_id: uuid.UUID, analysis_id: uuid.UUID
) -> dict | None:
    """The stored analysis (pack + findings), or None when absent/foreign."""
    row = (
        await session.execute(
            select(AnalysisEvidence).where(
                AnalysisEvidence.tenant_id == tenant_id,
                AnalysisEvidence.id == analysis_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    finding_rows = (
        await session.execute(
            select(AnalysisFinding).where(
                AnalysisFinding.tenant_id == tenant_id,
                AnalysisFinding.evidence_id == row.id,
            )
        )
    ).scalars().all()
    return {
        "analysis_id": str(row.id),
        "run_id": str(row.run_id) if row.run_id else None,
        "question": row.question,
        "outcome": row.outcome,
        "content_hash": row.content_hash,
        "model": row.model,
        "prompt_version": row.prompt_version,
        "created_at": row.created_at.isoformat(),
        "pack": row.pack,
        "findings": [
            {
                "statement": f.statement,
                "type": f.finding_type,
                "relationship": f.relationship,
                "confidence": f.confidence,
                "confidence_reasons": f.confidence_reasons,
                "evidence_refs": f.evidence_refs,
                "materiality": str(f.materiality),
            }
            for f in finding_rows
        ],
    }
