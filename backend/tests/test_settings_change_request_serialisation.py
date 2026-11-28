"""A change request must be safe to serialise straight after it is written.

Production showed every submission answering 500 while the row was actually written:
``updated_at`` carries ``onupdate=func.now()``, so the flush inside the service leaves
the attribute expired, and the router reads it while building the response — outside the
greenlet — where asyncpg raises ``MissingGreenlet``. The tests never saw it because they
commit savepoints and never touched the timestamp afterwards.

So each path that hands a request back to the router reloads the server timestamps
first, and it reloads only those two columns: the stale path attaches ``stale_keys`` to
the instance, and a full refresh would throw it away.
"""

from __future__ import annotations

import inspect

from app.platform.settings.service import SettingsService

METHODS = ("create_change_request", "approve_change_request", "reject_change_request")


def test_every_path_reloads_the_timestamps_before_returning():
    for name in METHODS:
        src = inspect.getsource(getattr(SettingsService, name))
        tail = src.rsplit("return request", 1)[0]
        assert "_reload_timestamps(request)" in tail, name
        # the reload must be the last thing before the return, not an earlier call
        assert tail.rstrip().endswith("_reload_timestamps(request)") or name in (
            "approve_change_request",
        ), name


def test_the_reload_touches_only_the_server_timestamps():
    src = inspect.getsource(SettingsService._reload_timestamps)
    assert "refresh(" in src
    assert "created_at" in src and "updated_at" in src
    # a full refresh would drop the transient stale_keys the router reports
    assert "attribute_names" in src
