"""Two channels on one warehouse are two settings, not one.

A ``channel`` override used to store the *warehouse* that serves the channel as its
scope_id. A shop running WhatsApp and Instagram from the same warehouse therefore had one
row for both: changing the Instagram reply policy changed WhatsApp's. A channel's identity
is now its ``integrations`` row, and it resolves up through the warehouse its config names.
"""

from __future__ import annotations

import inspect
import pathlib

from app.platform.settings import scope_graph
from app.platform.settings.registry import Scope

SOURCE = pathlib.Path(inspect.getfile(scope_graph)).read_text(encoding="utf-8")


def test_the_channel_scope_is_its_own_row() -> None:
    assert 'Scope.CHANNEL: "integrations"' in SOURCE
    assert "Scope.CHANNEL: Scope.TENANT" not in SOURCE.split("_ROOT_TABLE")[1]


def test_a_channel_is_not_rewritten_into_a_warehouse() -> None:
    assert "scope = Scope.WAREHOUSE" not in SOURCE, (
        "the channel id was being replaced by a warehouse id"
    )
    assert "A channel override hangs on the warehouse" not in SOURCE


def test_the_channel_chain_goes_through_its_named_warehouse() -> None:
    body = SOURCE[SOURCE.index("async def resolve_chain") :]
    assert "_channel_warehouse(" in body
    assert "ScopeLink(Scope.WAREHOUSE, warehouse_id)" in body


def test_a_channel_without_a_warehouse_inherits_from_the_tenant() -> None:
    body = SOURCE[SOURCE.index("async def resolve_chain") :]
    after = body.split("if warehouse_id is None:")[1].split("current_scope")[0]
    assert "ScopeLink(Scope.TENANT, None)" in after
    assert "return chain" in after


def test_the_warehouse_comes_from_the_integration_config() -> None:
    assert "config->>'warehouse_id'" in SOURCE
    assert "FROM integrations" in SOURCE
    assert "tenant_id = :tid AND id = :sid" in SOURCE


def test_validation_accepts_the_channel_scope() -> None:
    assert Scope.CHANNEL in scope_graph._ROOT_TABLE
