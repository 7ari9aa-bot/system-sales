# Instagram: the account's numbers, and what the API will not do

Two report items, closed in `gateway/instagram.py` and exposed on `routers/social.py`.

## Profile matrix: readable, never writable

Instagram's Graph API **reads** a professional account's profile. Changing the username, name,
biography, website or picture happens in the Instagram app; there is no API write for them. That is a
platform limit, so it is recorded with its reason instead of a settings form that cannot save.

`GET /api/v1/social/account/fields` returns every field with `readable: true, editable: false` and a
note (`profile_picture_url` is a short-lived CDN link: show it, never store it).

## Metric registry

`GET /api/v1/social/insights/catalog` lists every insight this client knows, with an honest state:

* **account** — `reach`, `profile_views`, `website_clicks`, `follower_count`
  (`GET /api/v1/social/account/insights`, asked with `metric_type=total_value` so Instagram answers
  one number per metric instead of a series);
* **feed / reels** — `reach`, `views`, `likes`, `comments`, `saved`, `shares`, `total_interactions`;
* **story** — `reach`, `views`, `shares`, `replies`, `total_interactions`;
* **removed by Meta** — `impressions`, `plays`, `video_views`, `profile_activity`, `audience_city`,
  each with the evidence that views replaced them.

Two behaviours that are Meta's, not ours:

* a metric Instagram has no data for yet comes back `null`, **never 0** — a quiet week and a zero
  week are different facts, and a card that shows 0 for both is a lie;
* a value of **-1** means "fewer than five people". It is kept as sent so the screen can say «أقل من
  ٥» instead of drawing a negative number.

## Tests

`tests/test_instagram_metrics_catalog.py` — no field claims to be editable, the catalog covers the
three scopes, retired metrics carry evidence and never appear as live, the account call asks for
`total_value`, both response shapes are read, and no data means `None` everywhere.
