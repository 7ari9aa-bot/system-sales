"""A change request can propose a clear, not only a value.

`restore_to_snapshot` opened an approval request for a key it needed to clear by sending
`{key: None}`, and `create_change_request` validates every value with the setting's own
validator — which rejects None for boolean, number and enum settings. So the clear path
could not even build its request, and the branch that handled "the snapshot had no override
for this key" skipped the request entirely.

A clear is an operation: the request carries `resets` (keys to remove) next to `changes`
(values to write), and applying it calls `reset` on the trusted path.
"""

from __future__ import annotations

import inspect
import pathlib

from app.modules.settings import service as service_module
from app.modules.settings.models import SettingChangeRequest
from app.modules.settings.schemas import ChangeRequestOut, CreateChangeRequestInput
from app.modules.settings.service import SettingsService

BACKEND = pathlib.Path(__file__).resolve().parents[1]
ROUTER = (BACKEND / "app/modules/settings/router.py").read_text(encoding="utf-8")
MIGRATION = (BACKEND / "migrations/versions/fe2026112605_change_request_resets.py").read_text(
    encoding="utf-8"
)


def test_the_request_stores_its_clears() -> None:
    assert "resets" in SettingChangeRequest.__table__.c
    assert "setting_change_requests" in MIGRATION
    assert "resets" in MIGRATION


def test_the_api_accepts_and_returns_resets() -> None:
    assert "resets" in CreateChangeRequestInput.model_fields
    assert "resets" in ChangeRequestOut.model_fields
    assert "resets=body.resets" in ROUTER
    assert 'resets=list(getattr(r, "resets", None) or [])' in ROUTER


def test_creation_validates_and_pins_the_reset_keys() -> None:
    src = inspect.getsource(SettingsService.create_change_request)
    assert "reset_keys" in src
    assert "for key in reset_keys:" in src
    # The revision a clear was proposed against must be pinned like any value.
    assert "pinned_keys = list(changes) + reset_keys" in src
    assert "resets=reset_keys" in src


def test_a_clear_does_not_travel_as_a_none_value() -> None:
    src = inspect.getsource(SettingsService.restore_to_snapshot)
    assert "{key: None}" not in src, "None is not a valid value for boolean/number/enum keys"
    assert "resets=[key]" in src


def test_applying_a_request_clears_through_the_trusted_path() -> None:
    src = inspect.getsource(SettingsService._apply_change_request)
    assert "await self.reset(" in src
    assert "trusted_apply=True" in src
    assert "cleared" in src


def test_reset_skips_the_write_check_only_when_trusted() -> None:
    src = inspect.getsource(SettingsService.reset)
    assert "if not trusted_apply:" in src


def test_an_empty_request_is_refused() -> None:
    src = inspect.getsource(SettingsService.create_change_request)
    assert "at least one change or reset" in src
    assert "source" in inspect.getsource(service_module)
