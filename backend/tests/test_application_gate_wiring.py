"""A gate is only real if it asks for the right application.

routing.GROUP_APPLICATIONS says which product owns each group of routes. This test
reads the modules that actually gate, extracts the key each one passes, and fails
if a router asks about an application that does not own its group - the mistake
that would let a purchasing customer through a customer-engagement screen, or the
reverse, without any test going red.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.modules.applications.manifests import REGISTRY

BACKEND = Path(__file__).resolve().parents[1]

#: module that gates -> the application it must ask about, and why
GATED: dict[str, tuple[str, str]] = {
    "app/modules/catalog/routers/__init__.py": (
        "retail.core",
        "the catalog is part of the base every shop starts with",
    ),
    "app/modules/inventory/router.py": ("retail.core", "stock is part of the base"),
    "app/modules/pos/router.py": ("retail.core", "the register is part of the base"),
    "app/modules/purchasing/router.py": (
        "retail.purchasing",
        "suppliers and purchase orders are the purchasing product",
    ),
    "app/modules/customers/routers/customers.py": (
        "customer.engagement",
        "customer records are the engagement product",
    ),
    "app/modules/conversations/routers/inbox.py": (
        "customer.engagement",
        "the inbox is how the engagement product talks to customers",
    ),
    "app/modules/segments/router.py": (
        "customer.engagement",
        "a segment has no meaning outside the engagement product",
    ),
}

CALL = re.compile(r'workspace_gate\(\s*"([^"]+)"')


def _keys(path: str) -> set[str]:
    source = (BACKEND / path).read_text(encoding="utf-8")
    return set(CALL.findall(source))


@pytest.mark.parametrize("path", sorted(GATED))
def test_a_gated_module_asks_about_the_application_it_serves(path: str) -> None:
    expected, why = GATED[path]
    assert _keys(path) == {expected}, (
        f"{path} should ask about {expected!r} ({why}), "
        f"but asks about {sorted(_keys(path))}"
    )


@pytest.mark.parametrize("path", sorted(GATED))
def test_every_gated_application_exists_in_the_registry(path: str) -> None:
    expected, _ = GATED[path]
    assert expected in REGISTRY, f"{path} gates an application that is not registered"


def test_every_file_in_the_table_exists_and_really_gates() -> None:
    for path in GATED:
        assert (BACKEND / path).is_file(), f"{path} moved; update this table"
        assert _keys(path), f"{path} no longer calls workspace_gate"
