"""The receipt asks for the whole shop identity, not half of it.

The registry lets the owner save a commercial register number, an email, a website and a postal
code, but the receipt read model only requested the name, address, phone and tax id, so the other
four were saved and never printed. These tests run the read model against a stubbed settings
resolver (no database needed) and pin two things: the four fields come back with the shop block,
and every business.* key in the registry is requested by the receipt, so a future key cannot be
added and silently ignored again.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.applications.apparel.modules.pos import receipt_settings as rs
from app.platform.settings import registry as reg

_DEFAULTS = {"print.copies": 1, "print.paper_width": "80mm", "pos.exchange_max_days": 0}


@pytest.fixture()
def stub(monkeypatch):
    values: dict[str, object] = {}

    async def fake_resolve(self, keys, scope=None, scope_id=None):
        out = {}
        for key in keys:
            if key in values:
                value = values[key]
            else:
                value = _DEFAULTS.get(key, "" if not key.startswith("print.show") else False)
            out[key] = SimpleNamespace(value=value)
        return out

    from app.platform.settings.service import SettingsService

    monkeypatch.setattr(SettingsService, "resolve_many", fake_resolve)
    return values


@pytest.mark.asyncio
async def test_the_four_identity_fields_come_back_with_the_shop_block(stub) -> None:
    stub["business.commercial_register"] = "CR-99887"
    stub["business.email"] = "shop@example.com"
    stub["business.website"] = "https://example.com"
    stub["business.address.postal_code"] = "11511"
    shop = await rs.receipt_settings(None, "tenant", register_id=None)
    assert shop["commercial_register"] == "CR-99887"
    assert shop["email"] == "shop@example.com"
    assert shop["website"] == "https://example.com"
    assert shop["postal_code"] == "11511"


@pytest.mark.asyncio
async def test_blank_identity_fields_are_absent_not_empty_strings(stub) -> None:
    stub["business.commercial_register"] = "   "
    shop = await rs.receipt_settings(None, "tenant", register_id=None)
    assert shop["commercial_register"] is None
    assert shop["email"] is None and shop["website"] is None and shop["postal_code"] is None


def test_every_business_key_in_the_registry_is_requested_by_the_receipt() -> None:
    text = Path(reg.__file__).read_text(encoding="utf-8")
    keys = set(re.findall(r'key="(business\.[a-z0-9_.]+)"', text))
    # vertical/setup_state/terms_accepted_at/type are not print identity: they drive capabilities.
    ignored = {
        "business.vertical",
        "business.setup_state",
        "business.terms_accepted_at",
        "business.type",
    }
    missing = keys - ignored - set(rs._KEYS)
    assert missing == set(), f"receipt never asks for {sorted(missing)}"
