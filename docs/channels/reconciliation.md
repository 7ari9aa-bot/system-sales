# Reconciliation: what Meta has that FIHRIST does not

A backfill with nothing to compare against is a walk with no conclusion. The report's Messenger gap
(a) was exactly that: `MessengerBackfill` could read a Page's conversations, but no code compared
the result to what is stored, so a webhook that failed for an hour left an invisible hole.

`app/modules/conversations/messenger_reconcile.py` draws the conclusion, and
`POST /api/v1/integrations/{id}/messenger-reconcile` runs it for one channel.

| Field | Meaning |
|---|---|
| `missing_locally` | people Meta can message that FIHRIST has never stored |
| `stale_locally` | people FIHRIST has that Meta's listing no longer shows |
| `stopped` | `exhausted` (the whole listing was read), `capped` (a bound stopped it), `error` |
| `bounds` | the pages / items / days this provider allows |

The local side is compared on `customer_identities.external_id` for the channel, because Meta's
thread id for a person **is** the PSID/IGSID that identity stores.

## Three rules that keep it honest

* **A capped or failed walk claims nothing.** `missing_locally` and `stale_locally` are only filled
  when `stopped == "exhausted"`; half a listing cannot prove absence.
* **A rate limit is an error with its reason**, never an empty result that reads as "all good".
* **Nothing is deleted on the strength of a listing.** Meta drops conversations from that listing for
  its own reasons, so `stale_locally` is a report, not a cleanup.
* **WhatsApp returns `supported: false`** — Meta exposes no history API, and no request is made.

## Tests

`tests/test_messenger_reconcile.py` (6) — a missing thread is named, a stale one is reported not
deleted, a capped walk claims nothing, a 429 is an error with its reason, the walk respects the
provider's bounds, and WhatsApp is unsupported without asking Meta anything.
