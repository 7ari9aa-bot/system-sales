"""The settings cache exists, is scope-aware, and is not in the read path.

Settings decide money (discount cap, cash-movement limit, tax, exchange window). A
process-local cache invalidated by a worker event can serve a retired value on every
other API worker for up to five minutes. So the resolver reads the database, and this
guard keeps that decision visible: if someone wires the cache, this fails and the
wiring has to come with cross-process invalidation.
"""

from __future__ import annotations

import pathlib
import uuid

from app.modules.settings import cache

SERVICE = pathlib.Path(__file__).resolve().parents[1] / "app/modules/settings/service.py"


def test_the_resolver_does_not_consult_the_cache() -> None:
    source = SERVICE.read_text(encoding="utf-8")
    assert "settings.cache" not in source
    assert "cache.get(" not in source
    assert "cache.put(" not in source


def test_the_decision_is_recorded_in_code() -> None:
    assert cache.WIRED_INTO_READ_PATH is False


def test_a_tenant_read_and_a_branch_read_are_different_entries() -> None:
    tenant, branch = uuid.uuid4(), uuid.uuid4()
    cache.clear()
    cache.put(tenant, "tenant", None, "pos.max_discount_pct", 10)
    cache.put(tenant, "branch", branch, "pos.max_discount_pct", 25)
    assert cache.get(tenant, "tenant", None, "pos.max_discount_pct") == 10
    assert cache.get(tenant, "branch", branch, "pos.max_discount_pct") == 25
    # Two branches never share an answer.
    assert cache.get(tenant, "branch", uuid.uuid4(), "pos.max_discount_pct") is None


def test_invalidating_a_key_clears_every_scope_of_it() -> None:
    tenant, branch = uuid.uuid4(), uuid.uuid4()
    cache.clear()
    cache.put(tenant, "tenant", None, "pos.max_discount_pct", 10)
    cache.put(tenant, "branch", branch, "pos.max_discount_pct", 25)
    cache.put(tenant, "tenant", None, "pos.cash_movement_limit", 500)
    assert cache.invalidate(tenant, "pos.max_discount_pct") == 2
    assert cache.get(tenant, "branch", branch, "pos.max_discount_pct") is None
    # An unrelated key survives.
    assert cache.get(tenant, "tenant", None, "pos.cash_movement_limit") == 500


def test_invalidating_one_scope_leaves_the_others() -> None:
    tenant, branch = uuid.uuid4(), uuid.uuid4()
    cache.clear()
    cache.put(tenant, "tenant", None, "pos.max_discount_pct", 10)
    cache.put(tenant, "branch", branch, "pos.max_discount_pct", 25)
    assert cache.invalidate_scope(tenant, "branch", branch) == 1
    assert cache.get(tenant, "tenant", None, "pos.max_discount_pct") == 10
