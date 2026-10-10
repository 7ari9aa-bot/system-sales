"""Agent runtime — the model loop that turns a user message into an answer.

Flow: load agent + its tools -> create agent_runs row -> build messages ->
loop (chat via gateway; execute requested tools through the registry and
policy) -> finalize the run. Exceptions mark the run failed and re-raise.

The model NEVER touches SQL: every business action goes through
app.modules.ai.tools, gated by the agent's tool policy.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError, NotFoundError
from app.modules.ai.gateway import (
    AIBudgetFallbackRequested,
    AIGateway,
    estimate_cost,
)
from app.modules.ai.guardrails import analytics_guardrail, default_guardrail, screen_inbound
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
DEFAULT_SYSTEM_PROMPT = (
    "أنت مساعد خدمة العملاء والمبيعات الذكي للمتجر. تتحدث بلهجة مصرية مهذبة وودودة ومباشرة.\n"
    "مهمتك مساعدة العملاء في الاستفسار عن المنتجات، الأسعار، المخزون، وحالة الطلبات، وإتمام "
    "عمليات الشراء.\n"
    "القواعد الإلزامية:\n"
    "1. لا تذكر أو تؤكد أي سعر أو كمية متوفرة إلا بعد الاستعلام عنها عبر الأدوات المخصصة.\n"
    "2. قبل تسجيل أي طلب، تأكد من وضوح كافة بيانات العميل والمنتج والكمية.\n"
    "3. التزم بسياسات المتجر المعلنة بدقة (الشحن، الدفع، الاسترجاع والاستبدال).\n"
    "4. إذا طلب العميل التحدث مع موظف خدمة عملاء أو واجهت طلباً لا تستطيع حله، حوّل "
    "المحادثة لموظف بشري بلطف."
)
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
    run_id: uuid.UUID | None = None
    tool_calls_made: list[dict] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    # §41: the output-guardrail verdict, always populated. `content` is None
    # whenever this is not "allow", so a caller cannot accidentally send
    # unguarded text even if it forgets to check.
    guardrail_decision: str = "allow"
    guardrail_reason: str | None = None
    # §13: media the runner collected SERVER-SIDE from resolve_product_media
    # calls — [{image_id, image_url, alt}] with URLs minted here (capped at
    # four), never shown to the model. hooks delivers these after the text.
    media: list[dict] = field(default_factory=list)
    # Products this run showed or referenced — referent context for the
    # customer agent's state layer ("التاني" needs to know what was shown).
    shown_product_ids: list[str] = field(default_factory=list)
    agent_version: int = 1
    model: str | None = None
    # The concrete model behind the alias — provenance, not a label: "fast"
    # means nothing to a reader three months from now, the resolved name does.
    model_name: str | None = None
    provider: str | None = None


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


#: A side effect already performed, in the sense `tool_calls.idempotency_key`
#: means one: the handler ran, whatever it wrote is in the database.
_EXECUTED_TOOL_STATUSES = frozenset({"ok", "error"})


def compute_tool_idempotency_key(
    *,
    risk_level: str,
    conversation_id: uuid.UUID | None,
    inbound_message_id: uuid.UUID | str | None,
    run_id: uuid.UUID,
    tool_call_id: str,
    tool_name: str,
    arguments: dict | None,
    status: str,
) -> str | None:
    """The key that makes `uq_tool_calls_tenant_idempotency` dedupe a call (§15-16).

    Read-only tools (LOW) key on the run and the provider's tool_call id, because
    repeating a read costs nothing and two `check_stock` calls in one turn are
    usually about different variants — keying them by tool name alone would hand
    the model the first answer for the second question.

    Side-effecting tools (HIGH/MEDIUM) key SEMANTICALLY on conversation + inbound
    message + tool + arguments, without the run id, so a retried message cannot
    double-order.

    An `awaiting_approval` row claims NO key. It records an intent to ask, not a
    side effect that happened — and the approval flow is *designed* to run this
    exact semantic call again after a human grants it. Keying the park meant the
    resume's own park row occupied the key, the real execution's audit insert lost
    the unique-constraint race to it, and the code returned that row's
    `awaiting_approval` outcome: the approved order was created, the customer was
    told it was still pending forever, and the governance record said nothing
    happened.
    """
    if status not in _EXECUTED_TOOL_STATUSES:
        return None
    if risk_level in ("HIGH", "MEDIUM") and conversation_id is not None:
        args_hash = hashlib.sha256(
            json.dumps(arguments or {}, sort_keys=True).encode()
        ).hexdigest()[:16]
        msg_key = str(inbound_message_id) if inbound_message_id else str(run_id)
        return f"se:{conversation_id}:{msg_key}:{tool_name}:{args_hash}"
    return f"{run_id}:{tool_call_id}"


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
        inbound_message_id: uuid.UUID | str | None = None,
        user_message: str,
        customer_id: uuid.UUID | None = None,
        system_prompt: str | None = None,
        # §132: untrusted context, separate from system prompt
        knowledge_context: str | None = None,
        # P1-10: the conversation's confirmed quote (if the customer typed the
        # code), bound server-side — create_order executes from it.
        confirmed_quote_id: uuid.UUID | str | None = None,
    ) -> AgentRunResult:
        agent = await self._load_agent(session, tenant_id, agent_id)
        agent_tools = await self._load_agent_tools(
            session, tenant_id, agent_id, agent_kind=agent.kind
        )

        # §169: canary deployment decision — deterministic per conversation so
        # the same conversation does not flip between stable and candidate
        # across retries. Without AgentVersion rows the version itself cannot
        # switch yet, but the decision is recorded and the gate is live.
        canary_percent = 0
        canary_chosen = False
        try:
            from app.modules.ai.evaluation import AIEvaluationService

            canary_percent = await AIEvaluationService.get_canary_traffic_percent(
                session, tenant_id, agent_id
            )
        except Exception:
            logger.warning("ai.canary_check_failed agent=%s", agent_id, exc_info=True)
        if canary_percent > 0 and conversation_id is not None:
            bucket = int(hashlib.md5(conversation_id.bytes).hexdigest(), 16) % 100
            canary_chosen = bucket < canary_percent

        agent_version_id, version_source, version_tool_policy = (
            await self._resolve_agent_version(
                session, tenant_id, agent, canary_chosen=canary_chosen
            )
        )
        # The published version's policy narrows the registry-authorized set
        # for this run; it can never widen it (filter is veto-only).
        if version_tool_policy:
            before = len(agent_tools)
            from app.modules.ai.versions import filter_agent_tools_by_policy

            agent_tools = filter_agent_tools_by_policy(agent_tools, version_tool_policy)
            if len(agent_tools) != before:
                logger.info(
                    "ai.tool_policy_narrowed run_agent=%s from=%d to=%d",
                    agent.id,
                    before,
                    len(agent_tools),
                )

        run = AgentRun(
            tenant_id=tenant_id,
            agent_id=agent.id,
            agent_version_id=agent_version_id,
            conversation_id=conversation_id,
            status="running",
            input={
                "message": user_message,
                "customer_id": str(customer_id) if customer_id else None,
                "agent_version": getattr(agent, "version", 1),
                "model": self._alias_for(agent),
                "model_name": agent.model,
                "system_prompt_version": getattr(agent, "version", 1),
                "canary_percent": canary_percent,
                "canary_chosen": canary_chosen,
                "version_source": version_source,
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
                inbound_message_id=inbound_message_id,
                user_message=user_message,
                customer_id=customer_id,
                system_prompt=system_prompt,
                knowledge_context=knowledge_context,  # §132
                confirmed_quote_id=confirmed_quote_id,
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
        run.output = {
            "content": result.content,
            "media": result.media,
            "shown_product_ids": result.shown_product_ids,
            "agent_version": getattr(agent, "version", 1),
            "model": self._alias_for(agent),
            "provider": getattr(agent, "provider", None) or "platform",
        }
        run.tokens_in = result.tokens_in
        run.tokens_out = result.tokens_out
        run.cost = estimate_cost(result.tokens_in, result.tokens_out)
        run.finished_at = _now()
        await session.flush()

        # §38/§158/P1-17: raw AI run output is NOT automatically persisted as
        # agent_inferred memory by default — doing so injects past chat outputs
        # into future knowledge contexts without fact verification. Verified facts
        # are stored through explicit domain events and memory extraction only.

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
        session: AsyncSession,
        tenant_id: uuid.UUID,
        agent_id: uuid.UUID,
        agent_kind: str | None = None,
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
        tools = list(rows.all())
        if agent_kind:
            from app.modules.ai.core.registry import AgentRegistry

            authorized = []
            for t in tools:
                if AgentRegistry.is_tool_authorized(agent_kind, t.name):
                    authorized.append(t)
                else:
                    logger.warning(
                        "ai.tool_isolation_unauthorized agent=%s kind=%s tool=%s",
                        agent_id,
                        agent_kind,
                        t.name,
                    )
            return authorized
        return tools

    @staticmethod
    async def _resolve_agent_version(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        agent: Agent,
        *,
        canary_chosen: bool,
    ) -> tuple[uuid.UUID | None, str, dict | None]:
        """Return (agent_version_id, version_source, tool_policy), and patch
        agent fields in-place.

        If a Deployment row exists, picks stable_version_id or candidate_version_id
        based on canary_chosen.  The agent's mutable row is left untouched in the
        database; only the in-memory instance is overridden for this run.

        The fallback policy is EXPLICIT, never silent: when no version wins,
        the mutable agent row runs and ``version_source`` records why
        (``fallback:<reason>`` into run.input, plus a log line) so an auditor
        can tell a canary-served answer from a row-served one. The third
        element is the winning version's tool policy — the Agent row has no
        policy of its own, so without a version the effective policy is None
        (registry authorization alone).
        """
        from app.modules.ai.models import AgentVersion, Deployment

        deployment = (
            await session.execute(
                select(Deployment).where(
                    Deployment.tenant_id == tenant_id,
                    Deployment.agent_id == agent.id,
                    Deployment.status == "active",
                )
            )
        ).scalar_one_or_none()
        if deployment is None:
            return None, "fallback:no_deployment", None

        version_id = (
            deployment.candidate_version_id
            if canary_chosen and deployment.candidate_version_id
            else deployment.stable_version_id
        )
        if version_id is None:
            return None, "fallback:no_version_selected", None

        version = (
            await session.execute(
                select(AgentVersion).where(
                    AgentVersion.tenant_id == tenant_id,
                    AgentVersion.id == version_id,
                    AgentVersion.status == "published",
                )
            )
        ).scalar_one_or_none()
        if version is None:
            logger.warning(
                "ai.version_fallback agent=%s version=%s reason=version_not_published",
                agent.id,
                version_id,
            )
            return None, "fallback:version_not_published", None

        # Override in-memory agent config for this run only (never flushed).
        if version.system_prompt is not None:
            agent.system_prompt = version.system_prompt
        if version.model is not None:
            agent.model = version.model
        if version.temperature is not None:
            agent.temperature = version.temperature
        if version.max_output_tokens is not None:
            agent.max_output_tokens = version.max_output_tokens
        if version.run_limits:
            agent.run_limits = version.run_limits
        return version.id, "deployment", (version.tool_policy or None)

    @staticmethod
    def _alias_for(agent: Agent) -> str:
        # Agent.model stores a gateway alias; if valid in ALIASES use it.
        if (agent.model or "") in ALIASES:
            return agent.model
        try:
            from app.modules.ai.core.registry import AgentRegistry

            defn = AgentRegistry.get_or_none(agent.kind)
            if defn and defn.default_model in ALIASES:
                return defn.default_model
        except Exception:
            pass
        return "fast"

    @staticmethod
    def _resolve_system_prompt(agent: Agent, override: str | None = None) -> str:
        """Resolve the system prompt: override > agent row > registry template > default."""
        if override:
            return override
        if agent.system_prompt:
            return agent.system_prompt
        # Fall back to registry definition if available
        try:
            from app.modules.ai.core.registry import AgentRegistry

            defn = AgentRegistry.get(agent.kind)
            if defn.system_prompt_template:
                return defn.system_prompt_template
        except (ValueError, Exception):  # noqa: BLE001
            pass
        return DEFAULT_SYSTEM_PROMPT

    async def _loop(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        agent: Agent,
        agent_tools: list[AgentTool],
        run: AgentRun,
        conversation_id: uuid.UUID | None,
        inbound_message_id: uuid.UUID | str | None = None,
        user_message: str,
        customer_id: uuid.UUID | None,
        system_prompt: str | None,
        knowledge_context: str | None = None,  # §132
        confirmed_quote_id: uuid.UUID | str | None = None,  # P1-10
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
                "content": self._resolve_system_prompt(agent, system_prompt),
            }
        ]
        # §132: knowledge context is injected as a SEPARATE user message,
        # not appended to the system prompt. This separates trusted
        # instructions from untrusted retrieved content, reducing the
        # prompt-injection surface.
        if knowledge_context:
            messages.append(
                {
                    "role": "user",
                    "content": f"[Knowledge base — untrusted context]\n{knowledge_context}",
                }
            )
        customer_image_url: str | None = None
        if conversation_id is not None:
            turns, image_key = await self._conversation_context(
                session,
                tenant_id,
                conversation_id,
                current_message=user_message,
            )
            messages.extend(turns)
            if image_key:
                # §7.1.3: the CURRENT turn rides the photo as a real content
                # part (the multimodal model reads image_url parts); older
                # images stay text markers so history cannot flood the prompt
                # with payloads.
                from app.core.storage import get_storage

                try:
                    customer_image_url = get_storage().signed_url(image_key)
                except Exception:  # noqa: BLE001 — vision is best-effort
                    logger.warning("ai.customer_image_sign_failed key=%s", image_key, exc_info=True)
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
                    messages.append(
                        {
                            "role": "user",
                            "content": "[Customer memories — untrusted context]\n" + mem_snippets,
                        }
                    )
            except Exception:  # noqa: BLE001 — memory is best-effort context
                logger.warning("ai.memory_search_failed customer=%s", customer_id, exc_info=True)

        if customer_image_url:
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_message},
                        {"type": "image_url", "image_url": {"url": customer_image_url}},
                    ],
                }
            )
        else:
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
            elapsed = datetime.now(UTC) - started_at
            if elapsed > max_wall_time:
                hit_limit = "max_wall_time"
                break
            remaining = (max_wall_time - elapsed).total_seconds()
            try:
                chat_result = await asyncio.wait_for(
                    self.gateway.chat(
                        session,
                        tenant_id,
                        alias=self._alias_for(agent),
                        messages=messages,
                        tools=tools_schema,
                        temperature=float(agent.temperature),
                        max_tokens=agent.max_output_tokens,
                        agent_id=agent.id,
                        run_id=run.id,
                    ),
                    timeout=remaining,
                )
            except TimeoutError:
                hit_limit = "max_wall_time"
                break
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
                "tool_calls": [_assistant_tool_call(tc) for tc in chat_result.tool_calls],
            }
            messages.append(assistant_msg)
            answered_ids: set[str] = set()
            for tc in chat_result.tool_calls:
                if len(tool_calls_made) >= max_tool_calls:
                    hit_limit = "max_tool_calls"
                    break
                outcome = await self._execute_tool(
                    session,
                    tenant_id,
                    run=run,
                    agent=agent,
                    agent_tools=agent_tools,
                    request=tc,
                    customer_id=customer_id,
                    conversation_id=conversation_id,
                    inbound_message_id=inbound_message_id,
                    customer_image_url=customer_image_url,
                    confirmed_quote_id=confirmed_quote_id,
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
                                "content": json.dumps({"skipped": "tool call limit reached"}),
                            }
                        )
                break
            content = chat_result.content or content

        if awaiting_approval:
            # run.status was set to WAITING_APPROVAL by _execute_tool;
            # §135/P1-9: provide a polite waiting message so customer does not get complete silence
            content = "تم تحويل طلبك لفريق العمل للمراجعة والموافقة وسنوافيك بالرد فور اعتماده."
            await session.flush()
            logger.warning("ai.run_awaiting_approval run=%s", run.id)
        elif hit_limit:
            run.status = "timeout"
            run.error = f"run limit hit: {hit_limit}"
            # §134: a run that hits its limit must not leave the conversation
            # in AI limbo — the customer would get silence. Record a durable
            # handover so a human picks it up.
            if conversation_id is not None:
                from app.modules.ai.handover import request_human_takeover

                await request_human_takeover(
                    session,
                    tenant_id,
                    conversation_id=conversation_id,
                    reason="failure",
                    note=f"run_limit:{hit_limit}",
                    run_id=run.id,
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
                from app.modules.ai.handover import request_human_takeover

                await request_human_takeover(
                    session,
                    tenant_id,
                    conversation_id=conversation_id,
                    reason="failure",
                    note="run_limit:max_steps",
                    run_id=run.id,
                )
            await session.flush()
            logger.warning("ai.run_limit_hit run=%s limit=max_steps", run.id)

        # §41 output guardrail — enforced HERE, not in the caller. It used to
        # live in the auto-reply hook, so any other entry point into the runner
        # (automation, a campaign, a future API) would have bypassed it
        # entirely. Withholding the content is what makes the gate real: a
        # caller that forgets to inspect the verdict still cannot send it.
        decision, reason = "allow", None

        # Grounding v1: controlled by the agent definition in the registry.
        # When enabled and the run used tools, every numeral in the reply
        # must trace to a tool fact (§12). ONE regeneration, tools disabled,
        # with a corrective instruction; failing again withholds the reply.
        defn = None
        try:
            from app.modules.ai.core.registry import AgentRegistry

            defn = AgentRegistry.get(agent.kind)
        except Exception:
            pass

        if content and tool_calls_made and defn and getattr(defn, "enforce_grounding", False):
            from app.modules.ai.agents.customer import grounding, ledger

            facts = ledger.facts_from_tool_calls(tool_calls_made)
            failure = grounding.check_grounding(content, facts) if facts else None
            if failure is not None:
                logger.warning("ai.grounding_failed run=%s detail=%s", run.id, failure)
                # §134's wall clock covers THIS call too. Only the first model
                # call was bounded by `remaining`, so a run that spent nearly all
                # of its budget getting an unsourced answer could then take an
                # UNLIMITED second one — the request that outlives the worker's
                # 5-minute stale-claim window, and the one that holds the
                # conversation lease and its transaction open past any bound the
                # limits claim to enforce.
                remaining = (max_wall_time - (datetime.now(UTC) - started_at)).total_seconds()
                regen_timed_out = False
                try:
                    regen = await asyncio.wait_for(
                        self.gateway.chat(
                            session,
                            tenant_id,
                            alias=self._alias_for(agent),
                            messages=[
                                *messages,
                                {"role": "assistant", "content": content},
                                {
                                    "role": "user",
                                    "content": grounding.CORRECTION_INSTRUCTION,
                                },
                            ],
                            tools=None,  # the correction must reuse gathered facts only
                            temperature=float(agent.temperature),
                            max_tokens=agent.max_output_tokens,
                            agent_id=agent.id,
                            run_id=run.id,
                        ),
                        timeout=remaining,
                    )
                except TimeoutError:
                    regen_timed_out = True
                    regen = None
                    logger.warning(
                        "ai.grounding_regen_deadline run=%s remaining=%.1fs", run.id, remaining
                    )
                except Exception:  # noqa: BLE001 — a provider blip hands over
                    logger.warning("ai.grounding_regen_error run=%s", run.id, exc_info=True)
                    regen = None
                if regen is not None:
                    tokens_in += regen.tokens_in
                    tokens_out += regen.tokens_out
                corrected = regen.content if regen is not None else None
                if regen_timed_out:
                    # Named for what actually happened. "grounding_failed" would
                    # tell the merchant the model kept inventing numbers, when in
                    # fact the run ran out of wall clock mid-correction.
                    content = None
                    decision, reason = "block", "wall_time_exhausted"
                elif corrected and grounding.check_grounding(corrected, facts) is None:
                    content = corrected
                else:
                    content = None
                    decision, reason = "block", "grounding_failed"

        if content:
            if defn is None:
                logger.error(
                    "ai.guardrail_fail_closed run=%s unknown_agent_kind=%s", run.id, agent.kind
                )
                content = None
                decision, reason = "block", "unknown_agent_kind"
            else:
                guardrail_profile = getattr(defn, "guardrail_profile", "customer")
                if guardrail_profile == "analytics":
                    verdict = analytics_guardrail().evaluate(
                        content, {"tool_results": tool_calls_made}
                    )
                else:
                    verdict = default_guardrail(require_tool_evidence=True).evaluate(
                        content, {"tool_results": tool_calls_made}
                    )
                decision, reason = verdict.decision, verdict.reason
                if decision != "allow":
                    logger.warning("ai.guardrail_%s run=%s reason=%s", decision, run.id, reason)
                    content = None

        # §13: resolve the media the model requested into deliverable
        # attachments SERVER-SIDE — only image ids crossed the model
        # boundary; URLs are minted here and capped at four per reply.
        media, shown_product_ids = await self._collect_media(session, tenant_id, tool_calls_made)

        return AgentRunResult(
            content=content,
            run_id=run.id,
            tool_calls_made=tool_calls_made,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            guardrail_decision=decision,
            guardrail_reason=reason,
            media=media,
            shown_product_ids=shown_product_ids,
            agent_version=getattr(agent, "version", 1),
            model=self._alias_for(agent),
            model_name=agent.model,
            provider=getattr(agent, "provider", None) or "platform",
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
                    "[customer sent a voice message; no transcript is available for it yet]"
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
            # P1-14/T16: Canonical safe-history: skip messages that were blocked,
            # failed, or undelivered so blocked content is never re-fed to the model.
            msg_status = (message.status or "").strip().lower()
            if msg_status in ("blocked", "failed", "undelivered", "rejected"):
                continue
            outbound = message.direction == "outbound"
            if outbound and (
                message.sender_type == "system" or msg_status in _UNDELIVERED_OUTBOUND_STATUSES
            ):
                continue
            content = message.body or voice.get(message.id) or AgentRunner._media_marker(message)
            if not content:
                continue
            turns.append({"role": "assistant" if outbound else "user", "content": content})
        if (
            current_message is not None
            and turns
            and turns[-1]["role"] == "user"
            and turns[-1]["content"].strip() == current_message.strip()
        ):
            turns.pop()
        return turns

    @staticmethod
    async def _conversation_context(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        conversation_id: uuid.UUID,
        *,
        current_message: str | None = None,
    ) -> tuple[list[dict], str | None]:
        """History turns plus the newest inbound photo's storage key (§7.1.3).

        One method on purpose: the boundary ratchet counts import NODES
        (tests/test_module_boundaries.py), so the turns and the image lookup
        share this single lazy ConversationService import, and the attachment
        query rides the module-scope conversations-models import above.
        """
        # Lazy import: conversations module owns the message table.
        from app.modules.conversations.service import ConversationService

        history = await ConversationService.list_messages(
            session, tenant_id, conversation_id, limit=HISTORY_MESSAGES
        )
        spoken_ids = [m.id for m in history if not m.body and m.direction == "inbound"]
        rows = await ConversationService.audio_transcripts(session, tenant_id, spoken_ids)
        voice = AgentRunner._voice_turns(rows)
        turns = AgentRunner._provider_turns(history, voice=voice, current_message=current_message)

        image_key: str | None = None
        for message in reversed(history):
            if message.direction != "inbound":
                continue
            row = (
                await session.execute(
                    select(_conversations_models.Attachment.storage_key)
                    .where(
                        _conversations_models.Attachment.tenant_id == tenant_id,
                        _conversations_models.Attachment.message_id == message.id,
                        _conversations_models.Attachment.mime_type.like("image/%"),
                        _conversations_models.Attachment.storage_key.is_not(None),
                        # A failed scan leaves the storage key behind (media.py
                        # writes it before it knows the object is durable), and
                        # MediaService itself refuses such a row. Sending it
                        # anyway would sign a URL for an object that was never
                        # safely stored and hand it to an external provider.
                        _conversations_models.Attachment.scan_status.in_(
                            ["stored", "scanned"]
                        ),
                        _conversations_models.Attachment.processing_status != "failed",
                    )
                    .order_by(_conversations_models.Attachment.created_at.desc())
                    .limit(1)
                )
            ).first()
            if row is not None:
                image_key = row.storage_key
            break  # only the NEWEST inbound message's photo rides the turn
        return turns, image_key

    @staticmethod
    async def _collect_media(
        session: AsyncSession,
        tenant_id: uuid.UUID,
        tool_calls_made: list[dict],
    ) -> tuple[list[dict], list[str]]:
        """Server-side media resolution for the §13 photo-reply behavior.

        resolve_product_media crossed the model boundary as image IDS only;
        this maps them back to deliverable ``{image_id, image_url, alt}``
        through the tools module's existing catalog access, caps the batch
        at four, and gathers every product id the run showed or referenced
        for the agent's shown-items state.
        """
        from app.modules.ai.tools import media_payload_for_ids

        image_ids: list[str] = []
        shown: list[str] = []
        for call in tool_calls_made:
            if call.get("status") != "ok":
                continue
            result = call.get("result") or {}
            # find_product_by_image candidates are NOT shown to the customer
            # until the agent explicitly calls resolve_product_media for one.
            # Recording them here would inflate shown_product_ids and bias
            # the deduplication logic in subsequent runs.
            if call.get("name") != "resolve_product_media":
                continue
            product_id = (call.get("args") or {}).get("product_id")
            if product_id and str(product_id) not in shown:
                shown.append(str(product_id))
            for item in result.get("media") or []:
                media_id = item.get("image_id")
                if media_id and media_id not in image_ids:
                    image_ids.append(media_id)
        media = await media_payload_for_ids(session, tenant_id, image_ids[:4])
        return media, shown

    async def _execute_tool(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        run: AgentRun,
        agent: Agent | None = None,
        agent_tools: list[AgentTool],
        request: ToolCallRequest,
        customer_id: uuid.UUID | None = None,
        conversation_id: uuid.UUID | None = None,
        inbound_message_id: uuid.UUID | str | None = None,
        customer_image_url: str | None = None,
        confirmed_quote_id: uuid.UUID | str | None = None,  # P1-10
    ) -> dict[str, Any]:
        """Run one requested tool call under the agent's policy; record the row.

        §132: HIGH-risk tools (§15) require a durable human approval BEFORE
        execution — the run suspends as WAITING_APPROVAL. The tool's context
        pins the conversation's customer server-side (§132 scope binding).

        §15-16: idempotency — a call that EXECUTED claims a key (semantic for
        side-effecting tools, per-run for reads), so a retried run or replayed
        event that re-issues it finds the prior ToolCall row and returns its
        result without executing the handler twice. See
        compute_tool_idempotency_key for what does NOT claim one.
        """
        from app.modules.ai.tools import get_tool

        # §15-16: idempotency pre-check. If this exact call already EXECUTED,
        # return the prior result and do not run the handler again. The unique
        # constraint on (tenant_id, idempotency_key) makes the check-then-insert
        # atomic under concurrent retries.
        #
        # The key is probed as if this call will execute, and RE-computed with the
        # real status before the insert — see compute_tool_idempotency_key for why
        # a parked (awaiting_approval) row must not claim one.
        spec_for_key = get_tool(request.name)
        idempotency_probe = compute_tool_idempotency_key(
            risk_level=spec_for_key.risk_level if spec_for_key else "LOW",
            conversation_id=conversation_id,
            inbound_message_id=inbound_message_id,
            run_id=run.id,
            tool_call_id=request.id,
            tool_name=request.name,
            arguments=request.arguments,
            status="ok",
        )
        prior = (
            await session.execute(
                select(ToolCall).where(
                    ToolCall.tenant_id == tenant_id,
                    ToolCall.idempotency_key == idempotency_probe,
                )
            )
        ).scalar_one_or_none()
        if prior is not None and prior.result is not None and prior.status == "ok":
            logger.info(
                "ai.tool_call_idempotent_skip run=%s tool=%s key=%s",
                run.id,
                request.name,
                idempotency_probe,
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

        from app.modules.ai.core.registry import AgentRegistry

        agent_kind = agent.kind if agent else None

        if agent_kind and not AgentRegistry.is_tool_authorized(agent_kind, request.name):
            status = "denied"
            error = f"tool '{request.name}' is not authorized for agent kind '{agent_kind}'"
        elif agent_tool is None:
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

                    tool_context: dict[str, str | None] | None = None
                    if "context" in inspect.signature(spec.handler).parameters:
                        tool_context = {
                            "customer_id": str(customer_id) if customer_id else None,
                            "conversation_id": (str(conversation_id) if conversation_id else None),
                        }
                        if customer_image_url:
                            # §12/§132: the customer's photo is server-bound —
                            # the tool reads it from here, never from args.
                            tool_context["customer_image"] = customer_image_url
                        if confirmed_quote_id:
                            # P1-10: the conversation's confirmed quote — bound
                            # by the turn coordinator from the customer's own
                            # code message, never from model arguments.
                            tool_context["confirmed_quote_id"] = str(confirmed_quote_id)
                        kwargs["context"] = tool_context
                    # §135: HIGH-risk tools suspend the run until a human
                    # approves. The approval row is durable — the run resumes
                    # (or dies) on the decision. Phase-aware (P1-10): the
                    # create_order PROPOSAL runs inline; only the confirmed-
                    # quote execution parks.
                    from app.modules.ai.approvals import ApprovalService
                    from app.modules.ai.tools import requires_approval

                    if await requires_approval(spec, tool_context):
                        # §135 + G-02: the approval is bound to THESE arguments.
                        # The payload recorded on the request is what a human
                        # approved, and the resume must present the identical
                        # payload — otherwise it is not the action that was
                        # approved, whatever the action name says.
                        #
                        # The signed image URL is the one volatile piece: it is
                        # re-minted with a fresh expiry on every run, so
                        # keeping it in the payload would make the resume's
                        # hash differ from the grant's and strand the flow.
                        # It is transport, not the decision — excluded.
                        approval_args = {k: v for k, v in kwargs.items() if k != "context"}
                        if tool_context is not None:
                            approval_args["context"] = {
                                k: v
                                for k, v in tool_context.items()
                                if k != "customer_image"
                            }
                        approval_payload = {"arguments": approval_args}
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
                                session,
                                conversation_id,
                                since=(granted.decided_at or granted.created_at),
                            )
                        ):
                            granted = None
                        if granted is not None:
                            await ApprovalService.consume(session, granted)
                            # The savepoint wraps the HANDLER ONLY: if it fails,
                            # its partial writes roll back but the approval
                            # stays consumed — a retry needs a fresh human
                            # grant instead of silently re-using this one.
                            async with session.begin_nested():
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
                        # Same containment for the no-approval path: a failing
                        # tool must not poison the run's transaction — the
                        # failed ToolCall row below has to be writable.
                        async with session.begin_nested():
                            result = await spec.handler(session, tenant_id, **kwargs)
                except PydanticValidationError as exc:
                    status = "error"
                    error = f"invalid tool arguments: {exc.errors()[0].get('msg', str(exc))}"
                except DomainError as exc:
                    # Designed outcome: a tool MEANT to say this (insufficient
                    # stock, unknown id, duplicate SKU). The message is data
                    # the model may act on — it never carries internals.
                    status = "error"
                    error = str(exc)
                except Exception:
                    # Unexpected failure. The exception text may carry SQL
                    # fragments, connection strings, filesystem paths, keys
                    # or provider bodies — NONE of it enters the model's
                    # context; the model gets the fixed generic outcome and
                    # the full traceback goes to the logs for a human.
                    status = "error"
                    error = "tool failed unexpectedly"
                    logger.exception(
                        "ai tool call failed",
                        extra={"tool": request.name, "run_id": str(run.id)},
                    )
                else:
                    duration_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
        # The key the audit row claims. A call that never executed (parked on an
        # approval, or denied) claims none — that is what lets the approved
        # resume write its own row under the same semantic key.
        idempotency_key = compute_tool_idempotency_key(
            risk_level=spec_for_key.risk_level if spec_for_key else "LOW",
            conversation_id=conversation_id,
            inbound_message_id=inbound_message_id,
            run_id=run.id,
            tool_call_id=request.id,
            tool_name=request.name,
            arguments=request.arguments,
            status=status,
        )
        try:
            # The savepoint mirrors the ProcessedEvent consumer-inbox pattern:
            # a loser of the (tenant_id, idempotency_key) insert race rolls its
            # own row back without poisoning the run's transaction.
            async with session.begin_nested():
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
        except IntegrityError:
            # Lost the insert race — only EXECUTED rows claim a key, so the
            # winner is a call that actually performed the side effect, and its
            # outcome is the honest answer. The conversation lease makes this
            # unreachable for two CONCURRENT conversation runs; a duplicate
            # delivery, or a conversation-less caller with no lease, is where
            # the race lives.
            prior = (
                await session.execute(
                    select(ToolCall).where(
                        ToolCall.tenant_id == tenant_id,
                        ToolCall.idempotency_key == idempotency_key,
                    )
                )
            ).scalar_one()
            return {
                "name": prior.name,
                "status": prior.status,
                "error": prior.error,
                "result": prior.result,
            }

        if status == "denied":
            result = {"error": error}
        elif status == "error":
            result = {"error": error or "tool failed"}
        # `args` rides the outcome so downstream consumers (grounding reads
        # create_order quantities, media collection reads product ids) never
        # re-query the ToolCall row.
        return {
            "name": request.name,
            "status": status,
            "error": error,
            "result": result,
            "args": request.arguments or {},
        }
