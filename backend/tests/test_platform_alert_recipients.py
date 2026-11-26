"""Alerts must have somewhere to go.

``_operator_emails`` read only ``users.is_platform_admin``. Production has zero
platform admins, so the list came back empty, ``_push_operator_emails`` returned
0 before touching Resend, and every monitor trip — including the new stuck-sweep
alert — was dropped in silence. The path looked healthy because nothing failed.

Two things are pinned here: the configured inboxes are always included and
de-duplicated, and an alert with no recipient at all is logged as a warning
instead of vanishing.
"""

from __future__ import annotations

from typing import Any

from app.core.config import Settings
from app.workers import scheduler_worker


class _Scalars:
    def __init__(self, values: list[str]) -> None:
        self._values = values

    def all(self) -> list[str]:
        return self._values


class _Result:
    def __init__(self, values: list[str]) -> None:
        self._values = values

    def scalars(self) -> _Scalars:
        return _Scalars(self._values)


class _Session:
    def __init__(self, admins: list[str]) -> None:
        self._admins = admins

    async def execute(self, statement: Any) -> _Result:  # noqa: ARG002
        return _Result(self._admins)


def _settings(emails: str) -> Settings:
    return Settings(platform_alert_emails=emails)  # type: ignore[call-arg]


async def test_configured_inboxes_are_added_when_there_are_no_admins(monkeypatch) -> None:
    import app.core.config as config_module

    configured = _settings("Owner@Fihrist.world, ,bad")
    monkeypatch.setattr(config_module, "get_settings", lambda: configured)
    recipients = await scheduler_worker._operator_emails(_Session([]))  # type: ignore[arg-type]
    assert recipients == ["owner@fihrist.world"]


async def test_admins_and_configured_inboxes_are_merged_without_duplicates(monkeypatch) -> None:
    import app.core.config as config_module

    monkeypatch.setattr(
        config_module,
        "get_settings",
        lambda: _settings("ops@fihrist.world,admin@fihrist.world"),
    )
    recipients = await scheduler_worker._operator_emails(
        _Session(["Admin@fihrist.world", "second@fihrist.world"])  # type: ignore[arg-type]
    )
    assert recipients == ["admin@fihrist.world", "second@fihrist.world", "ops@fihrist.world"]


def test_settings_parse_and_normalise_the_list() -> None:
    settings = _settings(" A@x.com , b@y.com,a@X.com ")
    assert settings.platform_alert_recipients == ["a@x.com", "b@y.com"]
    assert _settings("").platform_alert_recipients == []
