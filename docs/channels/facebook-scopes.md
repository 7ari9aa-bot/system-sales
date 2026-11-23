# Facebook Page scopes vs Messenger scopes

Meta delivers both the Page's public news and its private chat over **one Page object** and one
webhook callback (`/webhooks/meta/page`). That is a fact about Meta, not a design choice for us:
FIHRIST still treats **Facebook Page management** and **Messenger inbox** as two separate
functions, with two separate connections and two separate permission sets. This page records
exactly which permission belongs to which function, and why.

## The rule

| Function | Connection | Permissions asked for | Why |
|---|---|---|---|
| Facebook Page management | `facebook` | `pages_show_list`, `pages_read_engagement`, `pages_manage_metadata`, `pages_manage_posts`, `pages_manage_engagement`, `pages_read_user_content`, `read_insights` | Meta's Pages API needs each of these for the call it backs: publishing, moderating comments, reading what people wrote, and reading insights |
| Messenger inbox | `messenger` | `pages_show_list`, `pages_read_engagement`, `pages_manage_metadata`, `pages_messaging` | the inbox, staff-reply sync, handover, message edits, reactions and platform settings all live on `pages_messaging` |

The two lists share only the three base permissions (`pages_show_list`, `pages_read_engagement`,
`pages_manage_metadata`) — the ones without which no Page connection works at all. Neither list
asks for the other's function-specific permission.

Source: `backend/app/modules/customers/meta_scopes.py` (`FACEBOOK_MANAGEMENT_SCOPES`,
`MESSENGER_SCOPES`, `FACEBOOK_PRIVATE_REPLY_SCOPES`), pinned by
`backend/tests/test_meta_capability_scopes.py` and `backend/tests/test_facebook_page_scopes.py`.

## Why the Page dialog no longer asks for `pages_messaging`

Chat never lands on the Facebook capability. `route_page_payload` in
`backend/app/modules/conversations/gateway/meta_page_events.py` splits every signed Page delivery
and sends every `messaging` (and `standby`) entry to the **Messenger** capability; only `changes`
goes to **Facebook**. So a Facebook connection has nothing to answer with `pages_messaging`, and
asking a store that only publishes posts and moderates comments to hand over its customers'
inbox was the exact bundling the review flagged.

## The one Page feature that really is a Messenger message

A **private reply** to a commenter (`POST /facebook/comments/{id}/private-reply`) is a Messenger
message sent by the Page, so it needs `pages_messaging`. It is now declared as its own capability:

```json
{"key": "private_reply", "scopes": ["pages_messaging"], "fields": [], "live_fields": []}
```

`capability_states` therefore reports it as `needs_permission` until the Messenger connection on
the same Page grants `pages_messaging`, instead of hiding it or shipping a button Meta refuses.
The route refuses with an actionable message ("connect Messenger for this Page first") rather than
letting Meta answer with an error code the merchant cannot act on.

## Which Pages each function is offered

`_messaging_pages` in `backend/app/modules/customers/meta_oauth.py` filters the Page list by the
task the chosen function actually needs:

* **Messenger** keeps a Page whose tasks include `MESSAGING` or `MANAGE`.
* **Facebook** keeps a Page whose tasks include `MANAGE` — posting, moderating and reading
  insights are Page management, and requiring `MESSAGING` there would hide a Page the owner can
  perfectly well manage.

A Page whose `tasks` list is missing (older Graph answers) is kept for both. A Page whose only
task is `ADVERTISE` is never offered to either.

## What this changes for an existing connection

A Facebook connection made before this split recorded `pages_messaging` in
`_connection.granted_scopes`. Nothing breaks: the extra grant is simply not used by this function,
and the private-reply capability reports `available` for it because the grant is there. A store
that connects Facebook today is asked for page management only, and the private reply shows as
`needs_permission` until Messenger is linked.
