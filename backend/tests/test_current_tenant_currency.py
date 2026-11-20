"""The signed-in user's workspaces carry the currency each shop trades in.

The till and every screen write amounts in that currency; without it they printed the Egyptian pound
for any shop. The value is the shop's own (``Tenant.currency``), never guessed by a client.
"""

from __future__ import annotations

import inspect
import uuid
from types import SimpleNamespace

from app.modules.identity import schemas
from app.modules.identity.routers import auth, users


def _tenant(currency: str | None) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), name="الأمل", slug="amal", currency=currency)


def test_a_workspace_reports_the_currency_the_shop_trades_in() -> None:
    row = _tenant("SAR")
    out = schemas.CurrentTenant.model_validate(row, from_attributes=True)
    assert out.currency == "SAR"


def test_a_workspace_with_no_currency_says_so_instead_of_guessing() -> None:
    out = schemas.CurrentTenant.model_validate(_tenant(None), from_attributes=True)
    assert out.currency is None


def test_every_place_that_builds_a_workspace_passes_the_currency() -> None:
    """Three routes build the same block; one that forgets it would show the pound again."""
    for fn in (auth.me, auth.accept_invitation, users._current_user):
        src = inspect.getsource(fn)
        assert "CurrentTenant(" in src, fn.__name__
        assert "currency=t.currency" in src, fn.__name__
