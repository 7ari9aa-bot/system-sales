"""A successful verify must not forget what the OAuth link recorded about the connection.

`granted_scopes` is written once, by the OAuth flow. The verify route used to REPLACE the whole
`_connection` block with just {verified_at, display_name}, so the next `GET /integrations` saw no
scopes at all, reported every Page permission as missing, and the settings screen told the owner
of a healthy Facebook channel to reconnect it.
"""

from __future__ import annotations

import uuid

from app.modules.customers.meta_scopes import FACEBOOK_PAGE_SCOPES
from app.modules.customers.routers.integrations import _integration_output
from app.modules.platform.integration_verifier import VerifiedChannel
from app.modules.platform.models import Integration
from app.modules.platform.service import IntegrationCredentialsService
from tests.test_customers_http_surface import TENANT, _call

GRANTED = list(FACEBOOK_PAGE_SCOPES)


def _facebook_row(**connection) -> Integration:
    return Integration(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        provider="facebook",
        kind="channel",
        status="active",
        config={
            "account_id": "1215323418341930",
            "_connection": {
                "verified_at": "2026-01-01T00:00:00+00:00",
                "display_name": "Old name",
                **connection,
            },
        },
        credentials={"ciphertext": "encrypted"},
    )


async def _verify(monkeypatch, row: Integration):
    async def decrypt(_session, integration) -> dict:  # noqa: ANN001
        return {"page_access_token": "page-secret"}

    async def verify(provider, credentials, config) -> VerifiedChannel:  # noqa: ANN001
        return VerifiedChannel({"account_id": "1215323418341930"}, "New name")

    monkeypatch.setattr(IntegrationCredentialsService, "decrypt", staticmethod(decrypt))
    monkeypatch.setattr(
        "app.modules.customers.routers.integrations.verify_channel_credentials", verify
    )
    response, _session = await _call(
        "POST",
        f"/api/v1/integrations/{row.id}/verify",
        rows=[row],
        permissions={"settings:write"},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_a_successful_verify_keeps_the_scopes_the_link_recorded(monkeypatch) -> None:  # noqa: ANN001
    row = _facebook_row(granted_scopes=GRANTED)

    await _verify(monkeypatch, row)

    assert row.config["_connection"]["granted_scopes"] == GRANTED
    # What `GET /integrations` shows the settings screen for this row afterwards.
    assert _integration_output(row)["missing_scopes"] == [], (
        "a healthy channel must not be told to reconnect"
    )


async def test_a_successful_verify_still_refreshes_what_it_just_learned(monkeypatch) -> None:  # noqa: ANN001
    row = _facebook_row(granted_scopes=GRANTED)

    await _verify(monkeypatch, row)

    connection = row.config["_connection"]
    assert connection["display_name"] == "New name"
    assert connection["verified_at"] != "2026-01-01T00:00:00+00:00"


async def test_a_successful_verify_clears_the_failure_it_has_now_recovered_from(
    monkeypatch,  # noqa: ANN001
) -> None:
    row = _facebook_row(granted_scopes=GRANTED, last_failure="meta_unreachable")

    await _verify(monkeypatch, row)

    assert "last_failure" not in row.config["_connection"]


async def test_a_channel_linked_before_scopes_were_recorded_still_asks_to_reconnect(
    monkeypatch,  # noqa: ANN001
) -> None:
    """Keeping the old facts must not invent scopes that were never granted."""
    row = _facebook_row()  # no granted_scopes at all

    await _verify(monkeypatch, row)

    assert "granted_scopes" not in row.config["_connection"]
    assert _integration_output(row)["missing_scopes"], (
        "an old link really does lack the new Page permissions"
    )
