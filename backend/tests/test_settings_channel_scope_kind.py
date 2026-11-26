"""A channel scope must be a channel, not any integration row.

`integrations` holds every provider link: channel accounts (whatsapp, instagram), oauth
grants, api keys. The scope graph accepted any of their ids as a channel scope, so a
settings chain could hang off an integration that never receives a message, and an id
copied from the wrong screen silently "worked".
"""

from __future__ import annotations

import inspect
import pathlib

from app.modules.settings import scope_graph
from app.modules.settings.scope_graph import UnknownScopeError

SOURCE = pathlib.Path(scope_graph.__file__).read_text(encoding="utf-8")


def test_only_kind_channel_is_accepted_as_a_channel_scope() -> None:
    assert scope_graph._CHANNEL_KIND == "channel"
    exists = inspect.getsource(scope_graph._exists)
    assert "scope is Scope.CHANNEL" in exists
    assert "_channel_kind(session, tenant_id, scope_id) == _CHANNEL_KIND" in exists


def test_a_non_channel_integration_is_refused_with_its_kind() -> None:
    require = inspect.getsource(scope_graph.require_scope_entity)
    assert "not a channel" in require
    # The refusal names what the row actually is, instead of a bare "not found".
    assert "is a {kind!r} integration" in require


def test_the_kind_lookup_is_tenant_bound() -> None:
    lookup = inspect.getsource(scope_graph._channel_kind)
    assert "WHERE tenant_id = :tid" in lookup
    assert "SELECT kind FROM integrations" in lookup


def test_unknown_scope_error_stays_a_not_found() -> None:
    # The API maps it to 404, so the guard must not change the error family.
    assert issubclass(UnknownScopeError, scope_graph.NotFoundError)
