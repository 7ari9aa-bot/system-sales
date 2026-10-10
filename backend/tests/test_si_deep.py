"""Deep analysis tests (spec §13) — queue → handler → persisted outcome.

The deep path is the durable half of the SI agent: the API stages a shell
(question) + a Job; the handler runs the full interactive pipeline with the
strong model and finalizes the shell. The model is mocked — the JOB
machinery (shell finalization, result write, cancel-wins) is what's tested.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.errors import ExternalProviderError
from app.modules.ai.agents.sales_intelligence.agent import AnalysisResult
from app.modules.ai.models import Agent
from app.modules.analytics.contracts import Outcome
from app.modules.analytics.persistence import load_analysis
from app.modules.platform.models import Job
from app.modules.platform.service import JobService
from app.workers.job_runner import get_job_handler


async def _stage(db, tenant_ctx, question="ليه المبيعات قلت؟"):
    db.add(
        Agent(
            tenant_id=tenant_ctx.tenant_id,
            kind="sales_intelligence",
            name="SI Agent",
            model="strong",
            system_prompt="analyze",
        )
    )
    await db.flush()
    from app.modules.analytics.persistence import create_pending_analysis

    analysis_id = await create_pending_analysis(db, tenant_ctx.tenant_id, question=question)
    job = await JobService.create(
        db,
        tenant_ctx.tenant_id,
        kind="si.deep_analysis",
        actor_user_id=tenant_ctx.user.id,
        correlation_id=str(analysis_id),
    )
    await db.flush()
    return analysis_id, job


def _fake_result(answer: str) -> AnalysisResult:
    return AnalysisResult(
        outcome=Outcome.ANSWERED,
        answer=answer,
        findings=[],
        facts=[],
        evidence_hash="a" * 64,
        saved_evidence_id=uuid.uuid4(),
    )


async def test_handler_runs_the_analysis_and_finalizes_the_shell(db, tenant_ctx, monkeypatch):
    analysis_id, job = await _stage(db, tenant_ctx)

    async def fake_run(session, tenant_id, **kwargs):
        return AnalysisResult(
            outcome=Outcome.ANSWERED,
            answer="الإيراد انخفض بسبب نفاد المخزون",
            findings=[],
            facts=[{"value": "1200"}],
            saved_evidence_id=uuid.uuid4(),
        )

    monkeypatch.setattr(
        "app.modules.ai.agents.sales_intelligence.agent.run_sales_analysis", fake_run
    )
    handler = get_job_handler("si.deep_analysis")
    assert handler is not None
    summary = await handler(db, job)

    stored = await load_analysis(db, tenant_ctx.tenant_id, analysis_id)
    assert stored["outcome"] == "ANSWERED"
    assert stored["model"] == "strong"
    assert summary["outcome"] == "ANSWERED"


async def test_handler_failure_marks_the_shell_failed(db, tenant_ctx, monkeypatch):
    db.add(
        Agent(
            tenant_id=tenant_ctx.tenant_id,
            kind="sales_intelligence",
            name="SI Agent",
            model="strong",
            system_prompt="analyze",
        )
    )
    await db.flush()
    from app.modules.analytics.persistence import create_pending_analysis

    analysis_id = await create_pending_analysis(db, tenant_ctx.tenant_id, question="سؤال")

    async def fake_run(session, tenant_id, **kwargs):
        raise ExternalProviderError("provider down")

    monkeypatch.setattr(
        "app.modules.ai.agents.sales_intelligence.agent.run_sales_analysis", fake_run
    )
    handler = get_job_handler("si.deep_analysis")
    job = Job(
        tenant_id=tenant_ctx.tenant_id,
        kind="si.deep_analysis",
        correlation_id=str(analysis_id),
    )
    db.add(job)
    await db.flush()
    summary = await handler(db, job)
    assert summary["outcome"] == "FAILED"
    stored = await load_analysis(db, tenant_ctx.tenant_id, analysis_id)
    assert stored["outcome"] == "FAILED"


async def test_unknown_shell_fails_the_job(db, tenant_ctx):
    job = Job(
        tenant_id=tenant_ctx.tenant_id,
        kind="si.deep_analysis",
        correlation_id=str(uuid.uuid4()),  # no such shell
    )
    db.add(job)
    await db.flush()
    handler = get_job_handler("si.deep_analysis")
    with pytest.raises(ValueError, match="shell missing"):
        await handler(db, job)
