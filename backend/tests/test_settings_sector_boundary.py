"""The platform must not read a shop's settings.

The registry keeps every key in one table; this is the line that says who may
read which part of it. A platform screen reading ``pos.*`` is the first step
toward the platform knowing what a point of sale is, and after that every sector
has to fit the platform's idea of one (industry-applications §12).
"""

from __future__ import annotations

import pytest

from app.applications.registry import register_all
from app.core import sector_registry
from app.core.errors import PermissionDeniedError
from app.modules.settings.sector_boundary import (
    PLATFORM_DOMAINS,
    assert_application_may_read,
    assert_platform_may_read,
    owner_of,
)


@pytest.fixture(autouse=True)
def _registered():
    sector_registry.clear()
    register_all()
    yield
    sector_registry.clear()


def test_startup_registers_the_apparel_application() -> None:
    assert "apparel" in sector_registry.applications()
    assert sector_registry.owner(sector_registry.ROUTE_PREFIX, "/apparel") == "apparel"
    assert sector_registry.owner(sector_registry.PERMISSION_NAMESPACE, "apparel.") == "apparel"


def test_the_platform_owns_its_own_domains() -> None:
    for domain in PLATFORM_DOMAINS:
        assert owner_of(domain) == "platform"
        assert_platform_may_read(domain)


def test_the_platform_is_refused_a_trading_domain() -> None:
    assert owner_of("pos") == "apparel"
    with pytest.raises(PermissionDeniedError, match="apparel"):
        assert_platform_may_read("pos")


def test_every_apparel_domain_is_refused_to_the_platform() -> None:
    from app.applications.apparel.settings_ownership import owned_settings_domains

    for domain in sorted(owned_settings_domains()):
        with pytest.raises(PermissionDeniedError):
            assert_platform_may_read(domain)


def test_an_unclaimed_domain_is_refused_rather_than_assumed() -> None:
    assert owner_of("not_a_real_domain") is None
    with pytest.raises(PermissionDeniedError, match="no owner"):
        assert_platform_may_read("not_a_real_domain")


def test_an_application_reads_only_its_own_domains() -> None:
    assert_application_may_read("catalog", "apparel")
    with pytest.raises(PermissionDeniedError):
        assert_application_may_read("billing", "apparel")


def test_two_applications_cannot_claim_the_same_domain() -> None:
    with pytest.raises(ValueError, match="already claimed"):
        sector_registry.register("pharmacy", settings_domains=("catalog",))
