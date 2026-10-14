"""The customer agent is reply-only, and every withhold path hands over.

Two contracts, both of which the code contradicted before this file existed:

1. **Reply-only.** The customer agent understands a message and answers it from
   trusted store data. It does not create orders, add tasks or tag customers —
   not in its prompt, not in its capability list, not in its tool allowlist.
   (The DB permissions were removed earlier; the definition still advertised
   them, and a published prompt is what the model actually reads.)

2. **Handover is real.** A path that withholds a reply owes the customer a human:
   the row, the conversation status and the event. Two paths used to return
   silently, leaving the conversation with no owner, and nothing stopped a
   conversation from holding two open handovers.

DB-free on purpose: every assertion below runs on a laptop with no Postgres,
which is where these defects were introduced.
"""

from __future__ import annotations

import inspect
import pathlib
import re

import pytest

import app.modules.ai.agents.customer.definition  # noqa: F401 — registers the definition
from app.modules.ai import hooks
from app.modules.ai.agents.customer.definition import CUSTOMER_SYSTEM_PROMPT
from app.modules.ai.core.registry import AgentRegistry
from app.modules.ai.handover import OPEN_HANDOVER_STATUSES, request_human_takeover

BACKEND_ROOT = pathlib.Path(__file__).resolve().parent.parent

# The three capabilities a reply-only agent must not carry. Their DB permissions
# were already removed; these are the remaining surfaces.
TRANSACTING_TOOLS = {"create_order", "add_task", "add_tag"}

# The closed reason vocabulary from `app/modules/ai/models.py::AIHandover.reason`.
HANDOVER_REASONS = {
    "budget",
    "policy",
    "low_confidence",
    "customer_request",
    "failure",
    "guardrail",
    "messaging_window_closed",
    "approval",
}


def _customer() -> object:
    return AgentRegistry.get("customer")


# --------------------------------------------------------- 1. reply-only ----


def test_customer_agent_carries_no_transacting_tool() -> None:
    definition = _customer()
    allowed = set(definition.allowed_tools)
    default = set(definition.default_tools)
    assert not (TRANSACTING_TOOLS & allowed), sorted(TRANSACTING_TOOLS & allowed)
    assert not (TRANSACTING_TOOLS & default), sorted(TRANSACTING_TOOLS & default)


def test_customer_agent_advertises_no_transacting_capability() -> None:
    names = {capability.name for capability in _customer().capabilities}
    assert not (TRANSACTING_TOOLS & names), sorted(TRANSACTING_TOOLS & names)


def test_customer_agent_has_no_order_placement_task_type() -> None:
    assert "order_placement" not in _customer().task_types


def test_customer_prompt_forbids_selling_and_keeps_the_read_allowance() -> None:
    prompt = CUSTOMER_SYSTEM_PROMPT
    # The old prompt said the job was "إتمام عمليات الشراء" and required
    # confirming details "قبل تسجيل أي طلب".
    assert "إتمام" not in prompt
    assert "تسجيل أي طلب" not in prompt
    # An explicit prohibition, not just an absence.
    assert "ممنوع" in prompt
    # Reading an existing order to answer a question stays allowed.
    assert "قراءة حالة طلب" in prompt
    # …and the handover instruction survives the rewrite.
    assert "موظف" in prompt


def test_the_prompt_and_the_tool_list_agree() -> None:
    """A prompt that promises an action its tools cannot perform is a lie."""
    definition = _customer()
    allowed = set(definition.allowed_tools)
    for tool in ("search_products", "get_order", "find_product_by_image"):
        assert tool in allowed
    assert definition.enforce_grounding is True


# --------------------------------------------- 2. handover is idempotent ----


def test_handover_service_checks_for_an_open_row() -> None:
    """The read-then-act half of the guarantee (the DB half is the index)."""
    source = inspect.getsource(request_human_takeover)
    assert ".in_(OPEN_HANDOVER_STATUSES)" in source
    assert "return False" in source


def test_the_open_status_vocabulary_is_the_model_vocabulary() -> None:
    # `AIHandover.status` documents: pending | claimed | resolved.
    assert set(OPEN_HANDOVER_STATUSES) == {"pending", "claimed"}


def test_the_partial_unique_index_migration_exists() -> None:
    """The DB-level guarantee: one open handover per conversation."""
    path = (
        BACKEND_ROOT
        / "migrations"
        / "versions"
        / "fe2026101401_one_open_handover_per_conversation.py"
    )
    assert path.exists(), "the partial unique index migration is missing"
    source = path.read_text(encoding="utf-8")
    assert "uq_handovers_open_conversation" in source
    assert "UNIQUE INDEX" in source.upper()
    # The index is PARTIAL: only the open statuses compete for the slot, so a
    # conversation can be handed over again after its handover is resolved.
    assert "_OPEN_STATUSES = \"('pending', 'claimed')\"" in source
    assert "WHERE status IN {_OPEN_STATUSES}" in source
    assert 'down_revision: str | None = "fe2026100818"' in source


# ------------------------------------------------- 3. every path hands over ---


def test_no_withhold_path_returns_silently() -> None:
    """A missing agent and a plan without AI must both hand over."""
    source = inspect.getsource(hooks._do_auto_reply)
    assert 'handover("policy"' in source
    assert 'handover("failure"' in source
    # The two silent returns that used to leave the conversation unowned.
    assert "if agent is None:\n        return" not in source


def test_hooks_use_only_documented_handover_reasons() -> None:
    source = inspect.getsource(hooks._do_auto_reply)
    used = set(re.findall(r'handover\("([a-z_]+)"', source))
    assert used, "no handover reason found — did the paths change shape?"
    assert used <= HANDOVER_REASONS, sorted(used - HANDOVER_REASONS)
    # The two this work added, and the one §37 had no producer for.
    assert {"policy", "failure"} <= used


# ------------------------------------------------- 4. the queue is gated -----


def _permission_codes(route: object) -> set[str]:
    """Every `require_permission` code on a route's dependency tree."""
    codes: set[str] = set()

    def walk(dependant: object) -> None:
        code = getattr(getattr(dependant, "call", None), "code", None)
        if isinstance(code, str):
            codes.add(code)
        for child in getattr(dependant, "dependencies", ()):
            walk(child)

    walk(route.dependant)  # type: ignore[attr-defined]
    return codes


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/ai/handovers", "conversations:read"),
        ("/ai/handovers/{handover_id}/claim", "conversations:write"),
        ("/ai/handovers/{handover_id}/resolve", "conversations:write"),
    ],
)
def test_handover_routes_are_gated_by_a_permission(path: str, expected: str) -> None:
    """Read the queue needs a read code; taking or closing needs a write code.

    Asserted on the AI router's OWN route objects rather than on
    `create_app().routes`: the app mounts routers lazily, so the endpoint
    definitions — and their dependency trees — live here.
    """
    from app.modules.ai.router import router as ai_router

    routes = [route for route in ai_router.routes if getattr(route, "path", None) == path]
    assert len(routes) == 1, f"expected one route for {path}, found {len(routes)}"
    codes = _permission_codes(routes[0])
    assert expected in codes, f"{path} is gated by {sorted(codes) or 'nothing'}"
