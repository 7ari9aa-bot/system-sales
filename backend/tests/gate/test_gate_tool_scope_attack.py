"""§176 gate scenario 16 — AI tool-scope attack (§132), language-only surface.

§132's rule: the model may only ever act on what the SERVER binds into the
tool's ``context``. The language-only scope cut removed every customer-scoped
tool (orders, customer reads, tasks, tags) — the strongest form of the fix:
an attack surface that does not exist cannot be steered.

What remains to enforce:

* NO customer tool schema exposes ``customer_id`` or ``conversation_id`` —
  a prompt-injected "act for customer 9999" has nowhere to land;
* the one context-bound tool, ``handover_to_human``, refuses to run with no
  conversation bound and treats a malformed binding as a controlled error —
  it never falls back to whatever id the model supplied.

DB-backed where a real handler runs; skips via ``db_url`` without an
application database — CI-only evidence.
"""

from __future__ import annotations

import pytest

from app.core.errors import DomainError
from app.modules.ai.agents.customer.tools import CUSTOMER_TOOL_SPECS
from app.modules.ai.tools import get_tool

pytestmark = [pytest.mark.gate]


def test_gate_no_customer_tool_names_a_customer_or_conversation() -> None:
    """The schema is the whole surface: no field may carry the scope."""
    for spec in CUSTOMER_TOOL_SPECS:
        fields = spec.args_schema.model_fields
        assert "customer_id" not in fields, f"{spec.name} exposes customer_id"
        assert "conversation_id" not in fields, f"{spec.name} exposes conversation_id"


def test_gate_the_old_scoped_tools_are_gone_entirely() -> None:
    """The customer-scoped reads died with the scope cut — nothing registers."""
    for name in ("get_customer", "get_order", "add_task", "add_tag", "create_order"):
        assert get_tool(name) is None, f"{name} is still registered"


async def test_gate_handover_with_no_bound_conversation_is_refused(db, tenant_ctx) -> None:
    """Fail closed: an unbound scope never falls back to a model-supplied id."""
    spec = get_tool("handover_to_human")
    with pytest.raises(DomainError):
        await spec.handler(
            db,
            tenant_ctx.tenant_id,
            reason="customer_request",
            summary="طلب موظف",
            context=None,
        )
    with pytest.raises(DomainError):
        await spec.handler(
            db,
            tenant_ctx.tenant_id,
            reason="customer_request",
            summary="طلب موظف",
            context={},
        )


async def test_gate_handover_with_a_malformed_binding_is_a_controlled_error(
    db, tenant_ctx
) -> None:
    """A corrupt context id is a DomainError, never a raw ValueError."""
    spec = get_tool("handover_to_human")
    with pytest.raises(DomainError):
        await spec.handler(
            db,
            tenant_ctx.tenant_id,
            reason="customer_request",
            summary="طلب موظف",
            context={"conversation_id": "not-a-uuid"},
        )
