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
from app.modules.ai.gateway import AIGateway, estimate_cost
from app.modules.ai.models import Agent, AgentRun, AgentTool, ToolCall
from app.modules.ai.providers import ToolCallRequest


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


from app.modules.ai.tools import tool_to_openai_schema  # noqa: E402
from app.modules.ai.usage import record_usage  # noqa: E402
from app.modules.conversations import models as _conversations_models  # noqa: E402,F401

# Importing the conversations models registers their tables in the shared
# metadata so agent_runs' FK to conversations.id resolves even when the AI
# runtime is used in a process that never touched the conversations module.

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 5
HISTORY_MESSAGES = 10
DEFAULT_SYSTEM_PROMPT = "You are a helpful sales assistant."
ALIASES = frozenset({"fast", "strong", "cheap", "embedding", "fallback"})
DEFAULT_RUN_LIMITS = {
    "max_steps": MAX_ITERATIONS,
    "max_tool_calls": 10,
    "max_wall_time_seconds": 120,
}
RUN_LIMITS_CEILINGS = {
    "max_steps": 25,
    "max_tool_calls": 100,
    "max_wall_time_seconds": 900,
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


def _now() -> datetime:
    return datetime.now(UTC)


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
            )
        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)
            run.finished_at = _now()
            await session.flush()
            if isinstance(exc, DomainError):
                raise
            raise DomainError(f"agent run failed: {exc}") from exc

        if run.status == "running":
            run.status = "succeeded"
        run.output = {"content": result.content}
        run.tokens_in = result.tokens_in
        run.tokens_out = result.tokens_out
        run.cost = estimate_cost(result.tokens_out)
        run.finished_at = _now()
        await session.flush()

        await record_usage(
            session,
            tenant_id,
            agent_id=agent.id,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            cost=estimate_cost(result.tokens_out),
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
    ) -> AgentRunResult:
        messages: list[dict] = [
            {
                "role": "system",
                "content": system_prompt or agent.system_prompt or DEFAULT_SYSTEM_PROMPT,
            }
        ]
        if conversation_id is not None:
            messages.extend(
                await self._conversation_history(session, tenant_id, conversation_id)
            )
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
        for _iteration in range(limits["max_steps"]):
            if datetime.now(UTC) - started_at > max_wall_time:
                hit_limit = "max_wall_time"
                break
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
            tokens_in += chat_result.tokens_in
            tokens_out += chat_result.tokens_out

            if not chat_result.tool_calls:
                content = chat_result.content
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
            await session.flush()
            logger.warning("ai.run_limit_hit run=%s limit=%s", run.id, hit_limit)

        return AgentRunResult(
            content=content,
            tool_calls_made=tool_calls_made,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )

    @staticmethod
    async def _conversation_history(
        session: AsyncSession, tenant_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> list[dict]:
        # Lazy import: conversations module owns the message table.
        from app.modules.conversations.service import ConversationService

        history = await ConversationService.list_messages(
            session, tenant_id, conversation_id, limit=HISTORY_MESSAGES
        )
        messages: list[dict] = []
        for message in history:
            if not message.body:
                continue
            role = "assistant" if message.direction == "outbound" else "user"
            messages.append({"role": role, "content": message.body})
        return messages

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
        """
        from app.modules.ai.tools import get_tool

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
                    from app.modules.ai.tools import requires_approval

                    if await requires_approval(spec):
                        from app.modules.ai.approvals import ApprovalService

                        await ApprovalService.request(
                            session,
                            tenant_id,
                            run_id=run.id,
                            conversation_id=conversation_id,
                            entity_type="tool",
                            entity_id=request.name,
                            action=request.name,
                            risk_level="HIGH",
                            payload={"arguments": kwargs},
                        )
                        run.status = "WAITING_APPROVAL"
                        status = "awaiting_approval"
                        result = {"awaiting_approval": True}
                        # fall through: the ToolCall audit row must be written
                        # for gated calls too (the early return skipped it).
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
