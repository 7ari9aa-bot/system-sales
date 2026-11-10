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
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from app.core.config import get_settings
from app.core.errors import DomainError, ExternalProviderError, NotFoundError
from app.modules.ai.constants import (
    VOICE_ECHO_SENTINEL,
    VOICE_NO_TRANSCRIPT_MARKER_PREFIX,
    VOICE_TURN_MARKER_PREFIX,
)
from app.modules.ai.gateway import (
    ALIASES,
    AIBudgetFallbackRequested,
    AIGateway,
    estimate_cost,
)
from app.modules.ai.guardrails import analytics_guardrail, default_guardrail, screen_inbound
from app.modules.ai.models import Agent, AgentRun, AgentTool, ToolCall
from app.modules.ai.multimodal import (
    _assistant_tool_call,
    _customer_user_content,
    _omni_audio_content_part,
)
from app.modules.ai.prompts import AWAITING_APPROVAL_MESSAGE, DEFAULT_SYSTEM_PROMPT
from app.modules.ai.providers import ToolCallRequest
from app.modules.ai.tools import tool_to_openai_schema  # noqa: E402
from app.modules.ai.usage import record_usage  # noqa: E402
from app.modules.conversations import models as _conversations_models  # noqa: E402,F401
from app.modules.conversations.voice import omni_audio_format  # noqa: E402

# Importing the conversations models registers their tables in the shared
# metadata so agent_runs' FK to conversations.id resolves even when the AI
# runtime is used in a process that never touched the conversations module.

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 5
_FINAL_STEP_INSTRUCTION = (
    "دي آخر خطوة: مفيش أدوات تاني. اكتب دلوقتي ردك للعميل بناءً على اللي "
    "لقيته بس. لو بحثت ومفيش نتيجة، قول له بصراحة إن اللي سأل عنه مش موجود "
    "دلوقتي واعرض اللي المتجر بيبيعه. متحوّلش ومتسكتش."
)
HISTORY_MESSAGES = 10

# Outbound rows whose send did not land: "failed" is terminal and "unknown" is
# a result that went missing mid-flight (conversations/models.py:172). Neither
# is a turn the customer read.
_UNDELIVERED_OUTBOUND_STATUSES = frozenset({"failed", "unknown"})
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


def _canary_chosen(
    canary_percent: int,
    conversation_id: uuid.UUID | None,
    inbound_message_id: uuid.UUID | str | None,
    agent_id: uuid.UUID,
) -> bool:
    """Deterministic canary bucket for one run.

    Conversations bucket by their own id (the same conversation must not flip
    between stable and candidate across retries). Conversation-less agents —
    the analyst today, future job/API agents — bucket by the inbound event id
    when the caller carries one. With NEITHER id there is nothing stable to
    bucket by: seeding on the agent id put every run of that agent in the
    SAME bucket, so its canary was all-or-nothing and §169's metric
    comparison never had a split. A run-scoped bucket (fresh uuid per run)
    splits statistically and is the correct unit for one-shot reports — a
    retried report is a new run, and its idempotency is the caller's concern,
    not the version router's.
    """
    if canary_percent <= 0:
        return False
    if conversation_id is not None:
        seed: bytes = conversation_id.bytes
    elif inbound_message_id is not None:
        seed = str(inbound_message_id).encode()
    else:
        seed = uuid.uuid4().bytes
    return int(hashlib.md5(seed).hexdigest(), 16) % 100 < canary_percent


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


class _PreStageOutcome(NamedTuple):
    """What the pre-loop per-kind hook stage produced.

    ``failure_reason`` is a short stable token (``hook_not_resolved``,
    ``context_builder_failed``, ``pre_run_hook_failed``) for the guardrail
    verdict and run.error; None means the stage passed.
    """

    context_lines: str | None
    failure_reason: str | None = None
    failure_detail: str | None = None


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
        # System-owned conversation facts (customer name, shown items, vision
        # results) — injected under their OWN label, never wearing the
        # knowledge one: a customer name is not a retrieved snippet, and a
        # knowledge-failure turn would otherwise look like it served one.
        context_lines: str | None = None,
        # SI chat: bounded prior turns, server-built from ai_chat_messages.
        # Narrative context only — never numeric authority; facts are
        # re-queried per turn by the deterministic tools.
        history: list[dict[str, str]] | None = None,
        # The coordinator's server-side photo verdict for this turn: the
        # classified kind gates find_product_by_image (the model cannot
        # re-propose a kind the server already refused) and a precomputed
        # MatchResult is REUSED instead of re-running the paid pipeline.
        vision_state: dict | None = None,
    ) -> AgentRunResult:
        agent = await self._load_agent(session, tenant_id, agent_id)
        # Fail BEFORE the first paid model call when the kind has no definition:
        # an unregistered kind used to be discovered only after the loop, so a
        # deployment typo spent money and then blocked the answer.
        from app.modules.ai.core.registry import AgentRegistry

        definition = AgentRegistry.get_or_none(agent.kind)
        if definition is None:
            # The block itself is free (nothing was paid), but the attempt must
            # stay AUDIT-VISIBLE: a run row with no trace is how a deployment
            # typo hides as "the agent is quiet". The full run-row metadata
            # (canary, version) needs the definition, so this row is minimal —
            # status vocabulary is the run table's own ("running | succeeded |
            # failed | ...").
            logger.error("ai.unknown_agent_kind agent=%s kind=%s", agent.id, agent.kind)
            blocked_run = AgentRun(
                tenant_id=tenant_id,
                agent_id=agent.id,
                conversation_id=conversation_id,
                status="failed",
                input={
                    "message": user_message,
                    "customer_id": str(customer_id) if customer_id else None,
                    "agent_version": getattr(agent, "version", 1),
                    "model": self._alias_for(agent),
                    "model_name": agent.model,
                },
                error="unknown_agent_kind",
                tokens_in=0,
                tokens_out=0,
                started_at=_now(),
                finished_at=_now(),
            )
            session.add(blocked_run)
            await session.flush()
            return AgentRunResult(
                content=None,
                run_id=blocked_run.id,
                guardrail_decision="block",
                guardrail_reason="unknown_agent_kind",
            )
        agent_tools = await self._load_agent_tools(
            session, tenant_id, agent_id, agent_kind=agent.kind
        )

        # §169: canary deployment decision — deterministic per conversation so
        # the same conversation does not flip between stable and candidate
        # across retries. Without AgentVersion rows the version itself cannot
        # switch yet, but the decision is recorded and the gate is live.
        canary_percent = 0
        try:
            from app.modules.ai.evaluation import AIEvaluationService

            canary_percent = await AIEvaluationService.get_canary_traffic_percent(
                session, tenant_id, agent_id
            )
        except Exception:
            logger.warning("ai.canary_check_failed agent=%s", agent_id, exc_info=True)
        canary_chosen = _canary_chosen(
            canary_percent, conversation_id, inbound_message_id, agent.id
        )

        agent_version_id, version_source, version_tool_policy = await self._resolve_agent_version(
            session, tenant_id, agent, canary_chosen=canary_chosen
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
                "definition_version": definition.definition_version,
                "agent_version_id": str(agent_version_id) if agent_version_id else None,
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
            # Per-kind extensibility hooks (Part B): context_builder and
            # pre_run_hook run BEFORE the model loop; resolution of ALL
            # declared hooks (post_run_hook included) is fail-closed here, so
            # an unresolvable hook fails the run before any paid model call
            # instead of being silently skipped.
            run_ctx: dict[str, Any] = {
                "run_id": run.id,
                "conversation_id": conversation_id,
                "inbound_message_id": inbound_message_id,
                "customer_id": customer_id,
                "knowledge_context": knowledge_context,
                "context_lines": context_lines,
            }
            pre = await self._run_pre_stage(
                session,
                tenant_id,
                agent=agent,
                definition=definition,
                run=run,
                run_ctx=run_ctx,
                context_lines=context_lines,
            )
            if pre.failure_reason is not None:
                run.status = "failed"
                run.error = f"{pre.failure_reason}: {(pre.failure_detail or '')[:500]}"
                run.finished_at = _now()
                await session.flush()
                logger.warning(
                    "ai.%s run=%s kind=%s detail=%s",
                    pre.failure_reason,
                    run.id,
                    agent.kind,
                    (pre.failure_detail or "")[:500],
                )
                # Contained, like unknown_agent_kind: a broken kind hook must
                # never crash the worker loop.
                return AgentRunResult(
                    content=None,
                    run_id=run.id,
                    guardrail_decision="block",
                    guardrail_reason=pre.failure_reason,
                )
            context_lines = pre.context_lines
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
                context_lines=context_lines,
                history=history,
                vision_state=vision_state,
            )
        except Exception as exc:
            run.status = "failed"
            if isinstance(exc, ExternalProviderError):
                # The provider body can echo request content — the durable run
                # row carries the category, the traceback carries the detail.
                run.error = f"{type(exc).__name__}: model provider call failed"
            else:
                run.error = str(exc)
            # §42 integrity: the cap measures ai_usage, which used to be written
            # only when a run SUCCEEDED — a tenant hammering a failing/fallback
            # provider burned real billed tokens (the calls that landed inside
            # the doomed run) that never counted against the cap. The loop
            # keeps run.tokens_* current per call, so record what was billed.
            # Contained: if the loop died on a DB-level error the session is
            # unusable and this write would raise on its own — masking the
            # original failure. The usage record is lost there, the error is not.
            if run.tokens_in or run.tokens_out:
                try:
                    await record_usage(
                        session,
                        tenant_id,
                        agent_id=agent.id,
                        tokens_in=run.tokens_in,
                        tokens_out=run.tokens_out,
                        cost=estimate_cost(run.tokens_in, run.tokens_out),
                    )
                except Exception:  # noqa: BLE001 — bookkeeping must not mask the failure
                    logger.warning("ai.failed_run_usage_unrecorded run=%s", run.id, exc_info=True)
            run.finished_at = _now()
            await session.flush()
            if isinstance(exc, DomainError):
                raise
            raise DomainError(f"agent run failed: {exc}") from exc
        finally:
            if lease_cm is not None:
                await lease_cm.__aexit__(None, None, None)

        # Per-kind post_run_hook: runs after the loop, BEFORE the run row is
        # finalized. Its produced content is re-screened by the SAME output
        # guardrail normal content passes (inside _run_post_stage); a hook
        # failure keeps the ORIGINAL result and is recorded in run.output.
        result, post_hook_note = await self._run_post_stage(
            session, tenant_id, agent=agent, definition=definition, run=run, result=result
        )

        if run.status == "running":
            run.status = "succeeded"
        run.output = {
            "content": result.content,
            "media": result.media,
            "shown_product_ids": result.shown_product_ids,
            "agent_version": getattr(agent, "version", 1),
            "definition_version": definition.definition_version,
            "agent_version_id": str(agent_version_id) if agent_version_id else None,
            "model": self._alias_for(agent),
            "model_name": result.model_name,
            "provider": getattr(agent, "provider", None) or "platform",
        }
        if post_hook_note is not None:
            run.output["post_hook_error"] = post_hook_note
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
    def _merge_context_lines(context_lines: str | None, lines: Any) -> str:
        """Append per-kind hook lines to the system-owned context.

        Each line is trimmed and length-capped so a hook cannot flood the
        prompt; the merged string rides the existing
        ``[Conversation context — system-owned facts]`` channel.
        """
        merged = list(context_lines.splitlines()) if context_lines else []
        for line in lines:
            text = str(line).strip()
            if text:
                merged.append(text[:500])
        return "\n".join(merged)

    async def _run_pre_stage(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        agent: Agent,
        definition: Any,
        run: AgentRun,
        run_ctx: dict[str, Any],
        context_lines: str | None,
    ) -> _PreStageOutcome:
        """Resolve ALL declared per-kind hooks (fail-closed), then run the
        pre-loop stages: context_builder first, then pre_run_hook.

        Resolution of every declared hook — post_run_hook included — happens
        here, before any paid model call: an unresolvable hook fails the run
        with ``hook_not_resolved`` rather than being silently skipped at its
        own stage. Stage exceptions are contained: the run is marked failed
        with a stable reason token and the caller returns a blocked result
        (a broken kind hook must never crash the worker loop). The
        pre_run_hook's returned dict merges into the run context — its
        entries ride the system-owned context lines channel.
        """
        from app.modules.ai.core.registry import HOOK_FIELDS, resolve_definition_hook

        for hook_field in HOOK_FIELDS:
            if not getattr(definition, hook_field, None):
                continue
            try:
                resolve_definition_hook(definition, hook_field)
            except ValueError as exc:
                logger.warning(
                    "ai.hook_not_resolved kind=%s run=%s field=%s detail=%s",
                    definition.kind,
                    run.id,
                    hook_field,
                    exc,
                )
                return _PreStageOutcome(context_lines, "hook_not_resolved", str(exc))

        builder = resolve_definition_hook(definition, "context_builder")
        if builder is not None:
            try:
                lines = await builder(session, tenant_id, agent, run_ctx)
            except Exception:
                logger.warning(
                    "ai.context_builder_failed kind=%s run=%s",
                    definition.kind,
                    run.id,
                    exc_info=True,
                )
                return _PreStageOutcome(context_lines, "context_builder_failed", None)
            if lines:
                context_lines = self._merge_context_lines(context_lines, lines)

        run_ctx["context_lines"] = context_lines
        pre_hook = resolve_definition_hook(definition, "pre_run_hook")
        if pre_hook is not None:
            try:
                extra = await pre_hook(session, tenant_id, agent, run_ctx)
            except Exception:
                logger.warning(
                    "ai.pre_run_hook_failed kind=%s run=%s",
                    definition.kind,
                    run.id,
                    exc_info=True,
                )
                return _PreStageOutcome(context_lines, "pre_run_hook_failed", None)
            if extra:
                context_lines = self._merge_context_lines(
                    context_lines, [f"{k}: {v}" for k, v in extra.items()]
                )
        return _PreStageOutcome(context_lines, None, None)

    async def _run_post_stage(
        self,
        session: AsyncSession,
        tenant_id: uuid.UUID,
        *,
        agent: Agent,
        definition: Any,
        run: AgentRun,
        result: AgentRunResult,
    ) -> tuple[AgentRunResult, str | None]:
        """Run the declared post_run_hook; return (final result, output note).

        Contract: the hook may return None (keep the original result), a bare
        string (replaces result.content) or a full AgentRunResult. Hook-produced
        content is RE-SCREENED by the same output guardrail normal content
        passes — unguarded hook text is withheld, never delivered. A hook
        exception keeps the ORIGINAL result (a broken hook must not destroy a
        good answer); the caller records the returned note in run.output.
        (Resolution was already fail-closed in the pre-stage, so the lookup
        here is a cache hit.)
        """
        from app.modules.ai.core.registry import resolve_definition_hook

        if not getattr(definition, "post_run_hook", None):
            return result, None
        hook = resolve_definition_hook(definition, "post_run_hook")
        if hook is None:
            return result, None
        try:
            produced = await hook(session, tenant_id, agent, run, result)
        except Exception as exc:
            logger.warning(
                "ai.post_run_hook_failed kind=%s run=%s",
                definition.kind,
                run.id,
                exc_info=True,
            )
            return result, f"{type(exc).__name__}: {str(exc)[:500]}"
        if produced is None:
            return result, None
        if isinstance(produced, str):
            modified = replace(result, content=produced)
        elif isinstance(produced, AgentRunResult):
            # Spend accounting stays tied to the MAIN loop: a hook that made
            # its own model call must fold those tokens into the result ITSELF
            # (the SI coverage regen does exactly that) — the gateway writes
            # only an audit ModelCall row, not ai_usage. A hook returning a
            # bare AgentRunResult carries default ZERO tokens — copying them
            # onto the run row would silently erase the run's real cost.
            # Model provenance likewise stays the loop's unless the hook
            # explicitly named one.
            modified = replace(
                produced,
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
                model_name=produced.model_name or result.model_name,
            )
        else:
            logger.warning(
                "ai.post_run_hook_bad_return kind=%s run=%s type=%s",
                definition.kind,
                run.id,
                type(produced).__name__,
            )
            return result, f"post_run_hook returned unsupported type {type(produced).__name__}"
        if modified.content and modified.content != result.content:
            decision, reason = self._screen_output(
                definition, modified.content, modified.tool_calls_made
            )
            if decision != "allow":
                logger.warning(
                    "ai.post_hook_guardrail_%s run=%s reason=%s", decision, run.id, reason
                )
                modified = replace(
                    modified, content=None, guardrail_decision=decision, guardrail_reason=reason
                )
            else:
                modified = replace(modified, guardrail_decision="allow", guardrail_reason=None)
        return modified, None

    @staticmethod
    def _screen_output(
        defn: Any, content: str, tool_calls_made: list[dict]
    ) -> tuple[str, str | None]:
        """The §41 output guardrail in ONE place: normal loop content and
        post-hook content are screened by literally the same logic."""
        profile = getattr(defn, "guardrail_profile", "customer")
        if profile == "analytics":
            verdict = analytics_guardrail().evaluate(content, {"tool_results": tool_calls_made})
        else:
            verdict = default_guardrail(require_tool_evidence=True).evaluate(
                content, {"tool_results": tool_calls_made}
            )
        return verdict.decision, verdict.reason

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

        # `fully_rollout` is a LIVE deployment, not a dead one: it is the state
        # the evaluation service writes when a canary reached 100% and its
        # candidate was promoted to stable. Excluding it used to send every
        # post-canary run back to the mutable settings fallback — the exact
        # un-pinned execution the version platform exists to prevent. Only
        # `rolled_back` (traffic deliberately withdrawn) falls through.
        deployment = (
            await session.execute(
                select(Deployment).where(
                    Deployment.tenant_id == tenant_id,
                    Deployment.agent_id == agent.id,
                    Deployment.status.in_(("active", "fully_rollout")),
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

        # Override in-memory agent config for this run only. set_committed_value
        # rewrites the attribute's LOADED state without creating pending
        # history — a plain assignment would dirty the session-attached row and
        # the next flush (the AgentRun insert) would write the snapshot's
        # prompt/model/limits back onto the mutable agents table, silently
        # reverting every merchant edit while a deployment is active.
        if version.system_prompt is not None:
            set_committed_value(agent, "system_prompt", version.system_prompt)
        if version.persona_prompt is not None:
            set_committed_value(agent, "persona_prompt", version.persona_prompt)
        if version.model is not None:
            set_committed_value(agent, "model", version.model)
        if version.temperature is not None:
            set_committed_value(agent, "temperature", version.temperature)
        if version.max_output_tokens is not None:
            set_committed_value(agent, "max_output_tokens", version.max_output_tokens)
        if version.run_limits:
            set_committed_value(agent, "run_limits", version.run_limits)
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

    @staticmethod
    def _compose_system_content(agent: Agent, override: str | None = None) -> str:
        """Base rules first, store persona last.

        ``system_prompt`` carries the canonical instructions and prohibitions;
        ``persona_prompt`` is the merchant-owned voice (agent name, tone, store
        name). Persona rides LAST so it colors the reply without diluting the
        rules, and either half may be empty on its own. This composition is
        the ONLY place the two prompts meet — the owner console edits each
        through its own field and never needs to know about the other.
        """
        base = AgentRunner._resolve_system_prompt(agent, override).strip()
        persona = (getattr(agent, "persona_prompt", None) or "").strip()
        if persona:
            return f"{base}\n\n{persona}"
        return base

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
        context_lines: str | None = None,
        history: list[dict[str, str]] | None = None,
        vision_state: dict | None = None,
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
                "content": self._compose_system_content(agent, system_prompt),
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
        if context_lines:
            # System-OWNED facts (customer identity, shown items, vision
            # results), not retrieved content: they carry their own label so
            # a knowledge failure cannot dress a name up as a snippet.
            messages.append(
                {
                    "role": "user",
                    "content": f"[Conversation context — system-owned facts]\n{context_lines}",
                }
            )
        if history:
            # SI chat: bounded prior turns, server-built from ai_chat_messages.
            # Narrative context only — never numeric authority; facts are
            # re-queried per turn by the deterministic tools.
            messages.extend(history)
        customer_image_url: str | None = None
        customer_audio: tuple[str, str] | None = None  # (mime, storage_key)
        if conversation_id is not None:
            turns, image_key, audio_media = await self._conversation_context(
                session,
                tenant_id,
                conversation_id,
                current_message=user_message,
                inbound_message_id=inbound_message_id,
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
            if audio_media and get_settings().ai_voice_audio_input:
                # Direct Omni input is opt-in and requires a scanner-cleared,
                # supported-format attachment. The audio bytes are read from
                # our own Supabase object store and encoded as a data URL; the
                # expiring channel URL never reaches the provider.
                customer_audio = audio_media
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

        customer_audio_part: dict[str, str] | None = None
        if customer_audio:
            audio_mime, audio_key = customer_audio
            audio_format = omni_audio_format(audio_mime)
            if audio_format is not None:
                from app.core.storage import get_storage

                # Keep one audio turn bounded well below the 25 MiB ingest cap:
                # base64 adds ~33%, and oversized bodies are a provider failure
                # (not a reason to retry/dead-letter an otherwise normal turn).
                try:
                    audio_blob = await get_storage().read_object(
                        audio_key, max_bytes=10 * 1024 * 1024
                    )
                    customer_audio_part = _omni_audio_content_part(audio_mime, audio_blob.data)
                except Exception:  # noqa: BLE001 — audio input is best-effort, never lose the turn
                    logger.warning(
                        "ai.customer_audio_read_failed key=%s — voice was not sent",
                        audio_key,
                        exc_info=True,
                    )
                if customer_audio_part is None:
                    logger.warning(
                        "ai.customer_audio_unsupported_format key=%s mime=%s",
                        audio_key,
                        audio_mime,
                    )
            else:
                logger.warning(
                    "ai.customer_audio_unsupported_format key=%s mime=%s",
                    audio_key,
                    audio_mime,
                )

        user_content = _customer_user_content(
            user_message,
            image_url=customer_image_url,
            audio_part=customer_audio_part,
        )
        messages.append({"role": "user", "content": user_content})

        tools_schema = [
            tool_to_openai_schema(spec)
            for spec in (tool for tool in map(_tool_for, agent_tools) if tool is not None)
        ] or None

        tool_calls_made: list[dict] = []
        tokens_in = 0
        tokens_out = 0
        content: str | None = None
        # The concrete model the provider says answered — provenance, not the
        # alias the run asked for. The alias stays in `model`.
        raw_model_name: str | None = None

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
            if customer_audio_part:
                chat_alias = get_settings().ai_voice_model_alias
            else:
                chat_alias = self._alias_for(agent)
            # The LAST allowed step is an answer step: no tools. A model that keeps
            # searching ("no match" -> retry -> retry ...) would otherwise spend the whole
            # budget, never write a word, and the run would end as a silent handover.
            # With tools withdrawn it has to tell the customer what it found, which for an
            # empty search is exactly the right answer ("we don't carry that").
            final_step = _iteration == limits["max_steps"] - 1 and _iteration > 0
            if final_step:
                messages.append({"role": "system", "content": _FINAL_STEP_INSTRUCTION})
            try:
                chat_result = await asyncio.wait_for(
                    self.gateway.chat(
                        session,
                        tenant_id,
                        alias=chat_alias,
                        messages=messages,
                        tools=None if final_step else tools_schema,
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
                # Direct audio contains the customer's actual voice and must
                # not be sent to the text-only cheap fallback. Fail closed:
                # hand over rather than stripping the audio and guessing.
                if customer_audio_part:
                    hit_limit = "audio_budget_fallback_unavailable"
                    break
                # §42: cap exhausted, policy says downgrade — retry this step
                # on the "fallback" alias (the cheap model). If the fallback
                # alias is what just failed, stop and hand over instead of
                # looping the same exhausted budget. The retry is bounded by
                # the SAME remaining wall clock as the primary call — an
                # unbounded fallback was a way for the run to outlive the
                # budget the limits claim to enforce.
                if self._alias_for(agent) != "fallback":
                    try:
                        chat_result = await asyncio.wait_for(
                            self.gateway.chat(
                                session,
                                tenant_id,
                                alias="fallback",
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
                        # The retry re-enters reserve_budget, which re-derives
                        # the same exhausted cap and raises AGAIN — from inside
                        # this handler it would escape as a generic run error,
                        # dead-letter the message, and never hand over. The
                        # fallback tier is spent: hand over like block does.
                        hit_limit = "budget_fallback_exhausted"
                        break
                else:
                    hit_limit = "budget_fallback_exhausted"
                    break
            raw_model_name = chat_result.raw_model or raw_model_name
            tokens_in += chat_result.tokens_in
            tokens_out += chat_result.tokens_out
            # Book the billed tokens onto the run row AS THEY ACCRUE: if the
            # loop dies mid-run (provider error, guardrail raise, budget
            # fallback), the failure handler below can still record usage the
            # provider actually billed — spend used to escape the monthly cap
            # because ai_usage was written only on the success path.
            run.tokens_in = tokens_in
            run.tokens_out = tokens_out

            if final_step and chat_result.tool_calls:
                # Some providers still emit a tool call on the answer step although no tools
                # were offered. Honour the contract: this step is text only. Ask once more
                # with the findings flattened into plain text, so there is nothing left to call.
                findings = "\n".join(
                    str(m.get("content"))[:600] for m in messages if m.get("role") == "tool"
                )
                flat = [m for m in messages if m.get("role") in ("system", "user")][:1] + [
                    m for m in messages if m.get("role") == "user"
                ][-1:]
                flat.append(
                    {
                        "role": "system",
                        "content": _FINAL_STEP_INSTRUCTION + "\nنتائج البحث:\n" + findings,
                    }
                )
                try:
                    chat_result = await asyncio.wait_for(
                        self.gateway.chat(
                            session,
                            tenant_id,
                            alias=chat_alias,
                            messages=flat,
                            tools=None,
                            temperature=float(agent.temperature),
                            max_tokens=agent.max_output_tokens,
                            agent_id=agent.id,
                            run_id=run.id,
                        ),
                        timeout=max(
                            5.0, (max_wall_time - (datetime.now(UTC) - started_at)).total_seconds()
                        ),
                    )
                except TimeoutError:
                    hit_limit = "max_wall_time"
                    break
                tokens_in += chat_result.tokens_in
                tokens_out += chat_result.tokens_out
                # Text only from here: whatever it still tries to call is discarded.
                chat_result.tool_calls = []

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
                    vision_state=vision_state,
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
            content = AWAITING_APPROVAL_MESSAGE
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
                    run.tokens_in = tokens_in
                    run.tokens_out = tokens_out
                    raw_model_name = regen.raw_model or raw_model_name
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
                decision, reason = self._screen_output(defn, content, tool_calls_made)
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
            model_name=raw_model_name or agent.model,
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
            and (
                turns[-1]["content"].strip() == current_message.strip()
                or (
                    current_message.strip() == VOICE_ECHO_SENTINEL
                    and turns[-1]["content"].startswith(VOICE_NO_TRANSCRIPT_MARKER_PREFIX)
                )
                or (
                    turns[-1]["content"].startswith(VOICE_TURN_MARKER_PREFIX)
                    and current_message.strip() in turns[-1]["content"]
                )
            )
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
        inbound_message_id: uuid.UUID | str | None = None,
    ) -> tuple[list[dict], str | None, tuple[str, str] | None]:
        """History plus the answered message's scanner-cleared photo and audio.

        Media is selected from the message THIS turn answers
        (``inbound_message_id``) — never "whatever is newest": a delayed event
        for photo A arriving after photo B was processed must not attach B's
        photo to A's answer. Audio is eligible only when its attachment was
        scanned clean, its MIME format is explicitly supported by Qwen Omni,
        and the deployment opted in. Older media stays a text marker.
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
        audio_media: tuple[str, str] | None = None
        for message in reversed(history):
            if message.direction != "inbound":
                continue
            # Bind to the message the event carried. Without a carried id
            # (approval resume / legacy event) the newest inbound row is the
            # best available answer target — the historical behaviour.
            if inbound_message_id is not None and message.id != uuid.UUID(str(inbound_message_id)):
                continue
            row = (
                await session.execute(
                    select(_conversations_models.Attachment.storage_key)
                    .where(
                        _conversations_models.Attachment.tenant_id == tenant_id,
                        _conversations_models.Attachment.message_id == message.id,
                        _conversations_models.Attachment.mime_type.like("image/%"),
                        _conversations_models.Attachment.storage_key.is_not(None),
                        # ADR-062 (amended): ONLY a scanned image egresses.
                        _conversations_models.Attachment.scan_status == "scanned",
                    )
                    .order_by(_conversations_models.Attachment.created_at.desc())
                    .limit(1)
                )
            ).first()
            if row is not None:
                image_key = row.storage_key
            if get_settings().ai_voice_audio_input:
                audio_row = (
                    await session.execute(
                        select(
                            _conversations_models.Attachment.mime_type,
                            _conversations_models.Attachment.storage_key,
                        )
                        .where(
                            _conversations_models.Attachment.tenant_id == tenant_id,
                            _conversations_models.Attachment.message_id == message.id,
                            _conversations_models.Attachment.mime_type.like("audio/%"),
                            _conversations_models.Attachment.storage_key.is_not(None),
                            # Audio is customer PII as well: only clamd-cleared
                            # bytes may egress to an Omni model.
                            _conversations_models.Attachment.scan_status == "scanned",
                        )
                        .order_by(_conversations_models.Attachment.created_at.desc())
                        .limit(1)
                    )
                ).first()
                if audio_row is not None and omni_audio_format(audio_row.mime_type):
                    audio_media = (audio_row.mime_type, audio_row.storage_key)
            break  # only the answered message's media rides the turn
        # When the newest message's own media rides this turn, its history
        # marker ("its contents are not available to me") is a lie the model
        # reads immediately before the real content — drop that one marker;
        # older photos keep theirs.
        if (image_key or audio_media) and turns:
            last = turns[-1]
            if (
                last["role"] == "user"
                and isinstance(last["content"], str)
                and last["content"].startswith("[the customer sent ")
            ):
                turns.pop()
        return turns, image_key, audio_media

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
            # until the agent explicitly calls get_product_photos for one.
            # Recording them here would inflate shown_product_ids and bias
            # the deduplication logic in subsequent runs.
            if call.get("name") != "get_product_photos":
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
        vision_state: dict | None = None,
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
                        if vision_state:
                            # The coordinator's server-side photo verdict: the
                            # classified kind gates find_product_by_image (the
                            # model cannot re-propose a kind the server
                            # refused), and a precomputed MatchResult is
                            # reused so the paid pipeline runs once per photo.
                            if vision_state.get("classified_kind") is not None:
                                tool_context["image_kind_classified"] = str(
                                    vision_state["classified_kind"]
                                )
                            if vision_state.get("match") is not None:
                                tool_context["vision_match"] = vision_state["match"]
                        kwargs["context"] = tool_context
                    # §135: HIGH-risk tools suspend the run until a human
                    # approves. The approval row is durable — the run resumes
                    # (or dies) on the decision. No current customer tool is
                    # HIGH; the path stays for the platform's future agents.
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
                                k: v for k, v in tool_context.items() if k != "customer_image"
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
                    # Name the field: "Extra inputs are not permitted" alone does
                    # not tell the model WHICH argument to drop, so it retries
                    # blind. Only the field path goes back, never the value
                    # (an argument can carry customer text).
                    first = exc.errors()[0]
                    field = ".".join(str(part) for part in first.get("loc", ()))
                    reason = first.get("msg", str(exc))
                    error = (
                        f"invalid tool arguments: {field}: {reason}"
                        if field
                        else f"invalid tool arguments: {reason}"
                    )
                except ExternalProviderError as exc:
                    # Provider failures are NOT designed outcomes: the
                    # exception text can carry the provider's response body
                    # (which may echo request content). The model gets a
                    # fixed category, the full text goes to the logs, and the
                    # trace row stays inspectable without leaking bodies.
                    status = "error"
                    error = f"model provider rejected the call ({exc.code})"
                    logger.warning(
                        "ai.tool_provider_error tool=%s detail=%s",
                        request.name,
                        str(exc)[:500],
                    )
                except DomainError as exc:
                    # Designed outcome: a tool MEANT to say this (insufficient
                    # stock, unknown id, duplicate SKU). The message is data
                    # the model may act on — it never carries internals.
                    status = "error"
                    error = str(exc)
                except AIBudgetFallbackRequested as exc:
                    # Designed outcome too (§42 on_exceed == "fallback"): the
                    # budget gate refused the call because a cap is exhausted.
                    # It is a plain Exception, not a DomainError, so without
                    # this guard it fell into the generic branch below and the
                    # model heard "tool failed unexpectedly" — retrying blind
                    # against a budget that cannot move. The explicit budget
                    # story is the data the model needs to stop and report.
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
        # `args` rides the outcome so downstream consumers (media collection
        # reads product ids) never re-query the ToolCall row.
        return {
            "name": request.name,
            "status": status,
            "error": error,
            "result": result,
            "args": request.arguments or {},
        }
