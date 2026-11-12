"""A tool the asker may not use is not merely refused, it is never shown to the model.

The owner assistant is about to read money: profit, expenses, supplier balances. Every shop user
shares one ``tenant_id``, and the chat sits behind a single ``analytics:read``, so without a
per-tool permission any employee with that one grant could ask for the shop's profit. Hiding the
tool is stronger than refusing the call: a model that never saw ``si_profit`` cannot be talked
into calling it, and cannot even say that it exists.

This filter FAILS CLOSED, unlike ``filter_agent_tools_by_policy`` (a publish-time policy that must
fail open so a typo cannot strip a live agent). A permission filter that failed open would hand
the finance tools to everyone on a malformed grant.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.modules.ai.tools import ToolSpec, tools_visible_to


def _tool(name: str, requires: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(name=name, requires=requires)


def _names(tools) -> list[str]:
    return [t.name for t in tools]


def test_a_tool_without_a_requirement_is_visible_to_everyone():
    tools = [_tool("si_get_metric")]
    assert _names(tools_visible_to(tools, set())) == ["si_get_metric"]


def test_a_tool_is_hidden_without_its_permission():
    tools = [_tool("si_get_metric"), _tool("si_profit", "finance:read")]
    assert _names(tools_visible_to(tools, {"analytics:read"})) == ["si_get_metric"]


def test_a_tool_is_shown_with_its_permission():
    tools = [_tool("si_get_metric"), _tool("si_profit", "finance:read")]
    shown = tools_visible_to(tools, {"analytics:read", "finance:read"})
    assert _names(shown) == ["si_get_metric", "si_profit"]


def test_each_tool_needs_its_own_permission_not_just_any_other_one():
    tools = [_tool("si_profit", "finance:read"), _tool("si_stock_status", "inventory:read")]
    assert _names(tools_visible_to(tools, {"inventory:read"})) == ["si_stock_status"]


def test_no_permission_set_at_all_hides_every_gated_tool():
    """``None`` is "we do not know who is asking", never "everyone"."""
    tools = [_tool("si_get_metric"), _tool("si_profit", "finance:read")]
    assert _names(tools_visible_to(tools, None)) == ["si_get_metric"]


def test_a_malformed_requirement_hides_the_tool():
    """An empty or non-string ``requires`` must not read as "no requirement"."""
    tools = [_tool("a", ""), _tool("b", 7), _tool("c", "  ")]
    assert tools_visible_to(tools, {"analytics:read", ""}) == []


def test_a_malformed_permission_set_shows_only_ungated_tools():
    tools = [_tool("si_get_metric"), _tool("si_profit", "finance:read")]
    assert _names(tools_visible_to(tools, "finance:read")) == ["si_get_metric"]
    assert _names(tools_visible_to(tools, [None, 5])) == ["si_get_metric"]


def test_a_tool_spec_can_declare_what_it_requires():
    spec = ToolSpec(
        name="x",
        description="d",
        args_schema=SimpleNamespace,
        handler=lambda: None,
        requires="finance:read",
    )
    assert spec.requires == "finance:read"
    assert (
        ToolSpec(
            name="y", description="d", args_schema=SimpleNamespace, handler=lambda: None
        ).requires
        is None
    )
