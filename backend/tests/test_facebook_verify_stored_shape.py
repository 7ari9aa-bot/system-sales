"""A Facebook channel linked through OAuth must pass its own verify.

OAuth stores ``config = {"account_id": <page id>}`` and ``credentials = {"page_access_token"}``
(meta_oauth._connect_page). The spec's verify used to read ``config["page_id"]`` only, so the
"verify" button failed for every OAuth-linked page and then moved a healthy channel to
``reauth_required``.
"""

import httpx
import pytest

from app.core.errors import ValidationError
from app.modules.platform.channel_specs.facebook import FacebookConnectionSpec

PAGE_ID = "1215323418341930"


def _client(page_id: str = PAGE_ID):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": page_id, "name": "Meruna"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_the_shape_oauth_stores_verifies():
    async with _client() as http:
        verified = await FacebookConnectionSpec().verify(
            {"page_access_token": "tok"}, {"account_id": PAGE_ID}, client=http
        )
    assert verified.identity_config == {"account_id": PAGE_ID}
    assert verified.display_name == "Meruna"


async def test_the_manual_form_shape_still_verifies():
    async with _client() as http:
        verified = await FacebookConnectionSpec().verify(
            {"page_access_token": "tok"}, {"page_id": PAGE_ID}, client=http
        )
    assert verified.identity_config == {"account_id": PAGE_ID}


async def test_a_token_for_another_page_is_still_refused():
    async with _client(page_id="999") as http:
        with pytest.raises(ValidationError):
            await FacebookConnectionSpec().verify(
                {"page_access_token": "tok"}, {"account_id": PAGE_ID}, client=http
            )


async def test_no_page_id_at_all_is_still_refused():
    async with _client() as http:
        with pytest.raises(ValidationError):
            await FacebookConnectionSpec().verify({"page_access_token": "tok"}, {}, client=http)
