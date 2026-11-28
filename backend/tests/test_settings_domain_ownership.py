"""A settings domain answers only to the layer that owns it.

The registry is one table and stays one table. What must not happen is a shop's
trading rules being readable by the platform layer, or the reverse, which is how
the platform starts needing to know what a sector is. These tests pin the rule to
the single funnel every read and write passes through, so a new service method
cannot quietly skip it.
"""

from __future__ import annotations

import pytest

from app.applications.registry import register_all
from app.core.context import application_key_contextvar
from app.core.errors import PermissionDeniedError
from app.modules.settings.registry import list_definitions
from app.modules.settings.service import _definition


def _key_in(domain: str) -> str:
    definitions = list_definitions(domain=domain)
    assert definitions, f"registry has no setting in domain {domain!r}"
    return definitions[0].key


@pytest.fixture(autouse=True)
def _shipped_applications_registered():
    """The composition root registers the applications at startup; do the same."""
    register_all()


@pytest.fixture
def as_application():
    def _set(application: str | None):
        return application_key_contextvar.set(application)

    tokens = []

    def _use(application: str | None) -> None:
        tokens.append(application_key_contextvar.set(application))

    yield _use
    for token in reversed(tokens):
        application_key_contextvar.reset(token)


def test_apparel_reads_its_own_domain(as_application) -> None:
    as_application("apparel")
    assert _definition(_key_in("pos")).domain == "pos"


def test_apparel_cannot_read_a_platform_domain(as_application) -> None:
    as_application("apparel")
    with pytest.raises(PermissionDeniedError):
        _definition(_key_in("billing"))


def test_platform_reads_its_own_domain(as_application) -> None:
    as_application("platform")
    assert _definition(_key_in("billing")).domain == "billing"


def test_platform_cannot_read_an_application_domain(as_application) -> None:
    as_application("platform")
    with pytest.raises(PermissionDeniedError):
        _definition(_key_in("pos"))


def test_no_application_context_keeps_todays_behaviour(as_application) -> None:
    as_application(None)
    assert _definition(_key_in("pos")).domain == "pos"
    assert _definition(_key_in("billing")).domain == "billing"
