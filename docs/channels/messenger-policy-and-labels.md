# Messenger: policy enforcement and conversation labels

Two Messenger gaps from the report, both closed in the same place the rest of Messenger lives
(`gateway/messenger.py`, `routers/messenger_profile.py`) so Messenger stays its own FIHRIST function
with its own `pages_messaging` permission.

## Policy enforcement: Meta warning, then blocking, the Page

Meta sends `messaging_policy_enforcement` when a Page breaks a messaging policy. Nothing read that
field, so a Page Meta had warned — and then blocked — looked perfectly healthy in FIHRIST while
every reply the agent wrote went nowhere.

`MessengerAdapter.parse_policy_events()` turns the field into plain data and `_apply_policy_events()`
in `gateway/ingest.py` acts on it:

| Meta says | FIHRIST does |
|---|---|
| `action: WARN` | records `messaging_policy` in the channel's `webhook_health` and writes one notification. **Nothing else** — a warning must not cost the owner a working channel. |
| `action: BLOCK` | the same record, and an `active`/`connected` channel moves to `restricted`, which every diagnostics surface already reads |

Rules the hook keeps:

* the field arrives under both `messaging_policy_enforcement` and `policy_enforcement`; both are read;
* an event with no `action` is **ignored**, not guessed — a false "blocked" is worse than a missing one;
* a `disconnected` or logged-out channel is never moved, forward or back: only reconnecting clears a
  restriction;
* the notification is written through the Page activity feed with the event's own timestamp in the
  dedup key, so Meta's multi-day retries update one row instead of nagging the owner per delivery.

## Conversation labels

Meta keeps a label on the thread itself (`custom_labels` on the PSID), so two staff members on two
devices see the same label, and the owner's Meta inbox sees it too.

| Route | What it does |
|---|---|
| `POST /api/v1/messenger/labels/{conversation_id}` | attach labels to one thread |
| `DELETE /api/v1/messenger/labels/{conversation_id}` | remove labels from one thread |

The PSID is read from the conversation's own Messenger identity (`customer_identities`), never from
the request body, unless the caller names one explicitly — a PSID typed into a request could label
somebody else's thread, and the Page token has the power to do it. The permission is checked
**before** the thread is looked up, so a caller without `pages_messaging` is told that, not whether
the id exists.

## Tests

* `tests/test_messenger_policy_enforcement.py` — both field spellings, an action-less event ignored,
  BLOCK restricts an active channel and notifies, WARN records without restricting, a disconnected
  channel is not moved, a redelivery keeps one dedup key.
* `tests/test_messenger_profile_routes.py` — labels reach the conversation's own PSID, removal sends
  the names as `fields`, an empty list never leaves the server, and a missing `pages_messaging` is a
  `403` with no Meta call.

## Referral / ad context

A Click-to-Messenger or Click-to-Direct referral used to survive as a single `from_ad: True` flag
plus a text line ("ADS / summer / ad 120210"). The campaign, ad id and headline Meta sent were
thrown away, so the agent could see that an ad brought the person in but not which one.

`IngestService._referral_details()` keeps only the documented fields (`source`, `type`, `ref`,
`ad_id`, `ref_source`, `headline`, `ctwa_clid`), each a trimmed string of at most 255 characters,
in the message's `provider_metadata.referral`. `from_ad` is still set from the same data, so the
7-day ad window rule is unchanged. The thread presents it as a card (`type: referral`, `kind: ad`
for `source: ADS`, `kind: link` for an m.me/short link), and a row written before this check existed
still renders safely because only printable strings leave the API.

Tests: `tests/test_referral_context.py`.
