# Facebook Graph API: Insights, Page Info, Messenger, Ratings

Scope: page insights, post insights, reel insights, audience demographics, follower count, Page
info read and edit, Messenger inbox, Page ratings and recommendations, Page roles, call to action,
Page visits, and the Business Suite features that have no API.

Research date: 2026-11-21. Docs read at Graph API v27.0 unless a row says otherwise.
Everything below comes from developers.facebook.com (read through a text proxy because the site
returns HTTP 400 to plain fetchers) plus the Pages API changelog. Nothing is guessed: a row whose
behaviour I could not confirm against a doc page is marked UNVERIFIED.

Status legend:

- DONE: our app calls this endpoint and shows or uses the result.
- MISSING-ALLOWED: the API permits it, our app does not do it yet. This is buildable work.
- API-FORBIDDEN: Meta does not offer this through the Graph API, or has removed it. Not buildable.
- UNVERIFIED: no doc page confirmed the behaviour. Treat as unknown.

How the "Implemented in our app?" column was produced: `timeout 30 grep -n` over
`backend/app/modules/conversations`, `frontend/src/pages/facebook` and
`frontend/src/lib/facebookApi.js`, plus reading the matched files.

## Part 1: deprecations first, because they decide what is buildable

Two rounds of removals shape everything else.

**16 Sep 2024 (all versions).** A large block of legacy metrics started returning an invalid
metric error. The ones a Page owner would notice: `page_views`, `page_views_login`,
`page_views_logout`, `page_views_unique`, `page_views_external_referrals`,
`page_impressions_by_age_gender_unique`, `page_impressions_by_city_unique`,
`page_impressions_by_country_unique`, `page_impressions_by_locale_unique`,
`page_impressions_by_story_type`, `page_fans_by_like_source`, `page_fans_online`,
`page_fans_online_per_day`, `page_cta_clicks_logged_in_total`,
`page_cta_clicks_logged_in_unique`, `page_call_phone_clicks_logged_in_count`,
`page_website_clicks_logged_in_count`, `page_tab_views_login_top`, `page_tab_views_logout_top`,
`page_negative_feedback` and its `_by_type` variants, `page_consumptions_unique`,
`page_places_checkin_total`, `post_clicks_unique`, `post_engaged_users`,
`post_cta_clicks_total`, `post_negative_feedback` and its variants,
`post_impressions_by_story_type`.

**15 Nov 2025 (all versions).** Impressions and Page fans were retired in favour of views and
follows. Removed: `page_fans` (replacement `page_follows`), `page_fans_locale`, `page_fans_city`
(replacement `page_follows_city`), `page_fans_country` (replacement `page_follows_country`),
`page_fan_adds`, `page_fan_adds_unique`, `page_fan_removes`, `page_fan_removes_unique`,
`page_impressions` and every `page_impressions_paid|viral|nonviral` variant (replacement
`page_media_view`, with `is_from_ads` and `is_from_followers` breakdowns), and every
`post_impressions`, `post_impressions_paid`, `post_impressions_fan`, `post_impressions_organic`,
`post_impressions_viral`, `post_impressions_nonviral` variant (replacement `post_media_view`).

So: **`page_impressions`, `page_fans`, `page_impressions_unique`, `page_fans_online`,
`page_views_login`, `post_impressions`, `post_impressions_organic` are all gone.**
**`page_media_view`, `post_media_view`, `page_follows`, `page_post_engagements`,
`page_views_total`, `page_total_actions`, `page_video_views`, `post_reactions_*_total`,
`post_media_view`, `overall_star_rating`, `rating_count` still work.**

Note the trap: `page_views` died in 2024 but `page_views_total` survived. They are different
metrics with confusingly similar names, and `page_views_total` is the only profile-view number
left.

Our backend already encodes this. `backend/app/modules/conversations/gateway/facebook_pages.py`
defines `PAGE_METRICS = ("page_follows", "page_media_view", "page_post_engagements")`,
`POST_METRICS` as the seven `post_reactions_*_total` plus `post_media_view`, and a
`REMOVED_METRICS` frozenset that raises `ValueError` on any retired name. That guard covers the
2024 and 2025 lists above. `frontend/src/pages/facebook/FacebookInsightsPage.jsx` labels exactly
those three page metrics.

## Part 2: the matrix

| Capability | Endpoint | Permission/feature | Implemented in our app? | Status | Doc URL |
| --- | --- | --- | --- | --- | --- |
| Page insights, follower count (`page_follows`) | `GET /{page-id}/insights?metric=page_follows&period=day` | `read_insights` + `pages_read_engagement`, ANALYZE task on the Page | Yes. `facebook_pages.get_page_insights` sends it; `FacebookInsightsPage.jsx` shows it as "المتابعون / Followers" reading the last value, not a sum | DONE | https://developers.facebook.com/docs/graph-api/reference/page/insights/ |
| Page insights, content views (`page_media_view`) | `GET /{page-id}/insights?metric=page_media_view&period=day` | same | Yes. In `PAGE_METRICS`, summed over the window in the UI | DONE | https://developers.facebook.com/docs/graph-api/reference/page/insights/ |
| Page insights, post engagements (`page_post_engagements`) | `GET /{page-id}/insights?metric=page_post_engagements&period=day` | same | Yes. In `PAGE_METRICS`, summed | DONE | https://developers.facebook.com/docs/graph-api/reference/page/insights/ |
| Page insights, unique media viewers (`page_total_media_view_unique`) | `GET /{page-id}/insights?metric=page_total_media_view_unique` | same | No. Not in `PAGE_METRICS` | MISSING-ALLOWED | https://developers.facebook.com/docs/graph-api/reference/page/insights/ |
| Page insights, profile views (`page_views_total`) | `GET /{page-id}/insights?metric=page_views_total&period=day` | same | No. Not in `PAGE_METRICS` (note: `page_views` was removed in 2024, `page_views_total` still exists) | MISSING-ALLOWED | https://developers.facebook.com/docs/graph-api/reference/page/insights/ |
| Page insights, CTA and contact clicks (`page_total_actions`) | `GET /{page-id}/insights?metric=page_total_actions` | same | No | MISSING-ALLOWED | https://developers.facebook.com/docs/graph-api/reference/page/insights/ |
| Page insights, video views (`page_video_views`, `page_video_views_organic|paid|unique`, `page_video_complete_views_30s`, `page_video_repeat_views`) | `GET /{page-id}/insights?metric=page_video_views,...` | same. Some video metrics only return accurate values to the Page video post creator | No. `PAGE_METRICS` has no video metrics | MISSING-ALLOWED | https://developers.facebook.com/docs/graph-api/reference/page/insights/ |
| Page insights, reaction breakdown (`page_actions_post_reactions_like_total` and the love, wow, haha, sorry, anger variants, `page_actions_post_reactions_total`) | `GET /{page-id}/insights?metric=page_actions_post_reactions_like_total,...` | same | No. Only the per-post reaction metrics are used | MISSING-ALLOWED | https://developers.facebook.com/docs/graph-api/reference/page/insights/ |
| Page insights, monetization earnings (`content_monetization_earnings`) | `GET /{page-id}/insights?metric=content_monetization_earnings` | same, and only for monetized Pages | No | MISSING-ALLOWED | https://developers.facebook.com/docs/graph-api/reference/page/insights/ |
| Page insights, impressions (`page_impressions` and paid, viral, nonviral, unique variants) | `GET /{page-id}/insights?metric=page_impressions` | Retired 15 Nov 2025, returns an invalid metric error. Use `page_media_view` with the `is_from_ads` / `is_from_followers` breakdowns | Correctly refused. `REMOVED_METRICS` raises before any call | API-FORBIDDEN | https://developers.facebook.com/blog/post/2025/08/15/page-insights-api-updates/ |
| Page insights, fans (`page_fans`, `page_fans_city`, `page_fans_country`, `page_fans_locale`, `page_fan_adds`, `page_fan_removes` and unique variants) | `GET /{page-id}/insights?metric=page_fans` | Retired 15 Nov 2025. Use `page_follows`, and the changelog names `page_follows_city` / `page_follows_country` as replacements | Correctly refused, all listed in `REMOVED_METRICS` | API-FORBIDDEN | https://developers.facebook.com/docs/pages-api/changelog/ |
| Page insights, demographics (`page_fans_city`, `page_fans_country`, `page_fans_locale`) | `GET /{page-id}/insights?metric=page_fans_country` | Retired 15 Nov 2025 | Correctly refused | API-FORBIDDEN | https://developers.facebook.com/docs/pages-api/changelog/ |
| Audience demographics by city or country after the removals (`page_follows_city`, `page_follows_country`) | `GET /{page-id}/insights?metric=page_follows_city` | Named as the replacement in the Pages changelog | No | UNVERIFIED (the changelog names these metrics but the v27.0 Page Insights metric tables do not list them, so their availability could not be confirmed) | https://developers.facebook.com/docs/pages-api/changelog/ |
| Audience demographics by age and gender (`page_impressions_by_age_gender_unique` and the 2024 demographic block) | `GET /{page-id}/insights?metric=page_impressions_by_age_gender_unique` | Retired 16 Sep 2024 | Correctly refused | API-FORBIDDEN | https://developers.facebook.com/docs/pages-api/changelog/ |
| Audience demographics, gender and age, any remaining metric | n/a | The insights doc still states that demographic metrics are only returned when 100 or more people are in the bucket | No | UNVERIFIED | https://developers.facebook.com/docs/graph-api/reference/page/insights/ |
| Insights date range (`since`, `until`, `period`) | `GET /{page-id}/insights?since=&until=&period=day` | same as insights. Only 90 days per request, 2 years retained, most metrics refresh once per 24h | Partly. `since` and `until` are accepted and passed through; the UI never sets them and always asks for `period=day` with no range, so Meta returns its default window | MISSING-ALLOWED | https://developers.facebook.com/docs/graph-api/reference/page/insights/ |
| Insights for Pages under 100 likes | `GET /{page-id}/insights` | Meta refuses: Page Insights needs 100 or more likes | No handling. An error surfaces as a red alert on the Insights screen | MISSING-ALLOWED (a clear "this Page is too small for insights" message would be honest) | https://developers.facebook.com/docs/graph-api/reference/page/insights/ |
