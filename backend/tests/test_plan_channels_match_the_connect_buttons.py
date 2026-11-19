"""A plan that offers Messenger must offer Facebook: they are the same page-messaging grant.

The channels page shows a Facebook connect button, but no plan listed ``facebook``, so connecting it
failed with "plan does not include this channel" on every plan except Enterprise. This pins the
seeded plans, which is what a fresh database gets. Plans already in a database are fixed by the
``fe2026111901`` migration, because ``provision.py`` only inserts a plan that is missing.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_PROVISION = Path(__file__).resolve().parent.parent / "scripts" / "provision.py"


def _plans() -> dict[str, object]:
    spec = importlib.util.spec_from_file_location("provision_for_test", _PROVISION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {code: features["channels"] for code, _name, _price, features in module.PLANS}


def test_every_plan_with_messenger_also_has_facebook() -> None:
    for code, channels in _plans().items():
        if isinstance(channels, list) and "messenger" in channels:
            assert "facebook" in channels, f"plan {code!r} has messenger but not facebook"


def test_the_cheaper_plans_are_not_widened_by_that_fix() -> None:
    plans = _plans()
    assert plans["starter"] == ["whatsapp", "webchat"]
    assert plans["basic"] == ["whatsapp", "telegram", "webchat"]
