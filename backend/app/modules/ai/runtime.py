"""Agent runtime — the model loop that turns a user message into an answer.

Flow: load agent + its tools -> create agent_runs row -> build messages ->
loop (chat via gateway; execute requested tools through the registry and
policy) -> finalize the run. Exceptions mark the run failed and re-raise.

The model NEVER touches SQL: every business action goes through
app.modules.ai.tools, gated by the agent's tool policy.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError, NotFoundError
from app.modules.ai.gateway import (
    AIBudgetFallbackRequested,
    AIGateway,
    estimate_cost,
)
from app.modules.ai.guardrails import default_guardrail, screen_inbound
from app.modules.ai.models import Agent, AgentRun, AgentTool, ToolCall
from app.modules.ai.providers import ToolCallRequest
from app.modules.ai.tools import tool_to_openai_schema  # noqa: E402
from app.modules.ai.usage import record_usage  # noqa: E402


def _assistant_tool_call(tc: ToolCallRequest) -> dict:
    """OpenAI tool_call entry — with Gemini 3.x thought_signature when present
    (required on the next turn, otherwise the provider 400s)."""
    entry: dict = {
        "id": tc.id,
        "type": "function",
        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments or {})},
    }
    if tc.thought_signature:
        entry["extra_content"] = {"google": {"thought_signature": tc.thought_signature}}
    return entry


from app.modules.conversations import models as _conversations_models  # noqa: E402,F401

# Importing the conversations models registers their tables in the shared
# metadata so agent_runs' FK to conversations.id resolves even when the AI
# runtime is used in a process that never touched the conversations module.

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 5
HISTORY_MESSAGES = 10
DEFAULT_SYSTEM_PROMPT = "You are a helpful sales assistant."
# Outbound rows whose send did not land: "failed" is terminal and "unknown" is
# a result that went missing mid-flight (conversations/models.py:172). Neither
# is a turn the customer read.
_UNDELIVERED_OUTBOUND_STATUSES = frozenset({"failed", "unknown"})
ALIASES = frozenset({"fast", "strong", "cheap", "embedding", "fallback"})
DEFAULT_RUN_LIMITS = {
    "max_steps": MAX_ITERATIONS,
    "max_tool_calls": 10,
    "max_wall_time_seconds": 120,
    "max_retries": 2,  # §134: max tool-call retries before giving up
    "max_handoffs": 1,  # §134: max agent handoffs before stopping
}
RUN_LIMITS_CEILINGS = {
    "max_steps": 25,
    "max_tool_calls": 100,
    "max_wall_time_seconds": 900,
    "max_retries": 10,
    "max_handoffs": 5,
}


def _run_limits(agent: Agent) -> dict[str, int]:
    """Return bounded per-agent limits while preserving old agent rows."""
    configured = agent.run_limits if isinstance(agent.run_limits, dict) else {}
    limits: dict[str, int] = {}
    for name, default in DEFAULT_RUN_LIMITS.items():
        try:
            value = int(configured.get(name, default))
        except (TypeError, ValueError):
            value = default
        limits[name] = max(1, min(value, RUN_LIMITS_CEILINGS[name]))
    return limits


def _tool_for(agent_tool: AgentTool):
    """The registered ToolSpec for an agent tool row, or None if unknown."""
    from app.modules.ai.tools import get_tool

    return get_tool(agent_tool.name)


@dataclass(slots=True)
class AgentRunResult:
    content: str | None
    tool_calls_made: list[dict] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    # §41: the output-guardrail verdict, always populated. `content` is None
    # whenever this is not "allow", so a caller cannot accidentally send
    # unguarded text even if it forgets to check.
    guardrail_decision: str = "allow"
    guardrail_reason: str | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _memory_line(memory) -> str:
    """One annotated memory line (§158 / ADR-036).

    "Customer said X" and "the AI guessed X" must not read the same to the
    model: every line carries its source, confidence, and whether a system
    event or staff review verified it. Unverified claims are shouted — an
    agent that repeats an unverified inference as fact is exactly the failure
    §158 exists to prevent.
    """
    confidence = float(memory.confidence) if memory.confidence is not None else 0.5
    verified = memory.verified_at is not None or memory.source == "system_verified"
    stamp = "VERIFIED" if verified else "UNVERIFIED"
    return f"- ({memory.source}, confidence={confidence:.2f}, {stamp}) {memory.content}"


class AgentRunner:
    def __init__(self, gateway: AIGateway | None = None) -> None:
        self.gateway = gateway or AIGateway()

    # ------------------------------------------------------------ public ---

    async def run(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        agent_id: uuid.UUID,
        conversation_id: uuid.UUID | None = None,
        user_message: str,
        customer_id: uuid.UUID | None = None,
        system_prompt: str | None = None,
        # §132: untrusted context, separate from system prompt
        knowledge_context: str | None = None,
    ) -> AgentRunResult:
        agent = await self._load_agent(session, tenant_id, agent_id)
        agent_tools = await self._load_agent_tools(session, tenant_id, agent_id)

        run = AgentRun(
            tenant_id=tenant_id,
            agent_id=agent.id,
            conversation_id=conversation_id,
            status="running",
            input={
                "message": user_message,
                "customer_id": str(customer_id) if customer_id else None,
            },
            started_at=_now(),
        )
        session.add(run)
        await session.flush()

        # §126: acquire the conversation lease INSIDE the runtime, so any
        # caller (not just the message-worker hook) is serialized. Two
        # concurrent AI runs on the same conversation would produce
        # conflicting state — duplicate orders, interleaved tool calls,
        # lost writes. The advisory lock is transaction-scoped and
        # reentrant, so the hook's own lease is a no-op.
        lease_cm = None
        if conversation_id is not None:
            from app.core.lease import conversation_lease

            lease_cm = conversation_lease(session, conversation_id)
            await lease_cm.__aenter__()

        try:
            result = await self._loop(
                session,
                tenant_id,
                agent=agent,
                agent_tools=agent_tools,
                run=run,
                conversation_id=conversation_id,
                user_message=user_message,
                customer_id=customer_id,
                system_prompt=system_prompt,
                knowledge_context=knowledge_context,  # §132
            )
        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)
            run.finished_at = _now()
            await session.flush()
            if isinstance(exc, DomainError):
                raise
            raise DomainError(f"agent run failed: {exc}") from exc
        finally:
            if lease_cm is not None:
                await lease_cm.__aexit__(None, None, None)

        if run.status == "running":
            run.status = "succeeded"
        run.output = {"content": result.content}
        run.tokens_in = result.tokens_in
        run.tokens_out = result.tokens_out
        run.cost = estimate_cost(result.tokens_in, result.tokens_out)
        run.finished_at = _now()
        await session.flush()

        # §38: persist a memory from the AI run so future runs can retrieve it.
        # §158: the memory is labelled agent_inferred — NOT customer_stated —
        # because this is an AI-generated summary, not something the customer
        # explicitly said. confidence is moderate (not verified by a system event).
        if customer_id is not None and result.content and result.guardrail_decision == "allow":
            try:
                from app.modules.ai.knowledge import add_memory

                await add_memory(
                    session,
                    tenant_id,
                    customer_id=customer_id,
                    conversation_id=conversation_id,
                    kind="summary",
                    content=f"AI run: {result.content[:500]}",
                    source="agent_inferred",
                    confidence=0.6,
                )
            except Exception:  # noqa: BLE001 — memory is best-effort
                logger.warning("ai.memory_persist_failed run=%s", run.id, exc_info=True)

        await record_usage(
            session,
            tenant_id,
            agent_id=agent.id,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            cost=estimate_cost(result.tokens_in, result.tokens_out),
        )
        return result

    # ----------------------------------------------------------- private ---

    @staticmethod
    async def _load_agent(
        session: AsyncSession, tenant_id: uuid.UUID, agent_id: uuid.UUID
    ) -> Agent:
        agent = (
            await session.execute(
                select(Agent).where(
                    Agent.tenant_id == tenant_id,
                    Agent.id == agent_id,
                    Agent.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if agent is None:
            raise NotFoundError(f"agent {agent_id} not found")
        return agent

    @staticmethod
    async def _load_agent_tools(
        session: AsyncSession, tenant_id: uuid.UUID, agent_id: uuid.UUID
    ) -> list[AgentTool]:
        rows = (
            await session.execute(
                select(AgentTool).where(
                    AgentTool.tenant_id == tenant_id,
                    AgentTool.agent_id == agent_id,
                    AgentTool.is_active.is_(True),
                )
            )
        ).scalars()
        return list(rows.all())

    @staticmethod
    def _alias_for(agent: Agent) -> str:
        # Agent.model stores a gateway alias; unknown/empty values use "fast".
        return agent.model if (agent.model or "") in ALIASES else "fast"

    async def _loop(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        agent: Agent,
        agent_tools: list[AgentTool],
        run: AgentRun,
        conversation_id: uuid.UUID | None,
        user_message: str,
        customer_id: uuid.UUID | None,
        system_prompt: str | None,
        knowledge_context: str | None = None,  # §132
    ) -> AgentRunResult:
        # §41 input side: what the model is ABOUT to be shown is judged before
        # it is shown. The output chain cannot cover this — it only ever sees
        # what came back — and screening here means every caller of the runner
        # is covered, not just the auto-reply hook.
        inbound = screen_inbound(user_message)
        if inbound.decision != "allow":
            logger.warning(
                "ai.inbound_guardrail_%s run=%s reason=%s",
                inbound.decision,
                run.id,
                inbound.reason,
            )
            return AgentRunResult(
                content=None,
                guardrail_decision=inbound.decision,
                guardrail_reason=inbound.reason,
            )

        messages: list[dict] = [
            {
                "role": "system",
                "content": system_prompt or agent.system_prompt or DEFAULT_SYSTEM_PROMPT,
            }
        ]
        # §132: knowledge context is injected as a SEPARATE user message,
        # not appended to the system prompt. This separates trusted
        # instructions from untrusted retrieved content, reducing the
        # prompt-injection surface.
        if knowledge_context:
            messages.append({
                "role": "user",
                "content": f"[Knowledge base — untrusted context]\n{knowledge_context}",
            })
        if conversation_id is not None:
            messages.extend(
                await self._conversation_history(
                    session,
                    tenant_id,
                    conversation_id,
                    current_message=user_message,
                )
            )
        # §38: retrieve customer memories and inject into context (best-effort).
        # ADR-036: each line carries its provenance so the model (and anyone
        # reading the trace) can tell "customer said X" from "the AI guessed X"
        # — unverified claims are marked UNVERIFIED, never presented as fact.
        # Injected as a separate untrusted user message BEFORE the customer's
        # own turn, and never in the system role: retrieved content must not
        # inherit instruction trust (§132's rule, applied to memories too).
        if customer_id is not None:
            try:
                from app.modules.ai.knowledge import search_memory

                memories = await search_memory(
                    session, tenant_id, user_message, customer_id=customer_id, limit=5
                )
                if memories:
                    mem_snippets = "\n".join(_memory_line(m) for m, _dist in memories)
                    messages.append({
                        "role": "user",
                        "content": "[Customer memories — untrusted context]\n"
                        + mem_snippets,
                    })
            except Exception:  # noqa: BLE001 — memory is best-effort context
                logger.warning("ai.memory_search_failed customer=%s", customer_id, exc_info=True)

        messages.append({"role": "user", "content": user_message})

        tools_schema = [
            tool_to_openai_schema(spec)
            for spec in (tool for tool in map(_tool_for, agent_tools) if tool is not None)
        ] or None

        tool_calls_made: list[dict] = []
        tokens_in = 0
        tokens_out = 0
        content: str | None = None

        # §134 run limits: configured per agent, bounded by server policy.
        limits = _run_limits(agent)
        started_at = datetime.now(UTC)
        max_wall_time = timedelta(seconds=limits["max_wall_time_seconds"])
        max_tool_calls = limits["max_tool_calls"]
        hit_limit: str | None = None

        awaiting_approval = False
        # A natural completion sets this False; if the loop ends any other way
        # the step budget ran out mid-tool-loop (the max_steps timeout, §134).
        exhausted = True
        for _iteration in range(limits["max_steps"]):
            if datetime.now(UTC) - started_at > max_wall_time:
                hit_limit = "max_wall_time"
                break
            try:
                chat_result = await self.gateway.chat(
                    session,
                    tenant_id,
                    alias=self._alias_for(agent),
                    messages=messages,
                    tools=tools_schema,
                    temperature=float(agent.temperature),
                    max_tokens=agent.max_output_tokens,
                    agent_id=agent.id,
                    run_id=run.id,
                )
            except AIBudgetFallbackRequested:
                # §42: cap exhausted, policy says downgrade — retry this step
                # on the "fallback" alias (the cheap model). If the fallback
                # alias is what just failed, stop and hand over instead of
                # looping the same exhausted budget.
                if self._alias_for(agent) != "fallback":
                    chat_result = await self.gateway.chat(
                        session,
                        tenant_id,
                        alias="fallback",
                        messages=messages,
                        tools=tools_schema,
                        temperature=float(agent.temperature),
                        max_tokens=agent.max_output_tokens,
                        agent_id=agent.id,
                        run_id=run.id,
                    )
                else:
                    hit_limit = "budget_fallback_exhausted"
                    break
            tokens_in += chat_result.tokens_in
            tokens_out += chat_result.tokens_out

            if not chat_result.tool_calls:
                content = chat_result.content
                exhausted = False
                break

            # Gemini 3.x requires each tool_call entry to carry its
            # thought_signature on the next turn, otherwise it 400s.
            assistant_msg: dict = {
                "role": "assistant",
                "content": chat_result.content,
                "tool_calls": [
                    _assistant_tool_call(tc) for tc in chat_result.tool_calls
                ],
            }
            messages.append(assistant_msg)
            answered_ids: set[str] = set()
            for tc in chat_result.tool_calls:
                if len(tool_calls_made) >= max_tool_calls:
                    hit_limit = "max_tool_calls"
                    break
                outcome = await self._execute_tool(
                    session, tenant_id, run=run, agent_tools=agent_tools, request=tc,
                    customer_id=customer_id, conversation_id=conversation_id,
                )
                tool_calls_made.append(outcome)
                answered_ids.add(tc.id)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(outcome.get("result") or {}),
                    }
                )
                if outcome.get("status") == "awaiting_approval":
                    # §135: SUSPEND the loop. The previous behavior kept
                    # calling the model — it re-issued the same tool call
                    # (duplicate approvals, extra spend) and answered the
                    # customer as if the blocked action had happened.
                    awaiting_approval = True
                    break
            if awaiting_approval:
                break
            if hit_limit == "max_tool_calls":
                # OpenAI-compatible providers reject an assistant message
                # with tool_calls that lack tool responses — synthesize a
                # skip result for every unanswered id before the loop ends.
                for tc in chat_result.tool_calls:
                    if tc.id not in answered_ids:
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": json.dumps(
                                    {"skipped": "tool call limit reached"}
                                ),
                            }
                        )
                break
            content = chat_result.content or content

        if awaiting_approval:
            # run.status was set to WAITING_APPROVAL by _execute_tool; leave
            # content empty — hooks sends nothing while approval is pending.
            await session.flush()
            logger.warning("ai.run_awaiting_approval run=%s", run.id)
        elif hit_limit:
            run.status = "timeout"
            run.error = f"run limit hit: {hit_limit}"
            # §134: a run that hits its limit must not leave the conversation
            # in AI limbo — the customer would get silence. Record a durable
            # handover so a human picks it up.
            if conversation_id is not None:
                from app.modules.ai.models import AIHandover

                session.add(
                    AIHandover(
                        tenant_id=tenant_id,
                        conversation_id=conversation_id,
                        run_id=run.id,
                        reason="failure",
                        status="pending",
                        note=f"run_limit:{hit_limit}",
                    )
                )
            await session.flush()
            logger.warning("ai.run_limit_hit run=%s limit=%s", run.id, hit_limit)
        elif exhausted:
            # The step budget ran out mid-tool-loop: the model never produced a
            # final answer. This must not fall through to the caller's
            # `running -> succeeded`, which reported a failed run as a success
            # with no content (test_agent_run_uses_configured_step_limit).
            run.status = "timeout"
            run.error = "run limit hit: max_steps"
            # §134: same as above — the step budget ran out, so a human takes
            # over rather than the customer staring at silence.
            if conversation_id is not None:
                from app.modules.ai.models import AIHandover

                session.add(
                    AIHandover(
                        tenant_id=tenant_id,
                        conversation_id=conversation_id,
                        run_id=run.id,
                        reason="failure",
                        status="pending",
                        note="run_limit:max_steps",
                    )
                )
            await session.flush()
            logger.warning("ai.run_limit_hit run=%s limit=max_steps", run.id)

        # §41 output guardrail — enforced HERE, not in the caller. It used to
        # live in the auto-reply hook, so any other entry point into the runner
        # (automation, a campaign, a future API) would have bypassed it
        # entirely. Withholding the content is what makes the gate real: a
        # caller that forgets to inspect the verdict still cannot send it.
        decision, reason = "allow", None
        if content:
            # `require_tool_evidence` is on because this is the only place the
            # run's tool results exist: a price or a stock level the model
            # invented, with nothing behind it, is handed over rather than sent.
            verdict = default_guardrail(require_tool_evidence=True).evaluate(
                content, {"tool_results": tool_calls_made}
            )
            decision, reason = verdict.decision, verdict.reason
            if decision != "allow":
                logger.warning(
                    "ai.guardrail_%s run=%s reason=%s", decision, run.id, reason
                )
                content = None

        return AgentRunResult(
            content=content,
            tool_calls_made=tool_calls_made,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            guardrail_decision=decision,
            guardrail_reason=reason,
        )

    @staticmethod
    def _voice_turns(
        rows: dict[uuid.UUID, tuple[str | None, str | None]],
    ) -> dict[uuid.UUID, str]:
        """§35: body-less inbound messages that carry audio, as model-readable turns.

        The lookup itself goes through the module that owns the attachment table
        (`ConversationService.audio_transcripts`) — this module does not reach
        into another module's models. A voice note whose transcript is missing
        (still pending, or STT failed) gets an explicit marker: "nothing" and
        "the customer spoke and we could not hear them" are different things to
        tell the model.
        """
        out: dict[uuid.UUID, str] = {}
        for message_id, (status, text) in rows.items():
            if text:
                out[message_id] = (
                    f"[customer voice message, {status} transcript — treat as what "
                    f"the customer said]\n{text}"
                )
            else:
                out[message_id] = (
                    "[customer sent a voice message; no transcript is available "
                    "for it yet]"
                )
        return out

    @staticmethod
    def _media_marker(message) -> str | None:
        """A body-less row still says something: which kind of thing was sent.

        §35 gave voice notes a turn of their own; every other medium (image,
        file, video, location) was `continue`d away, so a customer who sent a
        price list as a picture looked like a customer who had said nothing.
        Naming the kind is all the model can honestly be given — this runtime
        does not see inside attachments.
        """
        kind = (message.content_type or "").strip().lower()
        if kind in ("", "text"):
            # Rows written before §155 carry no canonical kind, only media_type.
            kind = (message.media_type or "").strip().lower()
        if kind in ("", "text"):
            kind = "attachment" if message.media_url else ""
        if not kind:
            return None
        speaker = "the assistant" if message.direction == "outbound" else "the customer"
        return f"[{speaker} sent {kind}; its contents are not available to me]"

    @staticmethod
    def _provider_turns(
        history,
        *,
        voice: dict[uuid.UUID, str],
        current_message: str | None = None,
    ) -> list[dict]:
        """Map `messages` rows to provider turns — who actually said what.

        `direction` alone cannot answer that, and mapping on it replayed lies:

        * an outbound row whose send ``failed`` (or is still ``unknown``) never
          reached the customer, so it is not something the assistant said;
        * a ``system`` row is a platform notice — assignment, a broadcast, a
          tombstone — authored by neither side of the conversation;
        * the newest inbound row IS the message being answered, which the loop
          appends itself. Without this the prompt carried it twice and the
          model read an echo of its own question as a second customer.
        """
        turns: list[dict] = []
        for message in history:
            outbound = message.direction == "outbound"
            if outbound and (
                message.sender_type == "system"
                or (message.status or "") in _UNDELIVERED_OUTBOUND_STATUSES
            ):
                continue
            content = (
                message.body
                or voice.get(message.id)
                or AgentRunner._media_marker(message)
            )
            if not content:
                continue
            turns.append(
                {"role": "assistant" if outbound else "user", "content": content}
            )
        if (
            current_message is not None
            and turns
            and turns[-1]["role"] == "user"
            and turns[-1]["content"].strip() == current_message.strip()
        ):
            turns.pop()
        return turns

    @staticmethod
    async def _conversation_history(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
        *,
        current_message: str | None = None,
    ) -> list[dict]:
        # Lazy import: conversations module owns the message table.
        from app.modules.conversations.service import ConversationService

        history = await ConversationService.list_messages(
            session, tenant_id, conversation_id, limit=HISTORY_MESSAGES
        )
        spoken_ids = [
            m.id for m in history if not m.body and m.direction == "inbound"
        ]
        rows = await ConversationService.audio_transcripts(
            session, tenant_id, spoken_ids
        )
        voice = AgentRunner._voice_turns(rows)
        return AgentRunner._provider_turns(
            history, voice=voice, current_message=current_message
        )

    async def _execute_tool(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        run: AgentRun,
        agent_tools: list[AgentTool],
        request: ToolCallRequest,
        customer_id: uuid.UUID | None = None,
        conversation_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Run one requested tool call under the agent's policy; record the row.

        §132: HIGH-risk tools (§15) require a durable human approval BEFORE
        execution — the run suspends as WAITING_APPROVAL. The tool's context
        pins the conversation's customer server-side (§132 scope binding).

        §15-16: idempotency — the (run_id, tool_call_id) pair is the dedupe
        key. A retried run or replayed event that re-issues the same tool
        call finds the prior ToolCall row and returns its result without
        re-executing the handler, preventing duplicate side-effects.
        """
        from app.modules.ai.tools import get_tool

        # §15-16: idempotency pre-check. If this exact tool call (same run,
        # same provider tool_call_id) was already executed, return the prior
        # result. The unique constraint on (tenant_id, idempotency_key) makes
        # the check-then-insert atomic under concurrent retries.
        idempotency_key = f"{run.id}:{request.id}"
        prior = (
            await session.execute(
                select(ToolCall).where(
                    ToolCall.tenant_id == tenant_id,
                    ToolCall.idempotency_key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if prior is not None and prior.result is not None and prior.status == "ok":
            logger.info(
                "ai.tool_call_idempotent_skip run=%s tool=%s key=%s",
                run.id, request.name, idempotency_key,
            )
            return {
                "name": prior.name,
                "status": prior.status,
                "error": prior.error,
                "result": prior.result,
            }

        agent_tool = next((t for t in agent_tools if t.name == request.name), None)
        status = "ok"
        result: dict | None = None
        error: str | None = None
        duration_ms: int | None = None

        if agent_tool is None:
            status = "denied"
            error = "tool not enabled for this agent"
        elif request.name in ((agent_tool.policy or {}).get("denied") or []):
            status = "denied"
            error = "tool denied by policy"
        else:
            spec = get_tool(request.name)
            if spec is None:
                status = "error"
                error = f"unknown tool: {request.name}"
            else:
                started = datetime.now(UTC)
                try:
                    kwargs = spec.args_schema(**(request.arguments or {})).model_dump()
                    # §132 scope binding: only handlers that declare `context`
                    # receive the server-side customer/conversation binding.
                    import inspect

                    if "context" in inspect.signature(spec.handler).parameters:
                        kwargs["context"] = {
                            "customer_id": str(customer_id) if customer_id else None,
                            "conversation_id": str(conversation_id) if conversation_id else None,
                        }
                    # §135: HIGH-risk tools suspend the run until a human
                    # approves. The approval row is durable — the run resumes
                    # (or dies) on the decision.
                    from app.modules.ai.approvals import ApprovalService
                    from app.modules.ai.tools import requires_approval

                    if await requires_approval(spec):
                        # §135 + G-02: the approval is bound to THESE arguments.
                        # The payload recorded on the request is what a human
                        # approved, and the resume must present the identical
                        # payload — otherwise it is not the action that was
                        # approved, whatever the action name says.
                        approval_payload = {"arguments": kwargs}
                        granted = await ApprovalService.find_granted(
                            session,
                            tenant_id,
                            conversation_id=conversation_id,
                            action=request.name,
                            payload=approval_payload,
                        )
                        # An approval a human already granted for this exact
                        # conversation+action+arguments is the resume path:
                        # execute ONCE and consume it, so one approval can never
                        # authorize repeated executions. A new customer message
                        # since it was granted makes it stale — the context it
                        # was decided on no longer holds, so re-evaluate rather
                        # than auto-continue.
                        if (
                            granted is not None
                            and conversation_id is not None
                            and await ApprovalService.is_stale_for_conversation(
                                session, conversation_id, since=granted.created_at
                            )
                        ):
                            granted = None
                        if granted is not None:
                            await ApprovalService.consume(session, granted)
                            result = await spec.handler(session, tenant_id, **kwargs)
                        else:
                            # The action has NOT happened. Park the run and
                            # return WITHOUT calling the handler — executing
                            # here would run a HIGH-risk tool (create order,
                            # refund, delete) with no human in the loop while
                            # the UI showed "waiting for approval".
                            await ApprovalService.request(
                                session,
                                tenant_id,
                                run_id=run.id,
                                conversation_id=conversation_id,
                                entity_type="tool",
                                entity_id=request.name,
                                action=request.name,
                                risk_level="HIGH",
                                payload=approval_payload,
                            )
                            run.status = "WAITING_APPROVAL"
                            status = "awaiting_approval"
                            result = {"awaiting_approval": True}
                    else:
                        result = await spec.handler(session, tenant_id, **kwargs)
                except PydanticValidationError as exc:
                    status = "error"
                    error = f"invalid tool arguments: {exc.errors()[0].get('msg', str(exc))}"
                except Exception as exc:
                    status = "error"
                    error = str(exc)
                    logger.warning(
                        "ai tool call failed",
                        extra={"tool": request.name, "run_id": str(run.id)},
                    )
                else:
                    duration_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
        session.add(
            ToolCall(
                tenant_id=tenant_id,
                run_id=run.id,
                agent_tool_id=agent_tool.id if agent_tool else None,
                name=request.name,
                args=request.arguments or {},
                result=result,
                idempotency_key=idempotency_key,
                status=status,
                error=error,
                duration_ms=duration_ms if status == "ok" else None,
            )
        )
        await session.flush()

        if status == "denied":
            result = {"error": error}
        elif status == "error":
            result = {"error": error or "tool failed"}
        return {"name": request.name, "status": status, "error": error, "result": result}
