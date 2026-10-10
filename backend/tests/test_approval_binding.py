"""An approval authorizes EXACTLY the arguments a human approved (review G-02).

The audit called this the most dangerous logical gap in the system, and it was:
`ApprovalService.find_granted` matched a granted approval on
`(tenant, conversation_id, action, status='APPROVED', consumed_at IS NULL)` —
the action NAME only. The approved arguments were recorded in `payload` and
never compared, while the resume path executed `spec.handler(**kwargs)` with
whatever arguments the run had computed *this* time.

So a human could approve `purge_customer_data(note="now")` and the resumed run
would execute `purge_customer_data(note="something else")` against that same
approval. The human approved one action and a different one ran.

These tests pin the fix: the approval is bound to a hash of its payload, and a
resume that presents different arguments must NOT execute.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from pydantic import BaseModel
from sqlalchemy import select

from app.modules.ai.approvals import ApprovalService, payload_fingerprint
from app.modules.ai.gateway import AIGateway
from app.modules.ai.models import Agent, AgentTool, ApprovalRequest
from app.modules.ai.providers import ChatCompletionResult, ToolCallRequest
from app.modules.ai.runtime import AgentRunner
from app.modules.ai.tools import ToolSpec, register_tool

EXECUTED: list[str] = []
DANGEROUS_TOOL = "purge_customer_data"


class _Args(BaseModel):
    note: str = "default"


async def _dangerous_handler(session, tenant_id, *, note: str = "default", **kwargs):
    EXECUTED.append(note)
    return {"purged": True}


def _result(content=None, tool_calls=None) -> ChatCompletionResult:
    return ChatCompletionResult(
        content=content,
        tool_calls=tool_calls or [],
        tokens_in=0,
        tokens_out=0,
        raw_model="fake-model",
    )


def _call(note: str) -> ChatCompletionResult:
    """A HIGH-risk call carrying `note` — the argument the binding must cover."""
    return _result(
        tool_calls=[ToolCallRequest(id="c1", name=DANGEROUS_TOOL, arguments={"note": note})]
    )


def _patch_gateway(monkeypatch, results: list[ChatCompletionResult]) -> None:
    calls = {"n": 0}

    async def fake_chat(self, session, tenant_id, *, alias, messages, tools=None, **kw):
        calls["n"] += 1
        return results[min(calls["n"], len(results)) - 1]

    monkeypatch.setattr(AIGateway, "chat", fake_chat)


def _register() -> None:
    register_tool(
        ToolSpec(
            name=DANGEROUS_TOOL,
            description="HIGH-risk: destroys customer data",
            args_schema=_Args,
            handler=_dangerous_handler,
            risk_level="HIGH",
        )
    )


OPS_KIND = "approval-binding-ops"


def _ensure_ops_kind() -> None:
    """The runtime checks the registry's per-kind allowlist BEFORE the
    AgentTool row, so a customer-kind agent could never reach the gate this
    file tests. A test-only kind authorizes exactly the destructive tool."""
    from app.modules.ai.core.registry import AgentDefinition, AgentRegistry

    if AgentRegistry.get_or_none(OPS_KIND) is None:
        AgentRegistry.register(
            AgentDefinition(
                kind=OPS_KIND,
                name="Approval Binding Test",
                description="test-only kind authorized for the destructive tool",
                allowed_tools=[DANGEROUS_TOOL],
            )
        )


async def _agent(db, tenant_id) -> Agent:
    _ensure_ops_kind()
    agent = Agent(
        tenant_id=tenant_id,
        kind=OPS_KIND,
        name="Ops Agent",
        model="fast",
        system_prompt="Be careful.",
    )
    db.add(agent)
    await db.flush()
    db.add(AgentTool(tenant_id=tenant_id, agent_id=agent.id, name=DANGEROUS_TOOL, policy={}))
    await db.flush()
    return agent


async def _conversation(db, tenant_id):
    from app.modules.conversations.service import ConversationService
    from app.modules.customers.service import CustomerService

    customer = await CustomerService.get_or_create_by_identity(
        db,
        tenant_id,
        channel="whatsapp",
        external_id=f"wa-{uuid.uuid4().hex[:10]}",
        name="Ops Customer",
    )
    return await ConversationService.get_or_create(
        db, tenant_id, customer_id=customer.id, channel="whatsapp"
    )


async def _approve(db, tenant_ctx, approval) -> None:
    await ApprovalService.decide(
        db,
        tenant_ctx.tenant_id,
        approval.id,
        decision="APPROVED",
        decided_by_user_id=tenant_ctx.user.id,
    )
    await db.flush()


async def _only_approval(db, tenant_id) -> ApprovalRequest:
    return (
        (await db.execute(select(ApprovalRequest).where(ApprovalRequest.tenant_id == tenant_id)))
        .scalars()
        .one()
    )


# ------------------------------------------------------- the fingerprint ---


def test_the_fingerprint_ignores_key_order() -> None:
    """The same logical arguments must always hash the same."""
    a = {"arguments": {"variant_id": "v1", "quantity": 1}}
    b = {"arguments": {"quantity": 1, "variant_id": "v1"}}
    assert payload_fingerprint(a) == payload_fingerprint(b)


def test_v12_lineage_hashes_alter_fingerprint() -> None:
    """Wave D: approvals bound to command/evidence hashes produce distinct fingerprints."""
    base = {"arguments": {"variant_id": "v1"}}
    fp_plain = payload_fingerprint(base)

    with_cmd = {
        "arguments": {"variant_id": "v1"},
        "_v12_lineage": {"command_hash": "c" * 64},
    }
    fp_cmd = payload_fingerprint(with_cmd)
    assert fp_plain != fp_cmd

    with_ev = {
        "arguments": {"variant_id": "v1"},
        "_v12_lineage": {"command_hash": "c" * 64, "evidence_set_hash": "e" * 64},
    }
    fp_ev = payload_fingerprint(with_ev)
    assert fp_cmd != fp_ev


def test_the_fingerprint_distinguishes_different_arguments() -> None:
    a = {"arguments": {"variant_id": "v1", "quantity": 1}}
    b = {"arguments": {"variant_id": "v1", "quantity": 100}}
    c = {"arguments": {"variant_id": "v2", "quantity": 1}}
    assert payload_fingerprint(a) != payload_fingerprint(b)
    assert payload_fingerprint(a) != payload_fingerprint(c)


def test_the_fingerprint_is_stable_for_empty_input() -> None:
    assert payload_fingerprint(None) == payload_fingerprint({})


def test_the_fingerprint_handles_non_json_values() -> None:
    """Tool arguments can carry UUIDs and datetimes; hashing must not raise."""
    from datetime import UTC, datetime

    payload = {"arguments": {"id": uuid.uuid4(), "at": datetime.now(UTC)}}
    assert len(payload_fingerprint(payload)) == 64


# ---------------------------------------------- the binding is enforced ----


async def test_the_request_records_the_payload_hash(db, tenant_ctx, monkeypatch):
    EXECUTED.clear()
    _register()
    agent = await _agent(db, tenant_ctx.tenant_id)
    _patch_gateway(monkeypatch, [_call("now"), _result(content="waiting")])

    await AgentRunner(gateway=AIGateway()).run(
        db, tenant_ctx.tenant_id, agent_id=agent.id, user_message="purge it"
    )

    approval = await _only_approval(db, tenant_ctx.tenant_id)
    assert approval.payload_hash is not None, "the approval is not bound to its arguments"
    assert approval.payload_hash == payload_fingerprint(approval.payload)


async def test_an_approval_does_not_authorize_DIFFERENT_arguments(db, tenant_ctx, monkeypatch):
    """THE regression test for G-02.

    A human approves `note="now"`. The resumed run asks for `note="evil"`. The
    approval must not release it — the action that runs has to be the action
    that was approved.
    """
    EXECUTED.clear()
    _register()
    agent = await _agent(db, tenant_ctx.tenant_id)
    conversation_id = (await _conversation(db, tenant_ctx.tenant_id)).id

    # First pass: parks asking to run note="now".
    _patch_gateway(monkeypatch, [_call("now"), _result(content="waiting")])
    await AgentRunner(gateway=AIGateway()).run(
        db,
        tenant_ctx.tenant_id,
        agent_id=agent.id,
        user_message="purge it",
        conversation_id=conversation_id,
    )
    approval = await _only_approval(db, tenant_ctx.tenant_id)
    await _approve(db, tenant_ctx, approval)

    # Resume asking for DIFFERENT arguments.
    _patch_gateway(monkeypatch, [_call("evil"), _result(content="done")])
    await AgentRunner(gateway=AIGateway()).run(
        db,
        tenant_ctx.tenant_id,
        agent_id=agent.id,
        user_message="purge it",
        conversation_id=conversation_id,
    )

    assert EXECUTED == [], (
        f"an approval granted for one set of arguments executed a different set: {EXECUTED}"
    )
    # The approved-but-unused approval must still be untouched...
    refreshed = (
        (await db.execute(select(ApprovalRequest).where(ApprovalRequest.id == approval.id)))
        .scalars()
        .one()
    )
    assert refreshed.consumed_at is None, "the wrong approval was consumed"
    # ...and the new arguments get their OWN pending request.
    pending = (
        (
            await db.execute(
                select(ApprovalRequest).where(
                    ApprovalRequest.tenant_id == tenant_ctx.tenant_id,
                    ApprovalRequest.status == "PENDING",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(pending) == 1, "different arguments must ask for a fresh approval"
    assert pending[0].payload.get("arguments", {}).get("note") == "evil"


async def test_matching_arguments_still_resume_and_execute_once(db, tenant_ctx, monkeypatch):
    """The binding must not break the legitimate resume path."""
    EXECUTED.clear()
    _register()
    agent = await _agent(db, tenant_ctx.tenant_id)
    conversation_id = (await _conversation(db, tenant_ctx.tenant_id)).id

    _patch_gateway(monkeypatch, [_call("now"), _result(content="waiting")])
    await AgentRunner(gateway=AIGateway()).run(
        db,
        tenant_ctx.tenant_id,
        agent_id=agent.id,
        user_message="purge it",
        conversation_id=conversation_id,
    )
    approval = await _only_approval(db, tenant_ctx.tenant_id)
    await _approve(db, tenant_ctx, approval)

    _patch_gateway(monkeypatch, [_call("now"), _result(content="done")])
    await AgentRunner(gateway=AIGateway()).run(
        db,
        tenant_ctx.tenant_id,
        agent_id=agent.id,
        user_message="purge it",
        conversation_id=conversation_id,
    )

    assert EXECUTED == ["now"], f"the approved action did not run: {EXECUTED}"


async def test_an_approval_with_no_hash_never_matches(db, tenant_ctx, monkeypatch):
    """Rows predating the column (payload_hash IS NULL) fail closed.

    SQL `= NULL` is never true, so such an approval cannot release an action
    even though its status is APPROVED.
    """
    EXECUTED.clear()
    _register()
    agent = await _agent(db, tenant_ctx.tenant_id)
    conversation = await _conversation(db, tenant_ctx.tenant_id)

    db.add(
        ApprovalRequest(
            tenant_id=tenant_ctx.tenant_id,
            conversation_id=conversation.id,
            entity_type="tool",
            entity_id=DANGEROUS_TOOL,
            action=DANGEROUS_TOOL,
            risk_level="HIGH",
            payload={"arguments": {"note": "now"}},
            payload_hash=None,  # legacy row
            status="APPROVED",
            decided_at=None,
        )
    )
    await db.flush()

    _patch_gateway(monkeypatch, [_call("now"), _result(content="done")])
    await AgentRunner(gateway=AIGateway()).run(
        db,
        tenant_ctx.tenant_id,
        agent_id=agent.id,
        user_message="purge it",
        conversation_id=conversation.id,
    )

    assert EXECUTED == [], "an unbound (legacy) approval released a HIGH-risk action"


async def test_a_stale_approval_is_not_auto_continued(db, tenant_ctx, monkeypatch):
    """A customer message after the approval invalidates it (spec §135).

    `is_stale_for_conversation` existed but had no caller, so an approval could
    be honoured after the conversation had moved on.
    """
    from app.modules.conversations.models import Message

    EXECUTED.clear()
    _register()
    agent = await _agent(db, tenant_ctx.tenant_id)
    conversation = await _conversation(db, tenant_ctx.tenant_id)

    _patch_gateway(monkeypatch, [_call("now"), _result(content="waiting")])
    await AgentRunner(gateway=AIGateway()).run(
        db,
        tenant_ctx.tenant_id,
        agent_id=agent.id,
        user_message="purge it",
        conversation_id=conversation.id,
    )
    approval = await _only_approval(db, tenant_ctx.tenant_id)
    await _approve(db, tenant_ctx, approval)

    # The customer writes again AFTER the approval was created. Postgres now()
    # is the transaction time, so the timestamp is set explicitly — otherwise
    # this row would share the approval's created_at and never read as newer.
    db.add(
        Message(
            tenant_id=tenant_ctx.tenant_id,
            conversation_id=conversation.id,
            direction="inbound",
            sender_type="customer",
            body="actually, don't",
            created_at=approval.created_at + timedelta(minutes=1),
        )
    )
    await db.flush()

    _patch_gateway(monkeypatch, [_call("now"), _result(content="done")])
    await AgentRunner(gateway=AIGateway()).run(
        db,
        tenant_ctx.tenant_id,
        agent_id=agent.id,
        user_message="purge it",
        conversation_id=conversation.id,
    )

    assert EXECUTED == [], "a stale approval was auto-continued"
    refreshed = (
        (await db.execute(select(ApprovalRequest).where(ApprovalRequest.id == approval.id)))
        .scalars()
        .one()
    )
    assert refreshed.consumed_at is None


async def test_request_is_idempotent_for_the_same_arguments(db, tenant_ctx, monkeypatch):
    """Re-entering the gate must not pile up duplicate pending requests."""
    EXECUTED.clear()
    _register()
    agent = await _agent(db, tenant_ctx.tenant_id)
    conversation = await _conversation(db, tenant_ctx.tenant_id)

    for _ in range(2):
        _patch_gateway(monkeypatch, [_call("now"), _result(content="waiting")])
        await AgentRunner(gateway=AIGateway()).run(
            db,
            tenant_ctx.tenant_id,
            agent_id=agent.id,
            user_message="purge it",
            conversation_id=conversation.id,
        )

    rows = (
        (
            await db.execute(
                select(ApprovalRequest).where(
                    ApprovalRequest.tenant_id == tenant_ctx.tenant_id,
                    ApprovalRequest.status == "PENDING",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1, f"expected one pending approval, got {len(rows)}"
