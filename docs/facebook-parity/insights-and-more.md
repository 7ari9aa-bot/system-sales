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
| Post insights, content views (`post_media_view`) | `GET /{post-id}/insights?metric=post_media_view` | `read_insights` + `pages_read_engagement`, ANALYZE task | Yes. In `POST_METRICS`; `FacebookPostsPage.jsx` opens `FbPostInsightsDialog` from `fetchFacebookPostInsights` | DONE | https://developers.facebook.com/docs/graph-api/reference/page/insights/ |
| Post insights, reactions by type (`post_reactions_like_total`, `love`, `wow`, `haha`, `sorry`, `anger`) | `GET /{post-id}/insights?metric=post_reactions_like_total,...` | same | Yes. All six are in `POST_METRICS` | DONE | https://developers.facebook.com/docs/graph-api/reference/page/insights/ |
| Post insights, reactions in one call (`post_reactions_by_type_total`) | `GET /{post-id}/insights?metric=post_reactions_by_type_total` | same | No. Our app asks for the six separate metrics instead, which is equivalent but costs one wider request | MISSING-ALLOWED (low value, the data is already there) | https://developers.facebook.com/docs/graph-api/reference/page/insights/ |
| Post insights, unique media viewers (`post_total_media_view_unique`) | `GET /{post-id}/insights?metric=post_total_media_view_unique` | same | No | MISSING-ALLOWED | https://developers.facebook.com/docs/graph-api/reference/page/insights/ |
| Post insights, video metrics (`post_video_views`, `post_video_views_organic|paid|unique`, `post_video_complete_views_organic|paid`, `post_video_avg_time_watched`, `post_video_retention_graph`) | `GET /{post-id}/insights?metric=post_video_views` | same. Reshared videos return 0 | No. `POST_METRICS` has no video metrics, so a video post shows views and reactions only | MISSING-ALLOWED | https://developers.facebook.com/docs/graph-api/reference/page/insights/ |
| Post insights, impressions (`post_impressions`, `post_impressions_organic`, `post_impressions_fan`, `post_impressions_paid`, `post_impressions_viral`, `post_impressions_nonviral`) | `GET /{post-id}/insights?metric=post_impressions` | Retired 15 Nov 2025. Use `post_media_view`, with `is_from_ads` / `is_from_followers` for the paid and follower splits | Correctly refused, all in `REMOVED_METRICS` | API-FORBIDDEN | https://developers.facebook.com/blog/post/2025/08/15/page-insights-api-updates/ |
| Post insights, clicks and negative feedback (`post_clicks_unique`, `post_engaged_users`, `post_negative_feedback*`, `post_cta_clicks_total`) | `GET /{post-id}/insights?metric=post_clicks_unique` | Retired 16 Sep 2024 | Correctly refused | API-FORBIDDEN | https://developers.facebook.com/docs/pages-api/changelog/ |
| Reel insights as a Page metric | `GET /{page-id}/insights?metric=...` | The insights doc states plainly: "Interactions on Reels are not included" | No, and cannot be | API-FORBIDDEN | https://developers.facebook.com/docs/graph-api/reference/page/insights/ |
| Reel insights per reel (plays, reactions, comments, shares) | `GET /{video-id}/video_insights?metric=total_video_views,...` | Page access token with `read_insights` and `pages_read_engagement`. The reel id from `/{page-id}/video_reels` is a video id | No. `facebook_pages.list_reels` asks only for `id,description,title,updated_time,permalink_url,picture,length`, and `FacebookReelsPage.jsx` shows no numbers | MISSING-ALLOWED (a Page owner sees reel plays in the app; we show none) | https://developers.facebook.com/docs/graph-api/reference/video/video_insights/ |
| Video insights, view and completion metrics (`total_video_views`, `total_video_complete_views`, `total_video_10s_views`, `total_video_avg_time_watched`, `total_video_view_total_time`) | `GET /{video-id}/video_insights?metric=total_video_views` | same | No | MISSING-ALLOWED | https://developers.facebook.com/docs/graph-api/reference/video/video_insights/ |
| Video insights, legacy impressions fields (`total_video_impressions`, `total_video_impressions_unique`) | `GET /{video-id}/video_insights?metric=total_video_impressions` | Still listed in the v27.0 video_insights reference, but the 2025 changelog retires the impressions family. Whether these specific video fields still answer is not stated | No | UNVERIFIED | https://developers.facebook.com/docs/graph-api/reference/video/video_insights/ |
| Story insights | `GET /{story-id}/insights` | The Page Insights reference has a Stories section, but the metric names and the story id shape are not documented in a form I could confirm | No. `list_stories` only lists stories | UNVERIFIED | https://developers.facebook.com/docs/graph-api/reference/page/insights/ |
| Page info, basic read (name, about, category, fans, followers, link, picture, cover, website, phone, emails, address, verification) | `GET /{page-id}?fields=id,name,about,category,fan_count,followers_count,link,picture{url},cover{source},website,phone,emails,single_line_address,verification_status` | Page access token. `about`, `category`, `website`, `phone`, `emails` and `single_line_address` are readable with `pages_read_engagement` + `pages_read_user_content` for Page-owned data, or the Page Public Content Access / Page Public Metadata Access feature for public data | Yes, exactly that field list in `facebook_pages.get_page`, served at `GET /facebook/page` and read by `useFacebookData.js` for the header avatar and name | DONE | https://developers.facebook.com/docs/graph-api/reference/page/ |
| Page info, follower count on the profile | `GET /{page-id}?fields=followers_count` | same. `fan_count` returns `followers_count` on New Page Experience Pages | Yes. `FacebookPostsPage.jsx` prints `page.followers_count` as "متابع / followers" under the Page name | DONE | https://developers.facebook.com/docs/graph-api/reference/page/ |
| Page info, rating on the profile | `GET /{page-id}?fields=overall_star_rating,rating_count` | `overall_star_rating` is public; `rating_count` needs PPCA or PPMA. Both are omitted when there are zero or very few ratings | No. Neither field is in the `get_page` field list | MISSING-ALLOWED | https://developers.facebook.com/docs/graph-api/reference/page/ |
| Page info, opening hours read | `GET /{page-id}?fields=hours` | Page access token, Page-owned data | No. `hours` is not requested | MISSING-ALLOWED | https://developers.facebook.com/docs/graph-api/reference/page/ |
| Page info, profile picture read | `GET /{page-id}/picture?redirect=0` | Page token from someone with the MANAGE task, or an app or user token | Yes, indirectly. `get_page` reads `picture{url}` rather than the `/picture` edge, which gives the same url | DONE | https://developers.facebook.com/docs/graph-api/reference/page/picture/ |
| Page info, cover photo read | `GET /{page-id}?fields=cover{source}` | Page access token | Yes, `cover{source}` is in the field list, but the UI never renders it. `FacebookLayout.jsx` uses the profile picture only | MISSING-ALLOWED (data fetched, thrown away) | https://developers.facebook.com/docs/graph-api/reference/page/ |
| Page info, edit about | `POST /{page-id}` with `about` | `pages_manage_metadata` plus the MANAGE task, and `business_management` where the Page belongs to a business | No. There is no `POST /facebook/page` route and no edit form in `frontend/src/pages/facebook` | MISSING-ALLOWED | https://developers.facebook.com/docs/graph-api/reference/page/ |
| Page info, edit hours | `POST /{page-id}` with `hours` (map keyed `mon_1_open` style) | same | No | MISSING-ALLOWED | https://developers.facebook.com/docs/graph-api/reference/page/ |
| Page info, edit phone | `POST /{page-id}` with `phone` | same | No | MISSING-ALLOWED | https://developers.facebook.com/docs/graph-api/reference/page/ |
| Page info, edit website | `POST /{page-id}` with `website` | same | No | MISSING-ALLOWED | https://developers.facebook.com/docs/graph-api/reference/page/ |
| Page info, edit category | `POST /{page-id}` with `category_list` (list of category ids) | same | No | MISSING-ALLOWED | https://developers.facebook.com/docs/graph-api/reference/page/ |
| Page info, edit cover photo | `POST /{page-id}` with `cover`, plus `focus_x`, `focus_y`, `offset_x`, `offset_y`, `no_feed_story` | Page Admin or Editor with `EDIT_PROFILE` and `business_management` | No | MISSING-ALLOWED | https://developers.facebook.com/docs/graph-api/reference/page/ |
| Page info, edit profile photo | `POST /{page-id}/picture` | Page token from someone with the MANAGE task | No | UNVERIFIED (the `/picture` reference documents reading only; the write form is not on that page) | https://developers.facebook.com/docs/graph-api/reference/page/picture/ |
| Page info, edit description, mission, emails, address, price range, parking, payment options, attire, impressum, general info | `POST /{page-id}` with `description`, `mission`, `emails`, `contact_address`, `price_range`, `parking`, `payment_options`, `attire`, `impressum`, `general_info` | same as the other Page edits | No | MISSING-ALLOWED | https://developers.facebook.com/docs/graph-api/reference/page/ |
| Messenger inbox, conversation list from Meta | `GET /{page-id}/conversations?fields=id,snippet,updated_time,unread_count,participants` | Page access token from someone with the MESSAGING task, `pages_messaging`, `pages_manage_metadata` | No. `/conversations` and `/inbox` are served entirely from our own database (`InboxQuery.page`), which is fed by the `messages` webhook. Nothing calls the `/conversations` edge, so a thread that existed before the webhook was connected never appears | MISSING-ALLOWED | https://developers.facebook.com/docs/graph-api/reference/page/conversations/ |
| Messenger inbox, read one conversation's messages from Meta | `GET /{conversation-id}/messages` | same | No. `GET /conversations/{id}/messages` reads our `messages` table only | MISSING-ALLOWED (a backfill would fill gaps after downtime) | https://developers.facebook.com/docs/graph-api/reference/page/messages/ |
| Messenger inbox, inbound messages by webhook | `POST` webhook, field `messages` | `pages_messaging`, `pages_manage_metadata`, subscribed_apps with `messages` | Yes. `messenger.py` `parse_inbound` / `_parse_message_event` handles text, attachments, `mid`, `reply_to` | DONE | https://developers.facebook.com/docs/graph-api/reference/page/ |
| Messenger inbox, inbound message attachments | webhook `message.attachments` | same | Yes. `_parse_message_event` reads `attachments[0]` into `media_url` / `media_type` | DONE | https://developers.facebook.com/docs/graph-api/reference/page/ |
| Messenger send, plain text | `POST /me/messages` with `recipient.id` and `message.text` | `pages_messaging` and the MESSAGING task. Only inside the standard messaging window | Yes. `messenger_adapter.send`, called from `POST /conversations/{id}/messages` | DONE | https://developers.facebook.com/docs/messenger-platform/send-messages/ |
| Messenger send, media attachment (image, audio, video, file) | `POST /me/messages` with `message.attachment` | same. 8 MB for an image, 25 MB otherwise | Yes. `messenger.py` sends `attachment` for `message.media_url`, with `messenger_media.check_attachment` enforcing the sizes | DONE | https://developers.facebook.com/docs/messenger-platform/send-messages/ |
| Messenger send, file plus caption | two `POST /me/messages` calls | same. One request cannot carry both, which Meta's Send API implies by making attachment and text alternatives | Yes. `send` posts the file, then the text, and keeps the file's id | DONE | https://developers.facebook.com/docs/messenger-platform/send-messages/ |
| Messenger send, template (generic, button, media, receipt) | `POST /me/messages` with `message.attachment.type=template` and `payload.template_type` | same | Partly. `messenger.py` will send `template_name` and `template_vars` as a template, but the only templates the app creates are WhatsApp ones (`TemplateService`, `provider` defaults to `whatsapp`), and nothing in the Messenger UI builds a template payload. So the path exists and is unreachable | MISSING-ALLOWED | https://developers.facebook.com/docs/messenger-platform/send-messages/ |
| Messenger quick replies | `POST /me/messages` with `message.quick_replies` (up to 13) | same | No. `grep` finds `quick_replies` only in `instagram.py`. Messenger has none | MISSING-ALLOWED (a Page owner uses these constantly in Messenger) | https://developers.facebook.com/docs/messenger-platform/send-messages/quick-replies/ |
| Messenger sender action, typing on and off | `POST /me/messages` with `sender_action=typing_on` or `typing_off` | same. The request must carry only `recipient` and `sender_action` | No. `read_signal_service.py` line 95 refuses any channel that is not `whatsapp` or `instagram`, so a Messenger thread never shows typing | MISSING-ALLOWED | https://developers.facebook.com/docs/messenger-platform/send-messages/sender-actions/ |
| Messenger sender action, seen (`mark_seen`) | `POST /me/messages` with `sender_action=mark_seen` | same | No. Same guard in `read_signal_service.py` | MISSING-ALLOWED | https://developers.facebook.com/docs/messenger-platform/send-messages/sender-actions/ |
| Messenger sender action, react to a message with an emoji | `POST /me/messages` with `sender_action=react`, `payload.message_id`, `payload.reaction` | same | No. `POST /conversations/{id}/messages/{mid}/reaction` rejects any channel other than WhatsApp and Instagram | MISSING-ALLOWED | https://developers.facebook.com/docs/messenger-platform/send-messages/sender-actions/ |
| Messenger read and delivery receipts inbound | webhook `message_reads` and `message_deliveries` | `pages_messaging` | No. `MessengerAdapter.parse_status_updates` returns `[]` with the comment "inbound-only for now", so the blue ticks a customer generates are dropped | MISSING-ALLOWED (a Page owner sees "Seen" in Messenger) | https://developers.facebook.com/docs/graph-api/reference/page/ |
| Messenger 24 hour standard messaging window | rule on `POST /me/messages`, not an endpoint | Meta refuses a free-form message more than 24h after the person's last message | Yes. `CHANNEL_POLICIES` gives `messenger` and `facebook` `window_hours=24`, and `policy.py` computes `window_expires_at` and refuses outside it | DONE | https://developers.facebook.com/documentation/business-messaging/messenger-platform/send-messages |
| Messenger HUMAN_AGENT tag, 7 day window | `POST /me/messages` with `messaging_type=MESSAGE_TAG` and `tag=HUMAN_AGENT` | `pages_messaging`, and the human agent feature must be granted to the app | Half. `policy.py` models the 168 hour human agent window for `messenger` and `facebook`, but only `instagram.py` puts `messaging_type` and `tag` on the wire. `messenger.py` never sends the tag, so a human reply past 24h is refused by Meta even though our policy says it is allowed | MISSING-ALLOWED (this is a real bug, not just a gap) | https://developers.facebook.com/documentation/development/features-reference/human-agent |
| Messenger persistent menu | `POST /me/messenger_profile` with `persistent_menu` | `pages_messaging` | No. `me/messenger_profile` is only used by `instagram.py`, for ice breakers with `platform=instagram` | MISSING-ALLOWED | https://developers.facebook.com/docs/messenger-platform/send-messages/persistent-menu/ |
| Messenger get started button, greeting, ice breakers | `POST /me/messenger_profile` with `get_started`, `greeting`, `ice_breakers` | `pages_messaging` | No for Messenger. Instagram ice breakers exist in `instagram.py` | MISSING-ALLOWED | https://developers.facebook.com/docs/graph-api/reference/page/messenger_profile/ |
| Messenger domain allowlist, account linking, commands | `POST /me/messenger_profile` | `pages_messaging` | No | MISSING-ALLOWED | https://developers.facebook.com/docs/graph-api/reference/page/messenger_profile/ |
| Messenger customer profile from the PSID (name, picture) | `GET /{psid}?fields=first_name,last_name,profile_pic` | `pages_messaging` and the MESSAGING task | No. `grep` for `psid`, `first_name` and `profile_pic` in `messenger.py` returns nothing | UNVERIFIED (the field list is well known but I did not load its reference page) | https://developers.facebook.com/docs/messenger-platform/identity/user-profile/ |
| Messenger handover protocol, thread control | `POST /me/take_thread_control`, `pass_thread_control`, `request_thread_control` | `pages_messaging` and the handover feature | No | MISSING-ALLOWED | https://developers.facebook.com/docs/messenger-platform/handover-protocol/ |
| Messenger message templates, status callbacks | webhook `message_template_status_update` | `pages_messaging` | No | MISSING-ALLOWED | https://developers.facebook.com/docs/graph-api/reference/page/ |
