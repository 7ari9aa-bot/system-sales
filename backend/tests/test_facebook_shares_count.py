"""A post's share count: Meta returns `shares: {count}` and the screen shows it like Facebook does.

The app already asked Meta for `shares` but dropped it, so the Share counter always read 0. Meta's
note on the field: the count may include deleted and invisible shares, so it is shown as given.
"""

from types import SimpleNamespace

from app.modules.conversations.facebook_service import _shares
from app.modules.conversations.routers.facebook_pages import _post_out


def test_the_share_count_is_read_from_the_shares_object() -> None:
    assert _shares({"shares": {"count": 7}}) == 7


def test_a_post_nobody_shared_has_no_shares_field_and_counts_zero() -> None:
    # Meta leaves `shares` out entirely when there are none.
    assert _shares({}) == 0
    assert _shares({"shares": None}) == 0
    assert _shares({"shares": {}}) == 0


def test_a_malformed_count_is_zero_not_a_crash() -> None:
    assert _shares({"shares": {"count": "many"}}) == 0
    assert _shares({"shares": {"count": -3}}) == 0


def test_the_post_output_carries_the_share_count() -> None:
    row = SimpleNamespace(
        post_id="1_2",
        caption="hi",
        media_url=None,
        media_type="STATUS",
        permalink=None,
        like_count=1,
        comments_count=2,
        shares_count=5,
        posted_at=None,
    )
    assert _post_out(row)["shares"] == 5
