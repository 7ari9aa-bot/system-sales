"""Which Meta permissions each channel asks for, and which a connection actually holds.

Kept free of routers, models and the database on purpose: the connect flow, the integration
listing and the tests all need these, and the connect flow and the listing import each other.
"""

from __future__ import annotations

#: What ANY Page connection needs first: the Page list to choose from, its engagement data, and
#: `pages_manage_metadata` — the permission that lets the app subscribe itself to the Page's
#: webhook fields at all. Neither chat nor posts work without these three.
PAGES_BASE_SCOPES = "pages_show_list,pages_read_engagement,pages_manage_metadata"

#: What a store that only chats on Messenger is asked for: the base grant plus the inbox.
MESSENGER_SCOPES = PAGES_BASE_SCOPES + ",pages_messaging"

#: The Facebook channel is the Page's chat PLUS its own posts, comments and numbers, so it asks for
#: what Meta's Pages API demands for each (developers.facebook.com/docs/pages-api): publish a post
#: (pages_manage_posts), reply to / hide / delete / like a comment (pages_manage_engagement), read
#: what people wrote on the Page (pages_read_user_content) and read its insights (read_insights).
#: Without them Meta refuses every one of those calls on a real Page. Messenger keeps the narrow
#: list: a store that only chats must not be asked to let us post for it.
FACEBOOK_PAGE_SCOPES = (
    "pages_manage_posts",
    "pages_manage_engagement",
    "pages_read_user_content",
    "read_insights",
)
#: What managing the Page's own content needs — and ONLY that. A Page connection and a Messenger
#: connection are two FIHRIST functions with two permission sets, even though Meta delivers both
#: over one Page object: chat always lands on the Messenger capability
#: (gateway/meta_page_events.py routes every `messaging` entry there), so this list never asks a
#: store that only manages posts for permission to read its customers' messages.
FACEBOOK_MANAGEMENT_SCOPES = PAGES_BASE_SCOPES + "," + ",".join(FACEBOOK_PAGE_SCOPES)

#: The one Facebook feature that is really a Messenger message: the private reply to a commenter.
#: It needs `pages_messaging`, which this connection does not request — the Messenger connection on
#: the same Page does. The capability is reported as `needs_permission` until that grant exists
#: instead of being bundled into the Page dialog (docs/channels/facebook-scopes.md).
FACEBOOK_PRIVATE_REPLY_SCOPES = ("pages_messaging",)

#: What the Facebook dialog asks for: page management, nothing of Messenger's.
FACEBOOK_SCOPES = FACEBOOK_MANAGEMENT_SCOPES


def missing_facebook_scopes(granted: object) -> list[str]:
    """The Page permissions a Facebook connection still lacks, in the order we ask for them.

    `granted` is what was recorded when the Page connected (`_connection.granted_scopes`). A
    connection made before these permissions existed recorded nothing, so every one of them is
    missing, and the owner is told to connect once more instead of meeting a Meta refusal on the
    first post.
    """
    have = {str(x) for x in granted} if isinstance(granted, (list, tuple, set)) else set()
    return [scope for scope in FACEBOOK_PAGE_SCOPES if scope not in have]


def missing_private_reply_scopes(granted: object) -> list[str]:
    """`pages_messaging`, when the Page connection does not hold it.

    A private reply is a Messenger message, so it needs the Messenger permission. A store that
    manages posts but never linked Messenger gets an explanation instead of a Meta refusal.
    """
    have = {str(x) for x in granted} if isinstance(granted, (list, tuple, set)) else set()
    return [scope for scope in FACEBOOK_PRIVATE_REPLY_SCOPES if scope not in have]


#: What an Instagram connection needs beyond chat: DMs, comments, publishing and insights.
#: Missing one does not stop the account linking (DMs may still work) but the matching feature
#: fails, so the connection lists them and the owner can connect again. Insights is here because
#: the post insights tab calls `/{media_id}/insights`, which Meta refuses without
#: `instagram_manage_insights` (docs/channels/instagram-permissions.md, §5).
INSTAGRAM_REQUIRED_SCOPES = (
    "instagram_manage_messages",
    "instagram_manage_comments",
    "instagram_content_publish",
    "instagram_manage_insights",
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
