"""Deployment pinning proof (fe2026100818 wave) — runs execute the pinned version.

The runtime's resolver always preferred a deployment row, but no store had
one: production carried 22 published versions and ZERO ``agent_deployments``
rows, so every run silently executed the agent's MUTABLE settings under the
documented ``fallback:no_deployment`` branch. The backfill migration and the
publish-path wiring close the supply side; these tests prove the demand side
at the level that matters — a REAL ``AgentRunner.run``:

* with a deployment present, the created ``agent_runs`` row carries the
  pinned ``agent_version_id`` and the model is actually shown the pinned
  snapshot's prompt (not merely told a version id);
* with no deployment, the run still works and ``version_source`` records the
  fallback instead of hiding it;
* with ``canary_percent = 0``, the stable version is what serves — a canary
  decision of zero percent can never leak the candidate into traffic;
* ``fully_rollout`` (a completed canary whose candidate was promoted) is a
  LIVE deployment: it must keep pinning, not fall back to mutable settings.
  This pins the resolver's status filter, which previously accepted only
  ``active`` and un-pinned every post-canary store.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.ai.gateway import AIGateway
from app.modules.ai.models import Agent, AgentRun, AgentVersion, Deployment
from app.modules.ai.providers import ChatCompletionResult
from app.modules.ai.runtime import AgentRunner
from app.modules.ai.versions import AIAgentVersionService

pytestmark = pytest.mark.usefixtures("db")

# No numerals, no claims — passes the output guardrail's evidence gate without
# tool results, so the run tests exercise pinning, not the §41 chain.
_SAFE_REPLY = "تمام، تحت أمرك."
_SAFE_QUESTION = "مرحبا"


def _result(content: str | None = None) -> ChatCompletionResult:
    return ChatCompletionResult(
        content=content,
        tool_calls=[],
        tokens_in=1,
        tokens_out=1,
        raw_model="fake-model",
    )


def _patch_gateway_chat(monkeypatch, results: list[ChatCompletionResult]) -> dict[str, Any]:
    """Stub the gateway and capture the messages the model was actually shown."""
    calls: dict[str, Any] = {"count": 0, "messages": None}

    async def fake_chat(self, session, tenant_id, *, alias, messages, tools=None, **kwargs):
        calls["count"] += 1
        calls["messages"] = messages
        return results[min(calls["count"], len(results)) - 1]

    monkeypatch.setattr(AIGateway, "chat", fake_chat)
    return calls


def _agent(tenant_id: uuid.UUID, system_prompt: str = "row prompt") -> Agent:
    return Agent(
        tenant_id=tenant_id,
        kind="customer",
        name="Pinned Agent",
        model="fast",
        system_prompt=system_prompt,
        temperature=0.7,
        run_limits={},
    )


async def _deployment_for(
    db: AsyncSession, tenant_id: uuid.UUID, agent_id: uuid.UUID
) -> Deployment:
    return (
        await db.execute(
            select(Deployment).where(
                Deployment.tenant_id == tenant_id,
                Deployment.agent_id == agent_id,
            )
        )
    ).scalar_one()


async def _run_row(db: AsyncSession, run_id: uuid.UUID) -> AgentRun:
    return (await db.execute(select(AgentRun).where(AgentRun.id == run_id))).scalar_one()


def _system_message(messages: list[dict] | None) -> str | None:
    assert messages, "the gateway stub saw no messages"
    first = messages[0]
    assert first["role"] == "system"
    return first["content"]


class TestRunPinsTheDeployedVersion:
    async def test_deployment_present_run_carries_the_pinned_version(
        self, db, tenant_ctx, monkeypatch
    ) -> None:
        agent = _agent(tenant_ctx.tenant_id, system_prompt="mutable drift prompt")
        db.add(agent)
        await db.flush()
        # Snapshot a prompt that DIFFERS from what the row will say at run
        # time, then drift the row back — publish snapshots the row, so the
        # discriminator must be manufactured, and it is exactly the drift the
        # pinning contract exists to neutralize.
        agent.system_prompt = "pinned snapshot prompt"
        await db.flush()
        version = await AIAgentVersionService.publish(db, tenant_ctx.tenant_id, agent.id)
        agent.system_prompt = "mutable drift prompt"
        await db.flush()
        calls = _patch_gateway_chat(monkeypatch, [_result(_SAFE_REPLY)])

        result = await AgentRunner(gateway=AIGateway()).run(
            db,
            tenant_ctx.tenant_id,
            agent_id=agent.id,
            user_message=_SAFE_QUESTION,
        )

        run = await _run_row(db, result.run_id)
        assert run.agent_version_id == version.id
        assert run.input["version_source"] == "deployment"
        assert run.status == "succeeded"
        # The model was shown the PINNED snapshot's prompt, not the row's —
        # a version id in the run record alone could still hide a row-served
        # answer behind it.
        assert _system_message(calls["messages"]) == "pinned snapshot prompt"
        assert _system_message(calls["messages"]) != "mutable drift prompt"

    async def test_deployment_absent_falls_back_and_records_it(
        self, db, tenant_ctx, monkeypatch
    ) -> None:
        agent = _agent(tenant_ctx.tenant_id)
        db.add(agent)
        await db.flush()
        calls = _patch_gateway_chat(monkeypatch, [_result(_SAFE_REPLY)])

        result = await AgentRunner(gateway=AIGateway()).run(
            db,
            tenant_ctx.tenant_id,
            agent_id=agent.id,
            user_message=_SAFE_QUESTION,
        )

        run = await _run_row(db, result.run_id)
        assert run.agent_version_id is None
        assert run.input["version_source"] == "fallback:no_deployment"
        assert run.status == "succeeded"
        # The documented fallback runs the MUTABLE row — the system message
        # must be the row's prompt so the audit trail matches what executed.
        assert _system_message(calls["messages"]) == "row prompt"

    async def test_canary_percent_zero_serves_the_stable_version(
        self, db, tenant_ctx, monkeypatch
    ) -> None:
        agent = _agent(tenant_ctx.tenant_id)
        db.add(agent)
        await db.flush()
        stable = await AIAgentVersionService.publish(db, tenant_ctx.tenant_id, agent.id)
        # A second published version exists, wired as the candidate, but the
        # canary split is 0% — the candidate must stay out of traffic.
        agent.system_prompt = "candidate prompt"
        await db.flush()
        candidate = await AIAgentVersionService.publish(db, tenant_ctx.tenant_id, agent.id)
        deployment = await _deployment_for(db, tenant_ctx.tenant_id, agent.id)
        deployment.candidate_version_id = candidate.id
        await db.flush()
        calls = _patch_gateway_chat(monkeypatch, [_result(_SAFE_REPLY)])

        result = await AgentRunner(gateway=AIGateway()).run(
            db,
            tenant_ctx.tenant_id,
            agent_id=agent.id,
            user_message=_SAFE_QUESTION,
        )

        run = await _run_row(db, result.run_id)
        assert run.agent_version_id == stable.id
        assert run.agent_version_id != candidate.id
        assert run.input["version_source"] == "deployment"
        assert _system_message(calls["messages"]) == stable.system_prompt


class TestResolverDeploymentStatuses:
    async def _stack(
        self, db: AsyncSession, tenant_ctx, *, publish_candidate: bool = False
    ) -> tuple[Agent, AgentVersion, AgentVersion | None, Deployment]:
        agent = _agent(tenant_ctx.tenant_id)
        db.add(agent)
        await db.flush()
        stable = await AIAgentVersionService.publish(db, tenant_ctx.tenant_id, agent.id)
        candidate: AgentVersion | None = None
        if publish_candidate:
            agent.system_prompt = "candidate prompt"
            await db.flush()
            candidate = await AIAgentVersionService.publish(db, tenant_ctx.tenant_id, agent.id)
        deployment = await _deployment_for(db, tenant_ctx.tenant_id, agent.id)
        return agent, stable, candidate, deployment

    async def test_canary_chosen_serves_the_candidate(self, db, tenant_ctx) -> None:
        agent, _stable, candidate, deployment = await self._stack(
            db, tenant_ctx, publish_candidate=True
        )
        deployment.candidate_version_id = candidate.id
        deployment.canary_percent = 20
        await db.flush()

        version_id, source, _policy = await AgentRunner._resolve_agent_version(
            db, tenant_ctx.tenant_id, agent, canary_chosen=True
        )
        assert version_id == candidate.id
        assert source == "deployment"

    async def test_fully_rollout_deployment_still_pins_the_stable_version(
        self, db, tenant_ctx
    ) -> None:
        agent, stable, _candidate, deployment = await self._stack(db, tenant_ctx)
        # The state the evaluation service writes when a canary reaches 100%:
        # the candidate was promoted to stable and the split reset to zero.
        deployment.status = "fully_rollout"
        await db.flush()

        version_id, source, _policy = await AgentRunner._resolve_agent_version(
            db, tenant_ctx.tenant_id, agent, canary_chosen=False
        )
        assert version_id == stable.id
        assert source == "deployment"

    async def test_rolled_back_deployment_falls_back(self, db, tenant_ctx) -> None:
        agent, _stable, _candidate, deployment = await self._stack(db, tenant_ctx)
        deployment.status = "rolled_back"
        await db.flush()

        version_id, source, _policy = await AgentRunner._resolve_agent_version(
            db, tenant_ctx.tenant_id, agent, canary_chosen=False
        )
        assert version_id is None
        assert source == "fallback:no_deployment"
