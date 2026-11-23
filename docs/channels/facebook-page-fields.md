# Facebook Page fields: what can be edited, what cannot, and why

`PAGE_FIELD_MATRIX` in `gateway/facebook_pages.py` is the single source of truth; the API publishes
it at `GET /api/v1/facebook/page/fields` so a screen can say "read-only" instead of drawing a box
that cannot save. Writes go through `PATCH /api/v1/facebook/page` and are refused **before** the
call when they name anything outside the editable set — Meta answers a bad field with a generic
permission error that tells the owner nothing.

| Field | Editable | Permission | Note |
|---|---|---|---|
| `about` | yes | `pages_manage_metadata` | short description |
| `description` | yes | `pages_manage_metadata` | long description |
| `website` | yes | `pages_manage_metadata` | |
| `phone` | yes | `pages_manage_metadata` | |
| `emails` | yes | `pages_manage_metadata` | a list, not one string |
| `category` | yes | `pages_manage_metadata` | Meta restricts some category changes |
| `hours` | yes | `pages_manage_metadata` | structured JSON per day, not free text |
| `name` | **no** | — | renamed through Meta's own review flow |
| `id` | no | — | assigned by Meta |
| `followers_count`, `fan_count` | no | — | counted by Meta |
| `verification_status` | no | — | Business Suite only; the API does not expose it |
| `rating` | no | — | Page ratings have no API surface |

Two rows are the honest kind of "not supported": verification and rating are not features we failed
to build, they are things Meta never exposed. They appear in the matrix with `exposed: false` so the
UI does not offer them, and they are recorded in `METRIC_STATES` the same way for insights.

## Post controls

| Route | Meta field | Effect |
|---|---|---|
| `POST /api/v1/facebook/posts/{id}/pin` | `is_pinned` | pinned to the top of the Page timeline |
| `POST /api/v1/facebook/posts/{id}/hide` | `is_hidden` | hidden from the timeline, still visible to its author |
| `DELETE /api/v1/facebook/posts/{id}` | — | deletes the post |

## Insights

`GET /api/v1/facebook/insights/catalog` lists every insight this client knows with an honest state:

* **live** — `page_follows`, `page_media_view`, `page_post_engagements`,
  `page_daily_follows_unique`, `page_video_views`, `post_media_view`, `post_clicks` and the
  `post_reactions_*_total` counters;
* **removed** — the impressions family (`page_impressions*`, `page_engaged_users`, `page_fans`,
  `post_impressions*`, `page_posts_impressions`), retired by Meta and replaced by media views and
  follows;
* **not_supported** — Page rating and verification status, which have no API surface.

A metric Meta refuses at request time no longer takes the whole panel down: `insights_report()`
drops the metric Meta named, asks for the rest once more, and returns what it dropped in
`unavailable`, so the screen shows the numbers it does have and labels the rest.
