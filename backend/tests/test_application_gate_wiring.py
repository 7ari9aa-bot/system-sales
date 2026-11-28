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

from app.platform.applications.manifests import REGISTRY

BACKEND = Path(__file__).resolve().parents[1]

#: module that gates -> the application it must ask about, and why
GATED: dict[str, tuple[str, str]] = {
    "app/applications/apparel/modules/catalog/routers/__init__.py": (
        "apparel",
        "the catalog is part of the base every shop starts with",
    ),
    "app/applications/apparel/modules/inventory/router.py": ("apparel", "stock is part of the base"),
    "app/applications/apparel/modules/pos/router.py": ("apparel", "the register is part of the base"),
    "app/applications/apparel/modules/purchasing/router.py": (
        "apparel.purchasing",
        "suppliers and purchase orders are the purchasing product",
    ),
    "app/applications/apparel/modules/customers/routers/customers.py": (
        "apparel.customers",
        "customer records are the engagement product",
    ),
    "app/applications/apparel/modules/conversations/routers/inbox.py": (
        "apparel.customers",
        "the inbox is how the engagement product talks to customers",
    ),
    "app/applications/apparel/modules/segments/router.py": (
        "apparel.customers",
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
        f"{path} should ask about {expected!r} ({why}), but asks about {sorted(_keys(path))}"
    )


@pytest.mark.parametrize("path", sorted(GATED))
def test_every_gated_application_exists_in_the_registry(path: str) -> None:
    expected, _ = GATED[path]
    assert expected in REGISTRY, f"{path} gates an application that is not registered"


def test_every_file_in_the_table_exists_and_really_gates() -> None:
    for path in GATED:
        assert (BACKEND / path).is_file(), f"{path} moved; update this table"
        assert _keys(path), f"{path} no longer calls workspace_gate"
