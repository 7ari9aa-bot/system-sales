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


def test_the_chat_channels_ask_for_read_receipts():
    for provider in ("messenger", "instagram"):
        assert "message_reads" in subscribed_fields(provider).split(",")


def test_messenger_subscribes_to_every_event_the_ingest_acts_on():
    """A parser is not a subscription: Meta only sends what the Page is subscribed to."""
    f = set(subscribed_fields("messenger").split(","))
    assert {"messages", "messaging_postbacks", "messaging_referrals"} <= f
    assert {"message_deliveries", "message_reads"} <= f
    # Replies typed in the Page inbox, reactions, and thread-control hand-overs.
    assert {"message_echoes", "message_reactions", "messaging_handovers"} <= f


def test_facebook_asks_only_for_the_page_not_for_private_chat():
    """A Facebook connection with no Messenger beside it must not receive DMs it cannot place."""
    f = set(subscribed_fields("facebook").split(","))
    assert f == {"feed", "mention"}
    assert not (f & set(subscribed_fields("messenger").split(",")))


def test_instagram_does_not_ask_the_page_for_messenger_only_fields():
    f = set(subscribed_fields("instagram").split(","))
    assert not ({"message_echoes", "message_reactions", "messaging_handovers"} & f)


def test_every_documented_field_is_one_the_code_can_subscribe():
    """docs/META_SETUP.md tells the owner which Page fields to tick; they must all be asked for."""
    import re
    from pathlib import Path

    from app.modules.customers.meta_oauth import all_page_subscribed_fields

    text = (Path(__file__).resolve().parents[2] / "docs" / "META_SETUP.md").read_text()
    [line] = [
        ln
        for ln in text.splitlines()
        if ln.startswith("Fields: `messages`, `messaging_postbacks`, `messaging_referrals`")
    ]
    documented = set(re.findall(r"`([a-z_]+)`", line))
    assert documented == set(all_page_subscribed_fields())


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


def _documented_fields(prefix: str) -> set[str]:
    """The backticked names on the guide's English `Fields:` line that starts with `prefix`."""
    import re
    from pathlib import Path

    text = (Path(__file__).resolve().parents[2] / "docs" / "META_SETUP.md").read_text()
    [line] = [ln for ln in text.splitlines() if ln.startswith(f"Fields: `{prefix}")]
    return set(re.findall(r"`([a-z_]+)`", line))


def test_the_health_check_asks_for_the_dashboard_fields_the_guide_lists():
    """The check tells the owner which boxes to tick in the App Dashboard. When it named seven
    Page fields and the guide ten, an owner who followed the check never ticked echoes, handovers
    or mentions, and Meta never sent them."""
    from app.modules.customers.meta_channel_diagnostics import DASHBOARD_FIELDS

    assert set(DASHBOARD_FIELDS["page"]) == _documented_fields(
        "messages`, `messaging_postbacks`, `messaging_referrals"
    )
    assert set(DASHBOARD_FIELDS["instagram"]) == _documented_fields(
        "messages`, `messaging_postbacks`, `message_reactions"
    )


def test_the_dashboard_page_fields_cover_every_channels_page_subscription():
    from app.modules.customers.meta_channel_diagnostics import DASHBOARD_FIELDS

    for provider in ("messenger", "facebook", "instagram"):
        assert set(subscribed_fields(provider).split(",")) <= set(DASHBOARD_FIELDS["page"])
