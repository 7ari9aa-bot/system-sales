# Manual check: a real Meta Business App number, end to end

Everything else in this channel is covered by fixtures. This is the part fixtures cannot prove:
Meta's own answers, its webhook order and the 24-hour window. Run it once per release, on a number
that really is on the WhatsApp Business app, with a second phone as the customer.

Each step has an expected result. A step that gives a different one is a bug: write down what you
saw (the sync row, the webhook payload, the log line) before trying again.

## 1. Link the number

Settings → Channels → WhatsApp → Connect, and complete the Meta popup on the phone that holds the
Business app.

* Expected: the popup closes, the channel shows **connected**, and
  `GET /api/v1/integrations/whatsapp/coexistence-status` reports
  `sync_state` `CONNECTED_PENDING_SYNC` or `CONTACTS_SYNC_IN_PROGRESS`, never `OFFBOARDED`.
* Expected in `whatsapp_sync_runs`: one `contacts` row and one `history` row for this epoch, each
  with `request_id` set and `state` `requested` (or `failed`/`not_shared` for history).
* Expected in the log: `whatsapp.sync_requested` twice, once per sync type, with different ids.
* If `POST /smb_app_data` answers 2593109 the merchant declined history: that is an answer, not a
  failure. The run must read `not_shared` and the channel must still become READY.

## 2. Contacts arrive

Wait up to a minute, then reload the channel card.

* Expected: the contacts half shows progress, and `snapshot_received_at` is set once the first
  `smb_app_state_sync` webhook lands.
* Expected: the run is **not** `completed` from that first webhook alone. It completes only on an
  explicit `progress: 100` from Meta, or when the 24-hour window closes, in which case the snapshot
  says `settled_by: "deadline"` and never claims the list was complete.
* Expected: contacts appear in Customers, and **no** conversation is opened by the import.

## 3. History arrives

* Expected: imported messages carry their original timestamps, appear as `source: whatsapp_history`
  in the inbox, and trigger **no** AI reply.
* Expected: a reply inside the history keeps its parent (open the thread, the quoted message is
  there). A reply whose parent was not in the import keeps `reply_to_provider_id` and shows no
  broken quote.
* Expected: media arrives as placeholders, not as broken images.
* Expected: two `history` elements in one webhook (if Meta sends them) advance progress
  independently: a later element never walks an earlier one backwards.

## 4. The phone app keeps working (this is the whole promise)

Send a message from the merchant's phone to the customer.

* Expected: it appears in the inbox as the merchant's own message, the conversation moves to
  **waiting_human**, and the AI stops answering it.
* Send the same message again from the phone after a history import already stored that wamid:
  expected the same outcome (handover), not a silent skip.
* Expected: `POST`ing a message from FIHRIST shows up in the phone app too.

## 5. A customer replies

* Expected: the message arrives once (no duplicate from the echo), the unread counter moves, and
  the AI answers only while the conversation is not in `waiting_human`.
* Send a sticker or a reaction the Cloud API cannot represent: expected a system notice
  (`131060`), unread counter moves, **no** AI turn.

## 6. Removal and re-link

Disconnect the number from the phone app (Business app → Linked devices / partner removal).

* Expected: `account_update` with `PARTNER_REMOVED` disconnects the channel, sending is blocked,
  and the inbox says so instead of failing silently.
* Re-link, then replay a webhook captured from the previous epoch.
* Expected: it is ignored (`attribute_chunk` finds no run for that request_id), stores no messages
  and does not complete the new run.

## 7. The stuck reservation

If a connect dies between "Meta was asked" and "the answer was stored", the run stays `dispatching`.

* Expected: after 15 minutes the status reports `needs_attention` with the request id, its age and
  the last error, and the channel card shows it.
* Expected: the reconcile action closes the run **without** a second `POST /smb_app_data`. Only a
  re-link can ask Meta again, which is Meta's rule, not ours.

## What this cannot prove

Real Meta payloads for a device we do not have (WhatsApp for Windows, WearOS) and Meta's behaviour
past the 24-hour window. Both are documented from Meta's own docs in
`docs/channels/whatsapp-coexistence-limits.md`, and both need a real number to confirm.
