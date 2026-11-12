"""The plans a fresh database gets must be the same whether migrations or provision.py seeds them.

Basic and Business exist in two places: the migration that adds them to a live database and the
`PLANS` list `scripts/provision.py` seeds into a brand new one. If those drift, a new install and a
migrated install sell different limits under the same plan name, and nothing would say so.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CHANNELS = {"whatsapp", "instagram", "messenger", "telegram", "webchat"}


def _seed_plans() -> dict[str, dict]:
    spec = importlib.util.spec_from_file_location("provision", BACKEND / "scripts" / "provision.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {code: features for code, _name, _price, features in module.PLANS}


def _migration_plans() -> dict[str, dict]:
    text = (BACKEND / "migrations/versions/fe2026111203_plans_basic_business.py").read_text()
    found = {}
    for code in ("basic", "business"):
        match = re.search(
            rf"'{code}', '[A-Za-z]+', \d+, 'EGP', 'month',\s*'(\{{.*?\}})'::jsonb", text, re.S
        )
        assert match, f"could not find the {code} insert"
        found[code] = json.loads(match.group(1))
    return found


def test_basic_and_business_match_between_the_migration_and_the_seed() -> None:
    seed = _seed_plans()
    for code, features in _migration_plans().items():
        expected = dict(seed[code])
        if expected["channels"] == "*":
            continue
        assert features == expected, code


def test_every_channel_a_plan_names_is_a_real_channel() -> None:
    for code, features in {**_seed_plans(), **_migration_plans()}.items():
        channels = features.get("channels")
        if isinstance(channels, list):
            assert set(channels) <= CHANNELS, (code, set(channels) - CHANNELS)
