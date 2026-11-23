"""Spec §26 family — Facebook PAGE channel adapter (NEW).

A Facebook connection and a Messenger connection speak the IDENTICAL Meta
Graph protocol (page token, X-Hub-Signature-256, /me/messages): the only
difference is the integration `provider` value the owner connected through.
This adapter therefore REUSES the Messenger parsing/sending verbatim and
changes only the registry key, so:

* `/webhooks/facebook` (GET verify + POST) is served by the generic
  /webhooks/{channel} dispatcher the moment this adapter is registered;
* `resolve_channel_tenant('facebook', page_id)` matches the page id stored in
  `config.account_id` by the platform connection spec — the SQL function is
  identity-generic, so no migration is needed;
* sending goes through the same `provider.messenger` breaker (same endpoint).
"""

from app.modules.conversations.gateway.base import InboundComment
from app.modules.conversations.gateway.base import InboundComment
from app.modules.conversations.gateway.messenger import MessengerAdapter


class FacebookPageAdapter(MessengerAdapter):
    """Facebook Page messaging — Messenger's protocol under the page's name.

    The webhook handshake and signature are INHERITED on purpose: they used to be re-implemented
    here with different fallbacks, so one server could pass Meta's check on one webhook and fail
    it on the other. Same protocol, same app, same rule.
    """

    name = "facebook"
    channel = "facebook"

    def parse_comments(self, payload: dict) -> list[InboundComment]:
        """``feed`` comments (inherited) plus the Page's own mention changes.

        A Page tag is NOT a feed change: Meta sends it on field ``mention`` with the post, and the
        comment when the tag sits in one. Messenger's parser reads only ``feed``/``comments``, so
        the subscription asked for ``mention`` and every tag arrived and produced nothing.
        """
        return [*super().parse_comments(payload), *self.parse_mentions(payload)]

    @staticmethod
    def parse_mentions(payload: dict) -> list[InboundComment]:
        """Someone @-mentioned the Page (field ``mention``, also seen written ``mentions``).

        The tag is stored as a comment row with verb ``mention`` so the merchant sees it in
        Activity, keyed by the comment id (or the post id for a caption tag) so a redelivery is
        one row. Meta sends the message text only sometimes; the row is kept either way.
        """
        out: list[InboundComment] = []
        for entry in payload.get("entry", []) or []:
            for change in entry.get("changes", []) or []:
                if change.get("field") not in ("mention", "mentions"):
                    continue
                value = change.get("value") or {}
                post_id = str(value.get("post_id") or "").strip() or None
                comment_id = str(value.get("comment_id") or "").strip()
                key = comment_id or post_id
                if not key:
                    continue
                sender = str(value.get("sender_id") or value.get("from_id") or "").strip()
                message = value.get("message")
                body = message.strip() if isinstance(message, str) and message.strip() else None
                out.append(
                    InboundComment(
                        platform_comment_id=f"mention:{key}",
                        post_id=post_id,
                        parent_comment_id=None,
                        author_ref=sender or None,
                        author_name=None,
                        body=body,
                        verb="mention",
                        raw=value,
                    )
                )
        return out


    #: The Page's `mention` field arrives singular (unlike Instagram's `mentions`). Both are
    #: accepted: Meta has used each spelling on this object, and a tag must not vanish because of
    #: a plural.
    _MENTION_FIELDS = ("mention", "mentions")

    def parse_feed_events(self, payload: dict) -> list[dict]:
        """The Page's feed changes, as Meta sent them, for the Page Event Processor.

        Returned raw on purpose: the processor decides what a `post`, `share`, `reaction` or
        `publish` change means, and it needs the untouched value to do that. Comment changes are
        included so the processor can count them, but they are stored by the comment parser.
        """
        out: list[dict] = []
        for entry in payload.get("entry", []) or []:
            for change in entry.get("changes", []) or []:
                if change.get("field") in ("feed", "mention", "mentions"):
                    out.append(change)
        return out

    def parse_mentions(self, payload: dict) -> list[InboundComment]:
        """Someone @-mentioned the Page (field ``mention``).

        Meta sends IDS ONLY here: ``post_id`` for a tag in a post, and ``comment_id`` when the tag
        sits in a comment. No text and no author name, so the row keeps the ids and the merchant
        sees «أشار إليك أحدهم» instead of an empty comment body. The key is prefixed with
        ``mention:`` so a tag can never collide with a real comment id, and it is stable so a
        redelivery is one row.
        """
        out: list[InboundComment] = []
        for entry in payload.get("entry", []) or []:
            for change in entry.get("changes", []) or []:
                if change.get("field") not in self._MENTION_FIELDS:
                    continue
                value = change.get("value") or {}
                post_id = str(value.get("post_id") or value.get("media_id") or "").strip()
                comment_id = str(value.get("comment_id") or "").strip()
                key = comment_id or post_id
                if not key:
                    continue
                out.append(
                    InboundComment(
                        platform_comment_id=f"mention:{key}",
                        post_id=post_id or None,
                        parent_comment_id=comment_id or None,
                        author_ref=str(value.get("sender_id") or "") or None,
                        author_name=None,
                        body=None,
                        verb="mention",
                        raw=value,
                    )
                )
        return out


facebook_adapter = FacebookPageAdapter()
