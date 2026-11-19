"""The Facebook channel asks Meta for the Page permissions its posts, comments and insights need.

Meta refuses publishing, comment moderation and insights on a real Page without them, and the
owner can untick any single permission on the dialog, so what was ASKED is not what was GRANTED.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from app.modules.customers.meta_oauth import _build_authorize_url
from app.modules.customers.meta_scopes import (
    FACEBOOK_PAGE_SCOPES,
    FACEBOOK_SCOPES,
    MESSENGER_SCOPES,
    granted_scopes_from_permissions,
    missing_facebook_scopes,
)

NEEDED = {
    "pages_manage_posts",
    "pages_manage_engagement",
    "pages_read_user_content",
    "read_insights",
}


def _scopes(provider: str) -> set[str]:
    url = _build_authorize_url(
        app_id="1", redirect_uri="https://x/cb", state="s", provider=provider, config_id=""
    )
    return set(parse_qs(urlparse(url).query)["scope"][0].split(","))


def test_the_facebook_dialog_asks_for_posting_comments_and_insights():
    assert NEEDED <= _scopes("facebook")


def test_the_facebook_dialog_still_asks_for_page_messaging():
    assert set(MESSENGER_SCOPES.split(",")) <= _scopes("facebook")


def test_messenger_is_not_asked_to_let_us_post():
    assert not (NEEDED & _scopes("messenger"))
    assert _scopes("messenger") == set(MESSENGER_SCOPES.split(","))


def test_instagram_scopes_are_untouched():
    assert not (NEEDED & _scopes("instagram"))
    assert "instagram_content_publish" in _scopes("instagram")


def test_no_scope_is_asked_twice():
    parts = FACEBOOK_SCOPES.split(",")
    assert len(parts) == len(set(parts))
    assert set(FACEBOOK_PAGE_SCOPES) == NEEDED


def test_a_business_login_config_replaces_the_scope_list_for_instagram_only():
    # Each channel has its own configuration; one must never narrow another's permissions.
    instagram = parse_qs(
        urlparse(
            _build_authorize_url(
                app_id="1",
                redirect_uri="https://x/cb",
                state="s",
                provider="instagram",
                config_id="42",
            )
        ).query
    )
    assert instagram["config_id"] == ["42"] and "scope" not in instagram

    facebook = parse_qs(
        urlparse(
            _build_authorize_url(
                app_id="1",
                redirect_uri="https://x/cb",
                state="s",
                provider="facebook",
                config_id="42",
            )
        ).query
    )
    assert "config_id" not in facebook
    assert "pages_manage_posts" in facebook["scope"][0]


def test_a_connection_with_everything_granted_lacks_nothing():
    assert missing_facebook_scopes(sorted(NEEDED | {"pages_messaging"})) == []


@pytest.mark.parametrize("granted", [None, [], "pages_manage_posts", {"a": 1}, 7])
def test_a_connection_made_before_these_permissions_lacks_all_of_them(granted):
    # An older connection recorded no grant at all, so it must connect once more.
    assert missing_facebook_scopes(granted) == list(FACEBOOK_PAGE_SCOPES)


def test_one_unticked_permission_is_named():
    granted = sorted(NEEDED - {"read_insights"})
    assert missing_facebook_scopes(granted) == ["read_insights"]


def test_only_granted_permissions_count_not_declined_or_expired_ones():
    answer = {
        "data": [
            {"permission": "pages_manage_posts", "status": "granted"},
            {"permission": "pages_manage_engagement", "status": "declined"},
            {"permission": "read_insights", "status": "expired"},
            {"permission": "pages_read_user_content", "status": "granted"},
            {"status": "granted"},  # no name: ignored
            "junk",
        ]
    }
    got = granted_scopes_from_permissions(answer)
    assert got == ["pages_manage_posts", "pages_read_user_content"]
    assert missing_facebook_scopes(got) == ["pages_manage_engagement", "read_insights"]


@pytest.mark.parametrize("bad", [None, {}, {"data": None}, {"error": {"code": 190}}, [], "x"])
def test_an_unreadable_permissions_answer_grants_nothing(bad):
    assert granted_scopes_from_permissions(bad) == []
