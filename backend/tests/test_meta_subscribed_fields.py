from app.modules.customers.meta_oauth import _INSTAGRAM_SCOPES, subscribed_fields
from app.modules.customers.meta_scopes import missing_instagram_scopes

# Every field below exists on Meta's `page` object. Instagram's own fields do not.
INSTAGRAM_ONLY_FIELDS = {
    "comments",
    "mentions",
    "message_reactions",
    "messaging_seen",
    "live_comments",
}


def test_instagram_page_subscription_asks_only_for_page_fields():
    f = set(subscribed_fields("instagram").split(","))
    assert {"messages", "messaging_postbacks"} <= f
    assert INSTAGRAM_ONLY_FIELDS.isdisjoint(f)


def test_every_channel_asks_for_read_receipts():
    for provider in ("messenger", "instagram", "facebook"):
        assert "message_reads" in subscribed_fields(provider).split(",")


def test_messenger_gets_chat_fields_and_facebook_adds_feed_and_mention():
    base = "messages,messaging_postbacks,messaging_referrals,message_deliveries,message_reads"
    # A customer's reaction is the Page field `message_reactions`; Instagram's is not a Page field.
    messenger = base + ",message_reactions"
    assert subscribed_fields("messenger") == messenger
    # A Facebook Page's comments arrive on `feed`, a tag of the Page on `mention`.
    assert subscribed_fields("facebook") == messenger + ",feed,mention"


def test_instagram_asks_for_comment_and_publish_permissions():
    s = set(_INSTAGRAM_SCOPES.split(","))
    assert {
        "instagram_manage_comments",
        "instagram_content_publish",
        "instagram_manage_messages",
    } <= s


def test_a_connection_with_every_instagram_scope_lacks_none():
    granted = [
        "instagram_manage_messages",
        "instagram_manage_comments",
        "instagram_content_publish",
    ]
    assert missing_instagram_scopes(granted) == []


def test_a_connection_missing_one_instagram_scope_names_it():
    assert missing_instagram_scopes(["instagram_manage_messages", "instagram_manage_comments"]) == [
        "instagram_content_publish"
    ]


def test_a_connection_that_recorded_no_scopes_lacks_all_of_them():
    assert missing_instagram_scopes(None) == [
        "instagram_manage_messages",
        "instagram_manage_comments",
        "instagram_content_publish",
    ]
