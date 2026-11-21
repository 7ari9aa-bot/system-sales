# Facebook Page publishing and posts: Graph API parity

Scope: Meta's official Graph API surface for **publishing to a Facebook Page and managing the
Page's own posts**. Comments, moderation, insights and messaging are out of scope (other sheets).

Evidence for the "Implemented in our app?" column comes from
`backend/app/modules/conversations/routers/facebook_pages.py` and
`backend/app/modules/conversations/` (the `services` directory does not exist in this tree, so the
equivalent service layer `facebook_service.py` plus `gateway/facebook_pages.py` was read instead).
Line numbers are from branch `feat/facebook-matrix-publish`, based on `origin/main` at `36fee084`.

Status legend:

- `DONE`: the capability is implemented in our code and the Graph API documents it.
- `MISSING-ALLOWED`: Meta documents the capability and our code does not have it.
- `API-FORBIDDEN`: Meta does not expose this through the Graph API for Pages, so our app cannot have it.
- `UNVERIFIED`: Meta's documentation could not be read for this row, so no claim is made.

Version note: Meta's docs render at `v27.0` at the time of writing. `developers.facebook.com`
returned HTTP 400 to direct fetches, so pages were read through a text-extraction proxy of the same
URLs; where a page 404s that is stated in the row.

## Matrix

| Capability | Endpoint | Permission/feature | Implemented in our app? | Status | Doc URL |
|---|---|---|---|---|---|
| Text post | `POST /{page-id}/feed` with `message` | `pages_manage_posts`, `pages_read_engagement`; Page task `CREATE_CONTENT` | Yes: router `publish_post` (`routers/facebook_pages.py:154`), gateway `publish_post` (`gateway/facebook_pages.py:211`) sends `message` to `/{page-id}/feed` | DONE | https://developers.facebook.com/docs/pages-api/posts |
| Link post | `POST /{page-id}/feed` with `link` (plus optional `name`, `description`, `picture`) | `pages_manage_posts` | Yes: `PublishRequest.link` (`routers/facebook_pages.py:60`), `data["link"]` (`gateway/facebook_pages.py:247`); a link is refused together with a picture (`gateway/facebook_pages.py:237`) | DONE | https://developers.facebook.com/docs/graph-api/reference/page/feed |
| Single photo | `POST /{page-id}/photos` with `url` (and `caption`) | `pages_manage_posts` | Yes: `photo_url` routes to the `photos` edge (`gateway/facebook_pages.py:253`); file upload path `publish_picture` (`facebook_service.py:243`) stores the file and hands Meta a short signed link | DONE | https://developers.facebook.com/docs/graph-api/reference/page/photos/ |
| Multi-photo post | `POST /{page-id}/photos` with `published=false` per photo, then `POST /{page-id}/feed` with `attached_media[i]` | `pages_manage_posts` | Yes: `publish_pictures` (`facebook_service.py:273`), `_publish_album` (`gateway/facebook_pages.py:261`), cap `MAX_PHOTOS_PER_POST = 10` (`gateway/facebook_pages.py:117`) | DONE | https://developers.facebook.com/docs/graph-api/reference/page/feed |
| Video post (Page feed video) | `POST /{page-id}/videos` on `graph-video.facebook.com`, after a resumable upload session | `publish_video` plus `pages_manage_posts` | No: only Reels (`video_reels`) and Stories (`video_stories`) are implemented; no `/{page-id}/videos` call exists in the module. `publish_video` is also absent from `FACEBOOK_PAGE_SCOPES` (`backend/app/modules/customers/meta_scopes.py:20`) | MISSING-ALLOWED | https://developers.facebook.com/docs/video-api/guides/publishing |
| Scheduled post | `POST /{page-id}/feed` with `published=false` and `scheduled_publish_time` (10 minutes to 30 days out) | `pages_manage_posts` | Yes: `schedule_at` on `PublishRequest` (`routers/facebook_pages.py:72`), `check_schedule` enforces the window (`gateway/facebook_pages.py:67`), `GET /facebook/scheduled` reads `scheduled_posts` (`routers/facebook_pages.py:136`) | DONE | https://developers.facebook.com/docs/pages-api/posts |
| Backdated post | `POST /{page-id}/feed` or `POST /{page-post-id}` with `backdated_time` and `backdated_time_granularity` (`year`, `month`, `day`, `hour`, `minute`) | `pages_manage_posts` | No: no `backdated_time` anywhere in the module | MISSING-ALLOWED | https://developers.facebook.com/docs/graph-api/reference/page/feed |
| Edit post message | `POST /{page-post-id}` with `message` (an app may only edit a post it published) | `pages_manage_posts` | Yes: `PATCH /facebook/posts/{post_id}` (`routers/facebook_pages.py:310`) to `update_post` (`gateway/facebook_pages.py:293`) | DONE | https://developers.facebook.com/docs/pages-api/posts |
| Delete post | `DELETE /{page-post-id}` | `pages_manage_posts` | Yes: `DELETE /facebook/posts/{post_id}` (`routers/facebook_pages.py:323`) to `delete_post` (`gateway/facebook_pages.py:301`) | DONE | https://developers.facebook.com/docs/pages-api/posts |
| Post visibility and audience targeting (`feed_targeting`, `targeting`) | `POST /{page-id}/feed` with `feed_targeting` (preferred audience) or `targeting` (hard limit: `geo_locations`, `age_min`, `age_max`, `genders`, `locales`, `interests`, ...) | `pages_manage_posts` | No: no `feed_targeting` or `targeting` in the module | MISSING-ALLOWED | https://developers.facebook.com/docs/graph-api/reference/page/feed |
