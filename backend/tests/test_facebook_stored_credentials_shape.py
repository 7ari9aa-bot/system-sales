"""A Facebook channel connected through OAuth / the spec must work on the /facebook screens.

Regression: the spec and the OAuth callback store ``credentials.page_access_token`` and
``config.account_id``; the Pages client and router only read ``api_key``, so a correctly
connected Page answered "Facebook is not connected" (HTTP 409/503) on every screen.
"""

import pytest

from app.applications.apparel.modules.conversations.gateway.facebook_pages import (
    FacebookPagesClient,
    page_token_and_id,
)

STORED = {"account_id": "1215323418341930", "page_access_token": "page-token"}


def test_stored_oauth_shape_is_understood():
    assert page_token_and_id(STORED) == ("page-token", "1215323418341930")
    assert FacebookPagesClient._creds(STORED) == ("page-token", "1215323418341930")


def test_legacy_api_key_shape_still_works():
    assert page_token_and_id({"api_key": "tok", "account_id": "111"}) == ("tok", "111")


def test_page_id_from_config_page_id_is_accepted():
    assert page_token_and_id({"page_access_token": "t", "page_id": "9"}) == ("t", "9")


def test_page_access_token_wins_when_both_are_present():
    assert (
        page_token_and_id({"api_key": "old", "page_access_token": "new", "account_id": "1"})[0]
        == "new"
    )


@pytest.mark.parametrize(
    "creds",
    [{}, {"account_id": "1"}, {"page_access_token": "t"}, {"api_key": "t"}],
)
def test_missing_part_is_reported_not_guessed(creds):
    token, page_id = page_token_and_id(creds)
    assert not (token and page_id)
    with pytest.raises(Exception, match="missing page token or page id"):
        FacebookPagesClient._creds(creds)
