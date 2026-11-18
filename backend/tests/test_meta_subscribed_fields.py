from app.modules.customers.meta_oauth import _INSTAGRAM_SCOPES, subscribed_fields


def test_instagram_subscribes_to_comments_reactions_and_seen():
    f = set(subscribed_fields("instagram").split(","))
    assert {"messages", "comments", "message_reactions", "messaging_seen"} <= f


def test_other_channels_keep_the_original_fields():
    base = "messages,messaging_postbacks,messaging_referrals,message_deliveries"
    assert subscribed_fields("messenger") == base == subscribed_fields("facebook")


def test_instagram_asks_for_comment_and_publish_permissions():
    s = set(_INSTAGRAM_SCOPES.split(","))
    assert {
        "instagram_manage_comments",
        "instagram_content_publish",
        "instagram_manage_messages",
    } <= s
