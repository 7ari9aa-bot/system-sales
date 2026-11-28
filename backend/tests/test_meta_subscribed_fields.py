from app.applications.apparel.modules.customers.meta_oauth import _INSTAGRAM_SCOPES, subscribed_fields
from app.applications.apparel.modules.customers.meta_scopes import missing_instagram_scopes

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


def test_the_messaging_channels_ask_for_read_receipts():
    # Facebook Management is not a messaging channel: it asks for Page-management fields only.
    for provider in ("messenger", "instagram"):
        assert "message_reads" in subscribed_fields(provider).split(",")
    assert "message_reads" not in subscribed_fields("facebook").split(",")


def test_messenger_gets_chat_fields_and_facebook_only_manages_the_page():
    base = "messages,messaging_postbacks,messaging_referrals,message_deliveries,message_reads"
    # A customer's reaction is the Page field `message_reactions`; Instagram's is not a Page field.
    messenger = base + ",message_reactions,message_echoes,messaging_handovers,message_edits"
    assert subscribed_fields("messenger") == messenger
    # Facebook Management asks ONLY for Page-management fields: comments arrive on `feed`, a tag of
    # the Page on `mention`. Messenger's fields need pages_messaging, which this grant lacks.
    assert subscribed_fields("facebook") == "feed,mention"


def test_a_staff_reply_from_metas_own_inbox_is_subscribed_where_it_exists():
    # Without these three Page fields the events never arrive, so no parser could ever see them.
    messenger_fields = set(subscribed_fields("messenger").split(","))
    assert {"message_echoes", "messaging_handovers", "message_edits"} <= messenger_fields
    # They belong to Messenger, not to Facebook Management.
    assert {"message_echoes", "messaging_handovers", "message_edits"}.isdisjoint(
        subscribed_fields("facebook").split(",")
    )
    # On Instagram the same names belong to the `instagram` object, so they stay off the Page
    # subscription (a Page POST naming them is ignored or rejected).
    instagram = set(subscribed_fields("instagram").split(","))
    assert {"message_echoes", "message_edits"}.isdisjoint(instagram)


def test_the_diagnostics_ask_for_the_fields_the_app_actually_subscribes():
    from app.applications.apparel.modules.customers.meta_channel_diagnostics import DASHBOARD_FIELDS

    page = set(DASHBOARD_FIELDS["page"])
    assert {"message_echoes", "messaging_handovers", "message_edits", "message_reactions"} <= page
    # Instagram's own object, including the fields this app parses but never asked to receive.
    instagram = set(DASHBOARD_FIELDS["instagram"])
    assert {"mentions", "live_comments", "story_insights"} <= instagram
    # Meta's own names for Instagram messaging; the Page names do not exist on this object.
    assert {"messaging_seen", "message_reactions", "message_edit"} <= instagram
    assert {"messaging_handovers", "message_edits", "message_reads"}.isdisjoint(instagram)


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
        "instagram_manage_insights",
    ]
    assert missing_instagram_scopes(granted) == []


def test_a_connection_missing_one_instagram_scope_names_it():
    assert missing_instagram_scopes(
        ["instagram_manage_messages", "instagram_manage_comments", "instagram_manage_insights"]
    ) == ["instagram_content_publish"]


def test_a_connection_that_recorded_no_scopes_lacks_all_of_them():
    assert missing_instagram_scopes(None) == [
        "instagram_manage_messages",
        "instagram_manage_comments",
        "instagram_content_publish",
        "instagram_manage_insights",
    ]
