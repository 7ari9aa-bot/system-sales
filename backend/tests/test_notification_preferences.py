"""The person's own notification settings: two channels, one window, one clock.

The table has existed since §166 but nothing could write it, and the model had been
pointed at a per-channel shape the dispatcher never used — so the digest aggregator
raised AttributeError the moment a row existed. These tests pin the parts that do
not need Postgres: the window arithmetic, the accepted time shape, the schema's
"something to change" rule, and the fact that the routes exist under /users/me.
"""

from __future__ import annotations

from datetime import time

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core.errors import ValidationError
from app.platform.notifications.digest import NotificationAggregator
from app.platform.notifications.models import NotificationPreference
from app.platform.notifications.router import me_router, router
from app.platform.notifications.schemas import NotificationPreferencesUpdate
from app.platform.notifications.service import NotificationPreferencesService

# --------------------------------------------------------------- the window --


def _pref(start: time | None, end: time | None) -> NotificationPreference:
    return NotificationPreference(quiet_start=start, quiet_end=end)


def test_no_window_means_never_quiet() -> None:
    assert NotificationAggregator._in_quiet_hours(_pref(None, None), now_time=time(3, 0)) is False


def test_a_daytime_window_holds_only_inside_it() -> None:
    pref = _pref(time(13, 0), time(15, 0))
    assert NotificationAggregator._in_quiet_hours(pref, now_time=time(12, 59)) is False
    assert NotificationAggregator._in_quiet_hours(pref, now_time=time(14, 0)) is True
    assert NotificationAggregator._in_quiet_hours(pref, now_time=time(15, 1)) is False


def test_an_overnight_window_wraps_around_midnight() -> None:
    """22:00 → 07:00 is the window people actually set."""
    pref = _pref(time(22, 0), time(7, 0))
    assert NotificationAggregator._in_quiet_hours(pref, now_time=time(23, 30)) is True
    assert NotificationAggregator._in_quiet_hours(pref, now_time=time(3, 0)) is True
    assert NotificationAggregator._in_quiet_hours(pref, now_time=time(12, 0)) is False


def test_the_window_is_compared_against_a_supplied_local_clock() -> None:
    """The caller resolves the person's zone; this function must not assume UTC."""
    pref = _pref(time(22, 0), time(7, 0))
    # 23:00 in Cairo is 21:00 UTC: reading it as UTC would call this "not quiet"
    assert NotificationAggregator._in_quiet_hours(pref, now_time=time(23, 0)) is True


# ----------------------------------------------------------- the time shape --


def test_hhmm_is_parsed() -> None:
    assert NotificationPreferencesService._parse_time("22:05", "start") == time(22, 5)
    assert NotificationPreferencesService._parse_time("07:00", "end") == time(7, 0)


@pytest.mark.parametrize("bad", ["2200", "25:00", "22:60", "ten", "", "22:00:00"])
def test_anything_else_is_refused(bad: str) -> None:
    with pytest.raises(ValidationError):
        NotificationPreferencesService._parse_time(bad, "start")


# --------------------------------------------------------------- the schema --


def test_an_empty_update_is_refused() -> None:
    with pytest.raises(PydanticValidationError):
        NotificationPreferencesUpdate()


def test_one_switch_is_a_valid_update() -> None:
    assert NotificationPreferencesUpdate(email_enabled=False).email_enabled is False


# ---------------------------------------------------------------- the shape --


def test_one_row_per_person_and_no_second_clock() -> None:
    """A per-channel shape and a stored timezone would both be lies the model tells."""
    assert not hasattr(NotificationPreference, "channel")
    assert not hasattr(NotificationPreference, "timezone")
    for column in ("in_app_enabled", "email_enabled", "push_enabled", "quiet_start", "quiet_end"):
        assert column in NotificationPreference.__table__.columns


def test_the_personal_routes_sit_under_users_me() -> None:
    me_paths = {
        (method, route.path)
        for route in me_router.routes
        for method in getattr(route, "methods", set())
    }
    assert ("GET", "/users/me/notification-preferences") in me_paths
    assert ("PUT", "/users/me/notification-preferences") in me_paths
    # and the workspace bell routes are untouched
    assert any(route.path.startswith("/notifications") for route in router.routes)
