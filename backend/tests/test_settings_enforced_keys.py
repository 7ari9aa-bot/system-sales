"""`SettingDef.enforced` must tell the truth.

The UI marks a setting "not active yet" when nothing reads it, so the flag is a promise to the
shop owner. This test scans the application (outside the settings module itself) for the literal
key strings and checks them against ``ENFORCED_KEYS`` in both directions.
"""

from __future__ import annotations

import pathlib

from app.modules.settings.registry import ENFORCED_KEYS, list_definitions

APP = pathlib.Path(__file__).resolve().parents[1] / "app"
SETTINGS_DIR = APP / "modules" / "settings"


def _keys_read_outside_settings() -> set[str]:
    keys = {d.key for d in list_definitions()}
    found: set[str] = set()
    for path in APP.rglob("*.py"):
        if SETTINGS_DIR in path.parents:
            continue
        text = path.read_text(encoding="utf-8")
        for key in keys:
            if f'"{key}"' in text or f"'{key}'" in text:
                found.add(key)
    return found


def test_every_enforced_key_is_registered() -> None:
    registered = {d.key for d in list_definitions()}
    assert not ENFORCED_KEYS - registered


def test_every_enforced_key_is_actually_read() -> None:
    missing = ENFORCED_KEYS - _keys_read_outside_settings()
    assert not missing, f"marked enforced but no module reads them: {sorted(missing)}"


def test_every_key_a_module_reads_is_marked_enforced() -> None:
    unlisted = _keys_read_outside_settings() - ENFORCED_KEYS
    assert not unlisted, f"read by a module but not in ENFORCED_KEYS: {sorted(unlisted)}"


def test_the_flag_reaches_the_definition() -> None:
    by_key = {d.key: d for d in list_definitions()}
    assert by_key["pos.max_discount_pct"].enforced
    assert by_key["print.copies"].enforced
    assert not by_key["print.invoice_prefix"].enforced
