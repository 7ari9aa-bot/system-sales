"""A broken vision pipeline must DEGRADE the turn, never kill the ingest.

The half-configured trap: turn the scanner on before the vision keys land, and
the provider's "not configured" error used to propagate out of `run_customer_turn`
into the worker — retrying and then DEAD-LETTERING a perfectly healthy inbound
photo. The customer's message would have been lost to a deployment-ordering
mistake. Vision is a bonus (the same policy the knowledge context rides under):
log loudly, tell the model the photo could not be analyzed, keep the reply alive.

DB-backed: the turn loads/patches state rows, so a real database is the point.
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.errors import ValidationError as DomainValidationError
from app.modules.ai.agents.customer.turn import TurnInput, run_customer_turn
from app.modules.ai.models import Agent
from app.modules.ai.runtime import AgentRunResult
from app.modules.conversations.models import Message
from app.modules.conversations.service import ConversationService
from app.modules.customers.models import Customer


class _ReplyRunner:
    """A runner that echoes what it was shown, so the test can assert the
    model-visible context carried the honest failure line."""

    def __init__(self) -> None:
        self.seen_context: str | None = None

    async def run(self, session, tenant_id, **kwargs):
        self.seen_context = kwargs.get("context_lines")
        return AgentRunResult(
            content="معلش، الصورة مقدرتش تتحلل — تحب أحولك لموظف؟",
            run_id=None,
            tool_calls_made=[],
            guardrail_decision="allow",
            guardrail_reason=None,
        )


async def _product_classifier(session, tid, url):
    from app.modules.ai.agents.customer.vision.schemas import ImageKind

    return ImageKind.PRODUCT


async def test_a_failing_vision_provider_degrades_instead_of_dying(db, tenant_ctx, monkeypatch):
    import app.modules.ai.agents.customer.turn as turn_module

    async def broken_vision(*args, **kwargs):
        # EXACTLY what AIGateway.embed_vision raises when the key is absent.
        raise DomainValidationError("vision embedding provider is not configured")

    monkeypatch.setattr(turn_module, "run_vision_match", broken_vision)

    tenant_id = tenant_ctx.tenant_id
    agent = Agent(
        tenant_id=tenant_id,
        kind="customer",
        name="Customer Agent",
        model="fast",
        system_prompt="s",
        is_active=True,
    )
    db.add(agent)
    await db.flush()

    customer = Customer(tenant_id=tenant_id, name="Photo Customer")
    db.add(customer)
    await db.flush()
    conversation = await ConversationService.get_or_create(
        db, tenant_id, customer_id=customer.id, channel="webchat"
    )
    await db.flush()

    message = await ConversationService.add_message(
        db,
        tenant_id,
        conversation_id=conversation.id,
        direction="inbound",
        sender_type="customer",
        body="بعتلك صورة المنتج",
    )
    await db.flush()

    runner = _ReplyRunner()
    outcome = await run_customer_turn(
        db,
        TurnInput(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            agent_id=agent.id,
            inbound_message_id=message.id,
            customer_id=customer.id,
            body="بعتلك صورة المنتج",
            content_type="image",
            attachments=[("image/png", "photo-key")],
            image_urls={"photo-key": "https://storage.example/photo.png"},
        ),
        runner=runner,  # type: ignore[arg-type]
        image_classifier=_product_classifier,
    )

    # The turn COMPLETED: a reply exists, nothing raised, no blocked reason.
    assert outcome.reply is not None, "a vision failure killed the reply"
    assert outcome.blocked_reason is None
    # The model was told the truth about OUR failure — never left to guess.
    assert runner.seen_context is not None
    assert "مشكلة في نظامنا" in runner.seen_context
    # And the outbound message row does not exist yet — the hook owns sending.
    rows = (
        (await db.execute(select(Message).where(Message.conversation_id == conversation.id)))
        .scalars()
        .all()
    )
    assert [m.direction for m in rows] == ["inbound"]
