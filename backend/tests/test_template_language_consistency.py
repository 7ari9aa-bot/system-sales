"""The language checked for approval must be the language that is sent.

Meta reviews every language of a template on its own. If the policy looked up "ar" while the
adapter sent "en", an approved Arabic template would let an unreviewed English one through (Meta
then drops it silently), and an approved English one would be blocked for no reason.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.applications.apparel.modules.conversations.gateway.base import OutboundMessage
from app.applications.apparel.modules.conversations.gateway.whatsapp import WhatsAppAdapter
from app.applications.apparel.modules.conversations.policy import MessagingPolicyService, template_language


@pytest.mark.parametrize(
    ("vars_", "expected"),
    [
        (None, "ar"),
        ({}, "ar"),
        ({"language_code": "en"}, "en"),
        ({"language_code": "en_US"}, "en_US"),
        ({"language_code": ""}, "ar"),
        ({"language_code": "   "}, "ar"),
        ({"language_code": None}, "ar"),
        ({"language_code": " fr "}, "fr"),
    ],
)
def test_the_language_rule(vars_, expected):
    assert template_language(vars_) == expected


@pytest.mark.parametrize("code", ["en", "ar", "", "  ", None, " fr "])
def test_the_adapter_sends_exactly_the_language_the_policy_checks(code):
    vars_ = {"language_code": code} if code is not None else {}
    msg = OutboundMessage(
        tenant_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        customer_ref="201000000000",
        body=None,
        template_name="order_ready",
        template_vars=vars_,
    )
    body = WhatsAppAdapter()._build_send_body(msg)
    assert body["template"]["language"]["code"] == template_language(vars_)


class _Capture:
    """Records the statement the policy sends to the database."""

    def __init__(self, row=None):
        self.stmts = []
        self.row = row

    async def execute(self, stmt):
        self.stmts.append(stmt)
        return SimpleNamespace(scalar_one_or_none=lambda: self.row)


def _conversation():
    return SimpleNamespace(
        channel="whatsapp",
        last_inbound_at=None,
        window_expires_at=None,
        customer_service_window_expires_at=None,
        id=uuid.uuid4(),
    )


@pytest.mark.asyncio
async def test_the_policy_looks_up_the_language_it_was_given():
    s = _Capture()
    await MessagingPolicyService.evaluate_for_conversation(
        s, uuid.uuid4(), _conversation(), template_name="order_ready", language="en"
    )
    assert len(s.stmts) == 1
    assert "en" in s.stmts[0].compile().params.values()
    assert "ar" not in s.stmts[0].compile().params.values()


@pytest.mark.asyncio
async def test_an_approved_template_in_another_language_does_not_count():
    # Only the Arabic row exists. Asking for English must find nothing, so the send is refused.
    s = _Capture(row=None)
    decision = await MessagingPolicyService.evaluate_for_conversation(
        s, uuid.uuid4(), _conversation(), template_name="order_ready", language="en"
    )
    assert decision.allowed is False


class _StopHere(Exception):
    """Raised by the spy so the send stops right after the policy was asked."""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("vars_", "expected"),
    [({"language_code": "en"}, "en"), ({}, "ar"), ({"language_code": ""}, "ar")],
)
async def test_sending_asks_the_policy_about_the_language_it_will_send(
    monkeypatch, vars_, expected
):
    from app.applications.apparel.modules.conversations.service import ConversationService

    seen = {}

    async def get(session, tenant_id, conversation_id):
        return _conversation()

    async def spy(session, tenant_id, conversation, **kw):
        seen.update(kw)
        raise _StopHere

    monkeypatch.setattr(ConversationService, "get", staticmethod(get))
    monkeypatch.setattr(MessagingPolicyService, "evaluate_for_conversation", staticmethod(spy))

    with pytest.raises(_StopHere):
        await ConversationService.add_message(
            None,
            uuid.uuid4(),
            conversation_id=uuid.uuid4(),
            direction="outbound",
            sender_type="user",
            template_name="order_ready",
            template_vars=vars_,
        )
    assert seen["language"] == expected
    assert seen["template_name"] == "order_ready"
