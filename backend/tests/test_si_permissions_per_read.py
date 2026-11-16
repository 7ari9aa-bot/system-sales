"""Each read of a merged tool needs ITS OWN permission, not the tool's.

The assistant has three tools and a parameter that says which read to run, so one tool covers reads
that need different permissions (the money reports ``finance:read``, purchases ``purchasing:read``;
the shop records ``orders:read``, ``inventory:read`` or ``customers:read``). Before the merge the
runner hid a tool the asker lacked. Now the read itself refuses, so these run the REAL registered
tool for every read with every asker and check who gets through. A role that holds one permission
must never read another's records through the shared tool, and an unknown asker reads nothing that
needs a permission.
"""

from __future__ import annotations

import pytest

from app.core.errors import ValidationError
from app.modules.ai.agents.sales_intelligence import tools as T
from app.modules.ai.agents.sales_intelligence.permissions import asking_with
from app.modules.ai.tools import TOOLS

# (tool, parameter, value, extra args, the permission that read needs)
READS = [
    ("si_finance", "report", "expenses", {}, "finance:read"),
    ("si_finance", "report", "profit", {}, "finance:read"),
    ("si_finance", "report", "purchasing", {}, "purchasing:read"),
    ("si_shop", "view", "products", {}, "orders:read"),
    ("si_shop", "view", "stock", {}, "inventory:read"),
    ("si_shop", "view", "cashier", {}, "orders:read"),
    ("si_shop", "view", "order", {"query": "1001"}, "orders:read"),
    ("si_shop", "view", "customer", {"query": "ahmed"}, "customers:read"),
]
EVERY_CODE = {"finance:read", "purchasing:read", "orders:read", "inventory:read", "customers:read"}


@pytest.fixture(autouse=True)
def _registered():
    for name in ("si_shop", "si_finance"):
        TOOLS.pop(name, None)
    T.register_si_tools()


def test_the_table_covers_every_read_the_tools_can_run():
    from typing import get_args

    for tool, parameter in (("si_finance", "report"), ("si_shop", "view")):
        values = set(get_args(TOOLS[tool].args_schema.model_fields[parameter].annotation))
        assert values == {v for t, p, v, _, _ in READS if t == tool}, tool


@pytest.mark.parametrize("tool,parameter,value,extra,needs", READS)
async def test_a_read_refuses_everyone_who_lacks_its_permission(
    db, tenant_ctx, tool, parameter, value, extra, needs
):
    handler = TOOLS[tool].handler
    call = {parameter: value, **extra}
    # holding every OTHER permission is not enough
    with asking_with(EVERY_CODE - {needs}), pytest.raises(ValidationError, match="not allowed"):
        await handler(db, tenant_ctx.tenant_id, **call)
    with asking_with(set()), pytest.raises(ValidationError, match="not allowed"):
        await handler(db, tenant_ctx.tenant_id, **call)
    with asking_with(None), pytest.raises(ValidationError, match="not allowed"):
        await handler(db, tenant_ctx.tenant_id, **call)
    with pytest.raises(ValidationError, match="not allowed"):  # no asker set at all
        await handler(db, tenant_ctx.tenant_id, **call)


@pytest.mark.parametrize("tool,parameter,value,extra,needs", READS)
async def test_a_read_runs_for_the_asker_who_holds_its_permission(
    db, tenant_ctx, tool, parameter, value, extra, needs
):
    with asking_with({needs}):
        out = await TOOLS[tool].handler(db, tenant_ctx.tenant_id, **{parameter: value, **extra})
    assert isinstance(out, dict)


def test_every_owner_tool_has_a_risk_level_and_it_is_low():
    """A tool the risk table does not know is treated as unknown by the platform.

    Found when the shop tool shipped without an entry; this makes the next new tool fail here and
    not in production."""
    from app.core.risk import RiskLevel, known_actions

    for name in T.SI_TOOLS:
        assert name in known_actions(), f"{name} has no risk level"
        assert TOOLS[name].risk_level == "LOW", name
    assert RiskLevel.LOW.value
