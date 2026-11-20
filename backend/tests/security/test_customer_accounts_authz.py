"""Customer accounts: who may do what, proven on the real mounted routes.

The cashier takes payments and deposits. Opening credit, adjusting a balance and reversing an
entry change what the shop is owed, so they are the manager's and the owner's (pos:override).
"""

from __future__ import annotations

import uuid

import pytest

from app.main import create_app
from tests.security.test_role_authz_matrix import _ctx_for, _status_for

CUSTOMER = uuid.uuid4()
ENTRY = uuid.uuid4()

# (method, path, body, who may reach it)
_ROUTES = [
    ("PUT", f"/api/v1/customer-accounts/{CUSTOMER}", {"credit_limit": "500"}, {"owner", "manager"}),
    (
        "POST",
        f"/api/v1/customer-accounts/{CUSTOMER}/adjustments",
        {"amount": "5", "reason": "x"},
        {"owner", "manager"},
    ),
    (
        "POST",
        f"/api/v1/customer-accounts/entries/{ENTRY}/reverse",
        {"reason": "x"},
        {"owner", "manager"},
    ),
    (
        "POST",
        f"/api/v1/customer-accounts/{CUSTOMER}/payments",
        {"amount": "5"},
        {"owner", "manager", "staff"},
    ),
    (
        "POST",
        f"/api/v1/customer-accounts/{CUSTOMER}/deposits",
        {"amount": "5"},
        {"owner", "manager", "staff"},
    ),
    ("GET", f"/api/v1/customer-accounts/{CUSTOMER}", None, {"owner", "manager", "staff"}),
    ("GET", f"/api/v1/customer-accounts/{CUSTOMER}/statement", None, {"owner", "manager", "staff"}),
]


@pytest.mark.parametrize("role", ["owner", "manager", "staff"])
@pytest.mark.parametrize("method,path,body,allowed", _ROUTES)
async def test_each_role_gets_exactly_what_it_should(role, method, path, body, allowed) -> None:
    app = create_app()
    try:
        status = await _status_for(app, _ctx_for(role), method, path, body)
    except Exception:  # noqa: BLE001 - the stub session blew up INSIDE the handler
        # an exception in the handler body means the permission gate already let the role in
        status = 500
    if role in allowed:
        assert status not in (401, 403), (role, method, path, status)
    else:
        assert status == 403, (role, method, path, status)


async def test_the_cashier_cannot_open_credit_for_anyone() -> None:
    # the single most dangerous gap: a till operator granting unlimited credit
    app = create_app()
    status = await _status_for(
        app,
        _ctx_for("staff"),
        "PUT",
        f"/api/v1/customer-accounts/{CUSTOMER}",
        {"credit_limit": None},
    )
    assert status == 403
