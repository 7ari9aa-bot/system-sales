"""Which Meta permissions each channel asks for, and which a connection actually holds.

Kept free of routers, models and the database on purpose: the connect flow, the integration
listing and the tests all need these, and the connect flow and the listing import each other.
"""

from __future__ import annotations

#: What a store that only chats on Messenger is asked for.
MESSENGER_SCOPES = "pages_show_list,pages_read_engagement,pages_manage_metadata,pages_messaging"

#: The Facebook channel is the Page's own posts, comments and numbers (its chat is the Messenger
#: channel), so it asks for what Meta's Pages API demands for each
#: (developers.facebook.com/docs/pages-api): publish a post (pages_manage_posts), reply to / hide /
#: delete / like a comment (pages_manage_engagement), read what people wrote on the Page
#: (pages_read_user_content) and read its insights (read_insights).
#: Without them Meta refuses every one of those calls on a real Page. Messenger keeps the narrow
#: list: a store that only chats must not be asked to let us post for it.
FACEBOOK_PAGE_SCOPES = (
    "pages_manage_posts",
    "pages_manage_engagement",
    "pages_read_user_content",
    "read_insights",
)

#: What the Facebook channel needs just to list and read a Page it manages. `pages_messaging` is
#: NOT here on purpose: chatting with customers is the Messenger channel's job, and a store that
#: connects only its Facebook Page (posts, comments, insights) must not be asked to hand over
#: private-message access it never uses, nor be refused for lacking it.
FACEBOOK_BASE_SCOPES = ("pages_show_list", "pages_read_engagement", "pages_manage_metadata")
FACEBOOK_SCOPES = ",".join((*FACEBOOK_BASE_SCOPES, *FACEBOOK_PAGE_SCOPES))


def missing_facebook_scopes(granted: object) -> list[str]:
    """The Page permissions a Facebook connection still lacks, in the order we ask for them.

    `granted` is what was recorded when the Page connected (`_connection.granted_scopes`). A
    connection made before these permissions existed recorded nothing, so every one of them is
    missing, and the owner is told to connect once more instead of meeting a Meta refusal on the
    first post.
    """
    have = {str(x) for x in granted} if isinstance(granted, (list, tuple, set)) else set()
    return [scope for scope in FACEBOOK_PAGE_SCOPES if scope not in have]


#: What an Instagram connection needs beyond chat: DMs, comments, and publishing. Missing one does
#: not stop the account linking (DMs may still work) but the matching feature fails, so the
#: connection lists them and the owner can connect again.
INSTAGRAM_REQUIRED_SCOPES = (
    "instagram_manage_messages",
    "instagram_manage_comments",
    "instagram_content_publish",
)


def missing_instagram_scopes(granted: object) -> list[str]:
    """The Instagram permissions a connection lacks, in the order we ask for them."""
    have = {str(x) for x in granted} if isinstance(granted, (list, tuple, set)) else set()
    return [scope for scope in INSTAGRAM_REQUIRED_SCOPES if scope not in have]


def granted_scopes_from_permissions(payload: object) -> list[str]:
    """Permissions Meta says the user GRANTED, from a `/me/permissions` answer.

    Meta lists declined and expired ones too, with another `status`; only `granted` counts. The
    owner can untick any single permission on the dialog, so the scope list we asked for says
    nothing about what the token can do.
    """
    rows = payload.get("data") if isinstance(payload, dict) else None
    out: set[str] = set()
    for row in rows or []:
        if isinstance(row, dict) and row.get("status") == "granted" and row.get("permission"):
            out.add(str(row["permission"]))
    return sorted(out)
