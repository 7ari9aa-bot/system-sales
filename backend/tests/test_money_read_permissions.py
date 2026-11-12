"""``finance:read`` and ``purchasing:read``: who may see the shop's money through the assistant.

The owner assistant reads profit, expenses and supplier balances. Every shop user shares one
``tenant_id`` and the chat sits behind ``analytics:read``, which staff hold, so the money tools are
gated by their own permissions. Those must start OWNER-ONLY: a manager does not get them by being
a manager (the owner grants them), and staff never do. The role matrix builds the manager from
``RESOURCES x ACTIONS``, so adding these as ordinary resources would have handed them out silently.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
MONEY = ("finance:read", "purchasing:read")


def _provision():
    spec = importlib.util.spec_from_file_location("provision", ROOT / "scripts" / "provision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_owner_holds_both_money_permissions():
    matrix = _provision().ROLE_MATRIX
    for code in MONEY:
        assert code in matrix["owner"], code


def test_a_manager_does_not_get_them_by_being_a_manager():
    matrix = _provision().ROLE_MATRIX
    for code in MONEY:
        assert code not in matrix["manager"], code


def test_staff_never_get_them():
    matrix = _provision().ROLE_MATRIX
    for code in MONEY:
        assert code not in matrix["staff"], code


def test_both_are_real_permission_rows_for_a_fresh_tenant():
    module = _provision()
    seeded = {code for _, _, code in module.EXTRA_PERMISSIONS}
    seeded |= {f"{r}:{a}" for r in module.RESOURCES for a in module.ACTIONS}
    for code in MONEY:
        assert code in seeded, f"{code} would be granted to the owner but never created"


def _migration() -> str:
    found = sorted((ROOT / "migrations" / "versions").glob("*money_read_permissions*.py"))
    assert found, "no migration brings existing databases to the same matrix"
    return found[-1].read_text()


def test_the_migration_creates_both_and_grants_them_to_the_owner_only():
    text = _migration()
    for code in MONEY:
        assert f"'{code}'" in text, code
    grants = re.findall(r"r\.code\s+IN\s*\(([^)]*)\)", text)
    assert grants, "no role grant found"
    for roles in grants:
        assert "'owner'" in roles
        assert "manager" not in roles and "staff" not in roles


def test_the_migration_is_safe_to_run_twice_and_can_be_undone():
    text = _migration()
    assert text.count("ON CONFLICT") >= 2
    assert "def downgrade" in text and "DELETE FROM role_permissions" in text


def test_the_migration_grants_each_permission_not_only_creates_it():
    """Creating a permission nobody holds leaves the owner without the tool. The grant statement
    itself must name every one of them."""
    text = _migration()
    grant = text.split("INSERT INTO role_permissions", 1)[1].split('"""', 1)[0]
    for code in MONEY:
        assert f"'{code}'" in grant, f"{code} is created but never granted to the owner"
