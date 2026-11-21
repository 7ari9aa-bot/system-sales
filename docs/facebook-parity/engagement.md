# Facebook Page engagement parity matrix

Scope: Meta Graph API for FACEBOOK PAGE ENGAGEMENT only (comments, replies, reactions,
mentions, private replies, moderation). Nothing here covers Instagram, WhatsApp, messaging
threads or ads.

Sources are Meta's own docs, read on 2026-11-21 against Graph API v27.0:

* Comment reference: https://developers.facebook.com/docs/graph-api/reference/comment/
* Comment Likes edge: https://developers.facebook.com/docs/graph-api/reference/comment/likes/
* Comment Reactions edge: https://developers.facebook.com/docs/graph-api/reference/comment/reactions/
* Object Comments edge: https://developers.facebook.com/docs/graph-api/reference/object/comments/
* Object Likes edge: https://developers.facebook.com/docs/graph-api/reference/object/likes/
* Post Comments edge: https://developers.facebook.com/docs/graph-api/reference/post/comments/
* Post reference (shares): https://developers.facebook.com/docs/graph-api/reference/post/
* Page Post reference (is_pinned): https://developers.facebook.com/docs/graph-api/reference/page-post/
* Page Blocked edge: https://developers.facebook.com/docs/graph-api/reference/page/blocked/
* Pages API Comments and @mentions guide: https://developers.facebook.com/documentation/pages-api/comments-mentions
* Private Replies: https://developers.facebook.com/documentation/business-messaging/messenger-platform/discovery/private-replies
* Page webhooks reference (feed, mention): https://developers.facebook.com/docs/graph-api/webhooks/reference/page/

Status legend:

* DONE - the capability exists in Meta's API and our app implements it.
* MISSING-ALLOWED - Meta's API allows it, our app does not implement it yet.
* API-FORBIDDEN - Meta's API does not offer it at all.
* UNVERIFIED - Meta's docs do not answer it clearly enough to claim either way.

The "Implemented in our app?" column was checked by grepping
`backend/app/modules/conversations` and `frontend/src/components/facebook`.

| Capability | Endpoint | Permission/feature | Implemented in our app? | Status | Doc URL |
| --- | --- | --- | --- | --- | --- |
| Read comments on a Page post | `GET /{object-id}/comments` (fields `message,from,created_time,like_count,comment_count,is_hidden,parent,permalink_url`) | Page access token; `pages_read_engagement` plus `pages_read_user_content` for other users' comments; `MODERATE` task needed to get comment ids for a Page post | Yes: `gateway/facebook_pages.py:list_comments` (COMMENT_FIELDS, paged by `after`), `facebook_service.py:sync_comments`, route `GET /facebook/posts/{post_id}/comments` | DONE | https://developers.facebook.com/docs/graph-api/reference/object/comments/ |
| Read replies of a comment | `GET /{comment-id}/comments` (our read inlines `comments.limit(25){...}` on each top-level comment) | Same as reading comments | Yes: inline sub-edge in `COMMENT_FIELDS`/`list_comments`, persisted with `parent_comment_id` | DONE | https://developers.facebook.com/docs/graph-api/reference/comment/ |
| Create a comment on a post (as the Page) | `POST /{object-id}/comments` with `message` | `pages_manage_engagement`, `MODERATE` task, Page access token; a User token fails with error 1705 | Yes: `gateway/facebook_pages.py:comment`, route `POST /facebook/objects/{object_id}/comments` | DONE | https://developers.facebook.com/docs/graph-api/reference/object/comments/ |
| Reply to a comment | `POST /{comment-id}/comments` with `message` (Facebook threads are one level deep; reply to the root comment) | `pages_manage_engagement`, `MODERATE` task; `can_comment` on the comment says whether a reply is possible | Yes: `facebook_service.py:reply` posts to the root comment id and stores `parent_comment_id` | DONE | https://developers.facebook.com/documentation/pages-api/comments-mentions |
| Edit a comment | `POST /{comment-id}` with `message` | `pages_manage_engagement`; Meta's Updating block on the Comment reference accepts `message`, but in practice a Page may only edit comments it authored | No: no `update_comment` in `gateway/facebook_pages.py`, no edit route, no edit control in `FbComment.jsx` | MISSING-ALLOWED | https://developers.facebook.com/docs/graph-api/reference/comment/ |
| Delete a comment | `DELETE /{comment-id}` | `pages_manage_engagement` (a Page can delete comments on its own posts) | Yes: `gateway/facebook_pages.py:delete_comment`, `facebook_service.py:remove_comment`, route `DELETE /facebook/comments/{comment_id}`, Delete control in `FbComment.jsx` | DONE | https://developers.facebook.com/docs/graph-api/reference/comment/ |
| Hide / unhide a comment | `POST /{comment-id}` with `is_hidden=true|false` (only applicable to Page comments) | `pages_manage_engagement`; `can_hide` field tells whether the viewer may hide | Yes: `gateway/facebook_pages.py:set_comment_hidden`, route `POST /facebook/comments/{comment_id}/hide`, Hide/Unhide control in `FbComment.jsx` | DONE | https://developers.facebook.com/docs/graph-api/reference/comment/ |
| Like a comment as the Page | `POST /{object-id}/likes` with a Page access token | `pages_manage_engagement` plus a Page user able to `CREATE_CONTENT`; the object must not already be liked and the Page must be able to like it | Yes: `gateway/facebook_pages.py:set_like`, route `POST /facebook/objects/{object_id}/like`, Like control in `FbComment.jsx` | DONE | https://developers.facebook.com/docs/graph-api/reference/object/likes/ |
| Unlike a comment | `DELETE /{object-id}/likes` | `pages_manage_engagement` plus a Page user able to `MODERATE` | Yes: same `set_like(liked=False)` path, toggled from `FbComment.jsx` | DONE | https://developers.facebook.com/docs/graph-api/reference/object/likes/ |
| Like a comment authored by the Page itself | `POST /{comment-id}/likes` where the comment's `from` is the Page | Docs are silent on self-authored comments. The Likes edge only says the Page "must also be able to like the object" and that it must not already be liked; the `can_like` summary field is the only way to know. Facebook's own web UI does not offer a Like control on your own comment, so `can_like` is expected to come back false. Our app does not attempt it and hides the control for Page-authored comments (`!comment.isPage` in `FbComment.jsx`) | Not attempted; UI suppressed for `isPage` comments | UNVERIFIED | https://developers.facebook.com/docs/graph-api/reference/comment/likes/ |
| Comment attachments (photo) | `POST /{object-id}/comments` with `attachment_id` (unpublished photo), `attachment_url` (image URL) or `source` (multipart) | `pages_manage_engagement`; one of `attachment_id`, `attachment_share_url`, `attachment_url`, `source`, `message` must be provided | No: `comment()` sends only `message`; no attachment control in `FbComment.jsx` | MISSING-ALLOWED | https://developers.facebook.com/docs/graph-api/reference/object/comments/ |
| Comment attachments (animated GIF) | `POST /{object-id}/comments` with `attachment_share_url` set to a GIF URL | `pages_manage_engagement` | No: not sent, no picker in the UI | MISSING-ALLOWED | https://developers.facebook.com/docs/graph-api/reference/object/comments/ |
| Comment attachments (sticker) | No documented parameter. The Comments publish fields are `attachment_id`, `attachment_share_url`, `attachment_url`, `source`, `message` only | n/a | No | API-FORBIDDEN | https://developers.facebook.com/docs/graph-api/reference/object/comments/ |
| Comment @mention tagging | `@[PSID]` (or `@[PSID,PSID,...]`) inside `message` of `POST /{object-id}/comments` | `pages_manage_engagement` plus the **Page Mentioning** feature; the Page must allow "Others Tagging this Page"; a Page may only mention a person who commented on or created the post | Yes: `gateway/facebook_pages.py:mention_tag` builds `@[id,...]`, `facebook_service.py:resolve_mentions` refuses anyone who did not write on the thread, `FbComment.jsx` shows a removable mention chip | DONE | https://developers.facebook.com/documentation/pages-api/comments-mentions |
| Comment ordering (chronological / reverse) | `GET /{object-id}/comments?order=chronological|reverse_chronological`; if the comments can be ranked, Meta returns ranked order regardless | Read permissions above | Partly: `list_comments` hardcodes `order=chronological`; no caller or UI can pick reverse or ranked | MISSING-ALLOWED | https://developers.facebook.com/docs/graph-api/reference/post/comments/ |
| Comment filters (`toplevel` / `stream`, live low-quality filter) | `GET /{object-id}/comments?filter=toplevel|stream&live_filter=filter_low_quality|no_filter` | Read permissions above | Partly: `list_comments` hardcodes `filter=toplevel`; `stream` and `live_filter` are never sent | MISSING-ALLOWED | https://developers.facebook.com/docs/graph-api/reference/post/comments/ |
| Pin a comment | No documented comment-level pin field or edge. `is_pinned` exists on the Page **Post** object, not on Comment | n/a for comments | No | API-FORBIDDEN | https://developers.facebook.com/docs/graph-api/reference/comment/ |
| Pin a post (for contrast with the row above) | `POST /{page-post-id}` with `is_pinned=true|false` | `pages_manage_posts` / `pages_manage_engagement` with `CREATE_CONTENT` | No: `update_post` sends only `message` | MISSING-ALLOWED | https://developers.facebook.com/docs/graph-api/reference/page-post/ |
| Reaction types readable | `GET /{object-id}/reactions?type=LIKE|LOVE|WOW|HAHA|SAD|ANGRY|THANKFUL|PRIDE|CARE|FIRE|HUNDRED` (works on Comment and Post) | Read permissions of the parent object (`pages_read_engagement`) | Partly: `get_reaction_breakdown` reads 6 kinds (LIKE, LOVE, HAHA, WOW, SAD, ANGRY); THANKFUL, PRIDE, CARE, FIRE, HUNDRED are not requested | DONE (6 of 11 kinds) | https://developers.facebook.com/docs/graph-api/reference/comment/reactions/ |
| Reaction types writable | `POST /{object-id}/reactions` - Meta answers "This operation is not supported". The only write path is `POST /{object-id}/likes` (LIKE only) | `pages_manage_engagement` | Correct by construction: only the like write exists (`set_like`) | DONE (like only, as Meta allows) | https://developers.facebook.com/docs/graph-api/reference/comment/reactions/ |
| Reaction counts (per kind and total) | `GET /{object-id}/reactions.type(LOVE).limit(0).summary(true)` aliased per kind, or `GET /{object-id}/reactions?summary=total_count` | Read permissions of the parent object | Yes: `get_reaction_breakdown` reads all kinds in one aliased request, route `GET /facebook/objects/{object_id}/reactions`, drawn by `FbReactionSummary.jsx` | DONE | https://developers.facebook.com/docs/graph-api/reference/comment/reactions/ |
| Like count on a comment | `like_count` field on Comment, or `GET /{comment-id}/likes?summary=true` (`total_count`, plus `can_like`, `has_liked`) | Read permissions of the parent object | Yes: `like_count` is in `COMMENT_FIELDS` and stored on `SocialComment`, shown in `FbComment.jsx` | DONE | https://developers.facebook.com/docs/graph-api/reference/comment/likes/ |
| Shares count of a post | `shares` field on Post / Page Post (the share count may include deleted and invisible shares) | Read permissions of the post | Fetched but dropped: `POST_FIELDS` asks for `shares`, but `SocialPost` has no shares column and no route or screen exposes it | MISSING-ALLOWED | https://developers.facebook.com/docs/graph-api/reference/post/ |
| Private reply to a commenter | `POST /{page-id}/messages` with `recipient={"comment_id":"..."}` and `message` | `pages_messaging` plus a Page user with the `MESSAGING` task; **one message per comment**, only within **7 days** of the comment; cannot be sent to another Page | Yes: `gateway/facebook_pages.py:private_reply`, `facebook_service.py:private_reply`, route `POST /facebook/comments/{comment_id}/private-reply`; `FbComment.jsx` hides the button after one send and outside 7 days (`canPrivateReply`) | DONE | https://developers.facebook.com/documentation/business-messaging/messenger-platform/discovery/private-replies |
| Block a user from the Page | `POST /{page-id}/blocked` with `psid` (Page-scoped), `asid` (app-scoped) or `user`; returns a map of id to bool | Page access token with `MODERATE`; errors name `pages_manage_metadata` / `pages_read_user_content` (283). Limits: cannot reblock soon after unblocking, maximum number of blocks | No: no blocked edge in the gateway, no route, no UI | MISSING-ALLOWED | https://developers.facebook.com/docs/graph-api/reference/page/blocked/ |
| Unblock a user | `DELETE /{page-id}/blocked` with `psid`, `asid`, `uid` or `user` | Same as blocking | No | MISSING-ALLOWED | https://developers.facebook.com/docs/graph-api/reference/page/blocked/ |
| List blocked users | `GET /{page-id}/blocked` | `pages_read_engagement` / `pages_read_user_content` (error 283 names both) | No | MISSING-ALLOWED | https://developers.facebook.com/docs/graph-api/reference/page/blocked/ |
| Report a comment as spam | No documented Graph API endpoint. The Comment reference has read, create, update (`is_hidden`, `message`), delete and no report action; Page moderation is a Page setting, not an API call | n/a | No | API-FORBIDDEN | https://developers.facebook.com/docs/graph-api/reference/comment/ |
| Comment webhooks (`feed` field) | Webhook field `feed`, change `value.item=comment` with `verb` add/edited/remove, `comment_id`, `post_id`, `parent_id`, `from`, `message`, `created_time` | `pages_manage_metadata` to subscribe; the app must be subscribed to the Page's `feed` field | Yes: `gateway/base.py:parse_meta_comment_changes` normalizes `feed` and `comments`, `gateway/messenger.py:parse_comments`, wired in `gateway/ingest.py` into `SocialCommentService` | DONE | https://developers.facebook.com/docs/graph-api/webhooks/reference/page/ |
| Page mentions outbound (tagging a Page or person) | `@[page-id]` in a post `message`, `@[PSID]` in a comment `message` | `pages_manage_engagement`; **Page Mentioning** feature, subject to review | Yes for comments (see the mention row); post-level page tagging is not offered | DONE (comments only) | https://developers.facebook.com/docs/graph-api/reference/object/comments/ |
| Page mentions inbound (someone mentions the Page) | Webhook field `mention`, carrying `post_id`, `comment_id`, `message`, `link`, `created_time`; some ids may be withheld for permissions or privacy | `pages_manage_metadata` to subscribe to `mention` | No: only `feed` and `comments` changes are parsed in `gateway/base.py`; `mention` is not handled | MISSING-ALLOWED | https://developers.facebook.com/docs/graph-api/webhooks/reference/page/ |

## Notes worth acting on

1. **Page liking its own comment.** Meta's docs never state it either way. The Likes edge requires
   that the Page "must also be able to like the object", and the Comment Likes summary exposes
   `can_like` for exactly this question. Facebook's web UI shows no Like control under a Page's own
   comment. Treat it as not allowed until `can_like` is read for a real self-authored comment; the
   app already suppresses the button for `isPage` comments, so nothing is lost either way.
2. **Ranked order wins.** `order` is only a preference: if Meta can rank the comments it returns
   ranked order regardless, so a "chronological" toggle can never be guaranteed.
3. **Stickers are not a comment attachment.** Only photo (`attachment_id`, `attachment_url`,
   `source`) and animated GIF (`attachment_share_url`) are documented.
4. **No spam-report endpoint exists.** Moderation is hide, delete, block. Reporting is a Facebook
   UI action, not a Graph API one.
5. **Shares is read but thrown away.** `POST_FIELDS` requests `shares` and the sync discards it,
   which is a one-column fix if the Posts screen ever needs a share count.
