"""Optional versus mandatory capabilities.

An optional capability is a convenience the owner switches on and off. A mandatory one is a rule of
the trade the shop cannot opt out of. Nothing is mandatory yet, so the mechanism is exercised with a
capability that exists only inside the test.
"""

from __future__ import annotations

import pytest

from app.platform.settings import capabilities as caps
from app.platform.settings.capabilities import (
    CAPABILITIES,
    Capability,
    capability_enabled,
    is_mandatory,
    shop_capabilities,
)
from app.platform.settings.service import SettingsService

NAME = "test_only_legal_rule"


@pytest.fixture
def legal_rule(monkeypatch: pytest.MonkeyPatch) -> str:
    """A capability that is mandatory for apparel only, present for the length of one test.

    It gets the same owner switch every real capability has, so a stored "off" can be tried.
    """
    from app.platform.settings import registry
    from app.platform.settings.registry import Scope, SettingDef, SettingType

    cap = Capability(NAME, (), "قاعدة", "Rule", "وصف", "Description", mandatory_in=("apparel",))
    monkeypatch.setitem(caps.CAPABILITIES, NAME, cap)
    key = f"capability.{NAME}"
    monkeypatch.setitem(
        registry.REGISTRY,
        key,
        SettingDef(
            key=key,
            domain="business",
            type=SettingType.BOOL,
            default=False,
            scopes=(Scope.TENANT, Scope.WORKSPACE),
            label_ar=cap.label_ar,
            label_en=cap.label_en,
            description_ar=cap.description_ar,
            description_en=cap.description_en,
        ),
    )
    return NAME


def test_nothing_is_mandatory_today_so_no_shop_is_forced_into_anything() -> None:
    for name in CAPABILITIES:
        assert all(not is_mandatory(name, v) for v in caps.VERTICALS), name


def test_a_mandatory_capability_is_on_for_its_vertical_without_any_choice(legal_rule) -> None:
    assert capability_enabled(legal_rule, vertical="apparel") is True


def test_the_owner_cannot_switch_a_mandatory_capability_off(legal_rule) -> None:
    assert capability_enabled(legal_rule, vertical="apparel", overrides={legal_rule: False}) is True


def test_mandatory_in_one_vertical_does_not_force_it_in_another(legal_rule) -> None:
    assert is_mandatory(legal_rule, "apparel") is True
    assert is_mandatory(legal_rule, "pharmacy") is False
    assert capability_enabled(legal_rule, vertical="pharmacy") is False
    assert capability_enabled(legal_rule, vertical="pharmacy", overrides={legal_rule: True}) is True
    assert (
        capability_enabled(legal_rule, vertical="pharmacy", overrides={legal_rule: False}) is False
    )


def test_an_unknown_vertical_is_the_plain_shop_and_is_not_forced(legal_rule) -> None:
    assert is_mandatory(legal_rule, "no-such-vertical") is False
    assert is_mandatory(legal_rule, None) is False


def test_an_unknown_vertical_is_treated_as_general_so_a_general_rule_still_binds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A vertical nobody defined is the plain shop, so a rule made for it still binds."""
    cap = Capability(NAME, (), "قاعدة", "Rule", "وصف", "Description", mandatory_in=("general",))
    monkeypatch.setitem(caps.CAPABILITIES, NAME, cap)
    assert is_mandatory(NAME, "no-such-vertical") is True
    assert is_mandatory(NAME, None) is True
    assert is_mandatory(NAME, "apparel") is False


def test_an_unknown_capability_is_neither_mandatory_nor_on() -> None:
    assert is_mandatory("nobody_defined_this", "apparel") is False
    assert capability_enabled("nobody_defined_this", vertical="apparel") is False


@pytest.mark.asyncio
async def test_the_shop_reads_a_mandatory_capability_as_on_and_listed(
    db, tenant_ctx, legal_rule
) -> None:
    s = SettingsService(db, tenant_ctx.tenant_id)
    await s.set("business.vertical", "apparel")
    out = await shop_capabilities(db, tenant_ctx.tenant_id)
    assert out["capabilities"][legal_rule] is True
    assert legal_rule in out["mandatory"]


@pytest.mark.asyncio
async def test_a_stored_off_switch_does_not_beat_a_mandatory_capability(
    db, tenant_ctx, legal_rule
) -> None:
    """The owner's switch is a setting too: it must not be able to write its way round the rule."""
    s = SettingsService(db, tenant_ctx.tenant_id)
    await s.set("business.vertical", "apparel")
    await s.set(f"capability.{legal_rule}", False)
    out = await shop_capabilities(db, tenant_ctx.tenant_id)
    assert out["capabilities"][legal_rule] is True


@pytest.mark.asyncio
async def test_a_shop_with_nothing_mandatory_reports_an_empty_list(db, tenant_ctx) -> None:
    out = await shop_capabilities(db, tenant_ctx.tenant_id)
    assert out["mandatory"] == []


@pytest.mark.asyncio
async def test_the_mandatory_list_is_sorted_so_the_reply_is_stable(
    db, tenant_ctx, legal_rule, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.platform.settings import registry
    from app.platform.settings.registry import Scope, SettingDef, SettingType

    first = "a_test_only_rule"
    cap = Capability(first, (), "أ", "A", "وصف", "Description", mandatory_in=("apparel",))
    monkeypatch.setitem(caps.CAPABILITIES, first, cap)
    monkeypatch.setitem(
        registry.REGISTRY,
        f"capability.{first}",
        SettingDef(
            key=f"capability.{first}",
            domain="business",
            type=SettingType.BOOL,
            default=False,
            scopes=(Scope.TENANT, Scope.WORKSPACE),
            label_ar="أ",
            label_en="A",
            description_ar="وصف",
            description_en="Description",
        ),
    )
    await SettingsService(db, tenant_ctx.tenant_id).set("business.vertical", "apparel")
    out = await shop_capabilities(db, tenant_ctx.tenant_id)
    assert out["mandatory"] == [first, legal_rule]
