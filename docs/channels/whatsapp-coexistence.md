# WhatsApp Coexistence

A coexistence number runs the merchant's **existing WhatsApp Business App and FIHRIST on the same
number at the same time**. It is not a second number, not a migration, and not a re-registration:
the phone app keeps working, and FIHRIST sees the same conversations.

That difference is the whole design. A Cloud-API-only number is *ours* — we register it, we own the
history, we are the only sender. A coexistence number is *shared*: Meta hands us an import of
history and contacts once, echoes back what the merchant types on the phone, and can take the number
away again. Everything below exists because of that.

## What is now true

| Area | Rule |
|---|---|
| Onboarding | `is_on_biz_app` + `platform_type` decide the mode. A Business App number is never recorded as `cloud_api`; a Cloud API-only number is rejected for this product. |
| Registration | `_register_phone_number` is **never** called on the coexistence path; the app is still subscribed to the WABA. |
| Sync | Contacts (`smb_app_state_sync`) and history (`history`) are requested **once** per onboarding epoch, inside Meta's 24-hour window. A separate committed reservation is written before either Meta request; ambiguous outcomes are never resent automatically. |
| History | Nested phase/chunk/progress metadata, 2593109 decline webhooks, BSUID threads and message statuses are parsed. Messages are stored at Meta's timestamp, **no AI answer**, and no fake 24-hour service window. |
| Echoes | A message the merchant sends from the phone lands as a **human** outbound message and pulls the thread to `waiting_human`, so the agent cannot answer the same customer twice. |
| Identity | The phone when there is one, the **BSUID** when there is not, including history, contacts and app echoes. A message naming nobody is refused. |
| Lifecycle | `PARTNER_REMOVED` / `ACCOUNT_OFFBOARDED` disconnect the channel and stop sending; `ACCOUNT_RECONNECTED` requires the number to be verified again. |
| Throughput | 20 messages a second **per phone number**, paced in Redis so every worker shares the budget. |

## The sync state machine

`whatsapp_sync_runs` (migration `fe2026112401`) holds one row per sync attempt, per onboarding epoch:

```
ONBOARDING → CONNECTED_PENDING_SYNC → CONTACTS_SYNC_* → HISTORY_SYNC_* → READY
                                                     ↘ HISTORY_NOT_SHARED
                                   ↘ SYNC_FAILED
any → OFFBOARDED
```

* One request per epoch. `request_sync` refuses a second request for the same
  `(phone_number_id, sync_type, onboarding_epoch)` and returns the existing run with its
  `request_id`, so a retried connect replays instead of asking Meta twice.
* The 24-hour deadline is Meta's, not ours: a request after it cannot be made, and the run records
  `deadline_expired` rather than pretending it is still coming.
* `READY` requires either a completed history transfer **or** an explicit refusal (2593109). A
  silent timeout is `SYNC_FAILED`, never `READY`.
* Progress arrives out of order (`phase`, `chunk_order`, `progress`). Each chunk is stored
  idempotently, and a late chunk folds into progress without walking a completed transfer backwards.

## The three webhook fields

Subscribed alongside `messages`: `history`, `smb_app_state_sync`, `smb_message_echoes`.
`meta_channel_diagnostics.REQUIRED_FIELDS` names all of them, so a dashboard missing one is
**reported**, not assumed healthy.

They are parsed in `gateway/whatsapp_coexistence.py`, never inside `parse_inbound` — an import must
not be mistaken for a live message, because that is what would make the agent answer a
six-month-old conversation.

| Field | Parser | Effect |
|---|---|---|
| `history` | `parse_history` | messages stored with `imported_from=whatsapp_history`, no outbox event |
| `smb_app_state_sync` | `parse_app_state_sync` | phone- and BSUID-keyed contacts reconcile to customers; timestamped removals mark the app-contact relation inactive without deleting customer history; **no** conversation is opened |
| `smb_message_echoes` | `parse_app_echoes` | outbound human message + `request_human_takeover` |
| `messages` (131060) | `parse_unsupported_notice` | a visible system notice is stored in the recipient's inbox thread; does not degrade the channel |

## Error codes that are not failures

* **2593109** — the merchant chose not to share history. That is an answer, not an error: both
  the immediate API refusal and the documented history webhook form end the run as
  `HISTORY_NOT_SHARED`; the channel can still reach `READY` once the contacts snapshot is received.
* **131060** — Meta received a message type we do not render. FIHRIST stores a system message in
  the affected recipient's inbox thread explaining why the customer message is missing.

## Identity: phone, BSUID, or nobody

```
customer_ref = msg.from        (phone)     → identity_type = "phone"
             | msg.from_user_id (BSUID)    → identity_type = "bsuid"
             | neither                     → the message is dropped at parse and refused at ingest
```

A BSUID is the only handle a number-less customer has. Before this, `from` was read alone, so every
such message arrived with an **empty** ref and they all collapsed onto one blank identity — two
different people in one thread, replies going nowhere. The parser indexes `contacts[]` by `user_id`
as well as `wa_id` so the name resolves, and `identity_type` / `username` / `parent_ref` are stored
in `CustomerIdentity.extra` (a phone number may not exist at all).

## Lifecycle events

`account_update` envelopes are placed by **`waba_info.waba_id`** first, falling back to `entry.id`:
for a coexistence number `entry.id` is not guaranteed to be the business account, and routing by it
put the event on a channel that does not exist.

| Event | Channel state | Sending |
|---|---|---|
| `PARTNER_REMOVED`, `ACCOUNT_OFFBOARDED` | `disconnected` (+ Meta's reason in `webhook_health.partner_removed`) | stopped |
| `ACCOUNT_RECONNECTED` | `reauth_required` | stopped until a connect verifies the number |
| `ACCOUNT_RESTRICTION`, `DISABLED_UPDATE`, `ACCOUNT_VIOLATION` | `restricted` | stopped |

The outbound worker refuses to send on a channel that is not `active`/`connected`. Without that
gate a disconnected channel kept "answering" people who could never receive it.

## Throughput

`gateway/whatsapp_throughput.py` takes a Redis slot per phone number before the provider call
(20/s, sliding window). The caller **paces** — it waits for the next slot — and only hands back a
retryable error when the wait exceeds the worker's backoff, so the message is retried rather than
lost. The budget is per number, so one busy number never slows another. No Redis means no blocking:
Meta enforces the same cap and says so itself.

## Inbox

A voice note is an `<audio>` element on the message's real media URL: play/pause, real duration, a
seekable progress bar, and an explicit failure state for an expired link. It used to be a toggle
over a hardcoded `0:14` with no audio at all.

### Who wrote an outbound message

Three writers share one thread on a coexistence number: the AI, a person replying in FIHRIST, and
the merchant typing in the WhatsApp Business app on their phone. Every imported message keeps its
origin in `provider_metadata.imported_from` (`whatsapp_business_app` for an echo,
`whatsapp_history` for the app's own log), the messages payload exposes it as `source`, and the
bubble footer labels it — **Business App**, **AI** or **FIHRIST**. Inbound messages carry no label
because the customer is the only sender on that side, and a deleted message shows its tombstone
instead. Without this, a reply the owner typed on their phone is drawn exactly like an AI reply,
which is the one confusion a coexistence launch cannot afford.

### The strip above the thread

`GET /api/v1/integrations/whatsapp/coexistence-status` (typed, in the OpenAPI lock) answers from
FIHRIST's own rows, never from Meta:

* `sync_state` is recomputed from `whatsapp_sync_runs` on every read — the cached
  `config["sync_state"]` written at connect time goes stale the moment a history chunk lands;
* `contacts` and `history` carry state, percentage, imported count, deadline and (clipped) error;
* `offboarded`, `disconnect_event` and `disconnect_reason` come from the `partner_removed` mark the
  lifecycle handler writes, so a `PARTNER_REMOVED` channel says so and links back to settings.

`CoexistenceBanner` renders it at the top of a WhatsApp thread: a progress bar with the running
half's real percentage and message count while the transfer is going, Meta's reason plus a
reconnect link when the number is disconnected, a plain statement (not a failure) when the merchant
declined history, and nothing at all once the state is `READY`. The hook polls only while the state
is unsettled, so an idle inbox makes no requests, and a failed read hides the strip instead of
breaking the thread.

## Tests

| File | Covers |
|---|---|
| `tests/test_whatsapp_coexistence_onboarding.py` | mode from `is_on_biz_app`/`platform_type`, registration skipped, replay returns the stored mode |
| `tests/test_whatsapp_coexistence_sync.py` | one request per epoch, `request_id`, deadline, the state machine, 2593109 |
| `tests/test_whatsapp_coexistence_payloads.py` | the three parsers, 131060, history timestamps and direction |
| `tests/test_whatsapp_coexistence_import.py` | history without an AI answer, out-of-order chunks, echo as human, contacts without conversations |
| `tests/test_whatsapp_bsuid_identity.py` | BSUID-only customers, empty ref refused |
| `tests/test_whatsapp_coexistence_lifecycle.py` | `waba_info.waba_id` routing, offboarding, reconnect, restriction |
| `tests/test_whatsapp_throughput.py` | 20/s per number, pacing, per-number isolation |
| `tests/test_whatsapp_coexistence_status.py` | the snapshot, copy for every state, `source` on the payload, the status route is typed |
| `src/components/inbox/ChannelChat.voice.test.jsx` | real audio, duration, failure state |
| `src/components/inbox/whatsapp/MessageSource.test.jsx` | Business App / AI / FIHRIST labels, no label inbound or deleted |
| `src/components/inbox/whatsapp/CoexistenceBanner.test.jsx` | syncing percentage, READY silence, disconnect with reason, declined history, failed sync |

The DB-backed ones need Postgres (`DATABASE_URL_APP`) and skip without it; the throughput pacing
test uses Redis and skips when it is not running.

## Still open

* Throughput visibility: the cap is enforced and a 130429 is reported, but no gauge shows a number's
  current rate.
* The settings card still shows the connect-time `sync_state`; the live picture lives in the inbox
  strip and in the status endpoint.
