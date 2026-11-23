# Page activity: the notifications feed, on the server

The Facebook notifications screen (`/facebook/activity`) used to be rebuilt in the browser on
every load, from the Page's post list, with its read mark in `localStorage`. The review named three
consequences, and all three are fixed by one table.

| Before | Now |
|---|---|
| A new post, an edited post, a deleted post, a reaction or a video produced **no notification** — the screen only ever walked post comments | The webhook writes one `page_activity` row per event, whatever the screen would have derived |
| A **mention** was invisible until someone opened the post | A mention is a row of its own, even though Meta sends ids only (no author, no text) |
| "Mark all as read" was a **per-browser** key, so one staff member reading a notification left it unread on every other device | The read mark is a column (`read_at`), written once for the whole tenant |

## What records an event

`backend/app/modules/conversations/gateway/ingest.py` already applied the Page's feed changes to
the post rows (`PageEventProcessor.apply`). Right next to it, the same `changes` list is passed to
`PageActivityService.record_changes`, so one delivery does both jobs:

* `apply` keeps the merchant's posts and reactions **correct**;
* `record_changes` keeps the merchant **informed**.

The two are independent on purpose. `apply` counts a change for a post we do not hold as
`unknown_post` and changes nothing — but "a post was published" is still news, so the activity row
is written anyway. The merchant's Page may simply have been connected after that post was written.

## Idempotence

Meta retries a webhook delivery for up to seven days. `dedup_key` is
`channel:kind:object_id:<epoch seconds>`, unique per tenant, so a replay updates nothing instead of
adding a second notification. The timestamp is part of the key deliberately: two reactions on the
same post a minute apart are two events, while the same delivery twice is one.

## API

| Route | What it does |
|---|---|
| `GET /facebook/activity?only_unread=&limit=` | The newest events first, with `read` per row and an `unread` count |
| `POST /facebook/activity/read` | Marks everything up to now read for the whole tenant; returns how many rows changed |

Both require the Facebook channel to be connected, and read needs `conversations:read` while the
read mark needs `conversations:write`.

## The screen

`frontend/src/pages/facebook/FacebookActivityPage.jsx` now renders two sources in one list:

* **comments** — still from the post list, because that is where the author name and the text live;
* **the server's events** — every kind except `comment`, which would otherwise appear twice.

`localStorage` is no longer read or written by this screen. The kinds and their one-line Arabic
summaries live in `page_activity_service.KINDS` / `summary_for`, so the screen, the API and the
tests share one vocabulary.

## Tests

* `backend/tests/test_page_activity.py` — each event the report named becomes a row, a replay does
  not duplicate, an event for an unknown post is still recorded, the read mark is one tenant-wide
  write, and the feed is tenant- and channel-scoped.
* `frontend/src/pages/facebook/FacebookActivityPage.test.jsx` — the server's events render, and a
  comment is not shown twice.
