# Facebook Page parity report

Goal: the Facebook section of Fihrist matches the real Facebook Page experience, strictly within what Meta's official Graph API allows. Where the API forbids something, it is listed here and not faked.

Statuses: DONE (implemented), MISSING-ALLOWED (the API allows it, we do not do it yet), API-FORBIDDEN (Meta does not allow it), UNVERIFIED (Meta's docs do not settle it, so we do not claim either way).

## Capability matrices

| Area | File | DONE | MISSING-ALLOWED | API-FORBIDDEN | UNVERIFIED |
|---|---|---|---|---|---|
| Comments, reactions, moderation | [engagement.md](facebook-parity/engagement.md) | 16 | 11 | 3 | 1 |
| Insights, page info, Messenger, ratings | [insights-and-more.md](facebook-parity/insights-and-more.md) | 14 | 39 | 7 | 6 |
| Publishing and posts | [publish.md](facebook-parity/publish.md) | 9 | 3 | 0 | 10 |

Counts come from `grep -c '| STATUS |'` on each file.

## Visual and behaviour fixes shipped (each its own commit, test written first)

| Difference from real Facebook | Commit | Evidence |
|---|---|---|
| Post button shows only once you type | 1a992934 | 3 tests fail on the old code, pass after |
| Page's own comment wears the "Author" badge | 1b5b839b | tests in FbComment.test.jsx |
| Comment age sits on the author's line | 7456f316 | tests in FbComment.test.jsx |
| Comment count is a number on the Comment action | 19da5e0e | tests in FbPostCard.test.jsx |
| Page's own comment offers Reply | f2b1f988 | 5 new tests, failed before the change |
| FbReactionSummary import missing (production crash) | 71cede37 | merged earlier with owner approval |

Frontend full suite on this branch: 168 files, 2244 tests passing. ESLint clean on the touched files.

## Visual comparison against real Facebook (owner's local browser, 2026-11-21)

Real side: Meta Business Suite and the Page itself, for Page 61595629975011. Our side: fihrist.world production (it does not yet carry these branches, so the differences below are before any of this work).

| Screen | Real Facebook | Fihrist | Verdict |
|---|---|---|---|
| Insights, metrics | Six cards: Views, Viewers, Content interactions, Link clicks, Visits, Follows | Three cards: Followers, Content views, Post interactions | Fihrist lacks Viewers, Link clicks and Visits. The Graph API still exposes some of them, see insights-and-more.md |
| Insights, numbers | Follows 1 (100%), everything else 0 | Followers 1, views 0, interactions 0 | Same values |
| Insights, period | Last 30 days with a date picker | Last 2 days, no picker | Different. The note "may lag up to 48 hours" is accurate on our side |
| Insights, extras | Export button on each card, percentage change | None | Missing |
| Messages, layout | Tabs (All, Messenger, Instagram, WhatsApp, comments), search, filters (Unread, Priority, Ad replies, Follow up), Manage button | One list with "No conversations yet" and an empty "Pick a conversation" pane | Fihrist lacks search, the filters and the tabs |
| Messages, content | Empty inbox, offers to link Instagram | Empty | Same data |
| Reels, tab | The Page profile shows All, About, Followers, Photos, Mentions, More | Reels and Stories page with a New Reel button and Reels and Stories tabs | Different structure by design: ours is a publishing tool |
| Reels, content | No reels | "No reels published yet." | Same data |
| Page home, post | Same post, same comment | Same, comment shows "Page" badge and Delete only on production | Fixed on feat/facebook-comment-look, not yet deployed |

Not verified here: the Reels publishing flow on real Facebook (no reel was published), and the Stories tab.

## Branch state

`feat/facebook-full-parity` now contains every feature branch, each merged with `--no-ff` so the history keeps them apart: feat/facebook-comment-look (19da5e0e), feat/facebook-comment-order (dbbed9ff), feat/facebook-post-card-look, and the three matrix branches feat/facebook-matrix-engage, feat/facebook-matrix-insights, feat/facebook-matrix-publish. Nothing is merged to main. Backend check on the merged tree: `pytest tests/test_facebook_pages.py` 11 passed (the full backend suite is never run, per the standing rule).

## Page liking its own comment: tested on real Facebook

Done on 2026-11-21 in the owner's browser, on the test Page "Fihrist", comment id 122112956013520999_2041588523218805 ("Author" comment written by the Page).

- Facebook's own web UI offers Like, a thumbs-down and Reply on the Page's own comment (screenshot before the click).
- One click on Like turned the thumb blue and showed a like icon with the counter 1. After a full reload the like was still there (blue thumb, counter 1), so it was saved by Facebook, not a client-side guess.
- Not proven: that the Graph API edge `POST /{comment-id}/likes` accepts the same action with a Page token. The web UI and the API are different routes, and Meta's docs stay silent. Our own screen therefore keeps the Like button hidden on the Page's own comments (`FbComment.jsx`) until a real API call shows it works. Our API does not return a per comment like count either, so this could not be read back through our gateway.

## API limits read from Meta's reference (v27.0), 2026-11-21

Sources: https://developers.facebook.com/docs/graph-api/reference/object/likes/ , https://developers.facebook.com/docs/graph-api/reference/comment/ , https://developers.facebook.com/docs/graph-api/overview/rate-limiting/

Likes edge on a Comment (`POST /{comment-id}/likes`):
- Needs a Page access token requested by a person who can do the CREATE_CONTENT task, plus `pages_manage_engagement`.
- "The Page must also be able to like the object (whether via API or on Facebook.com)". Facebook.com let the Page like its own comment (tested), so this condition holds for our comment. Meta still never names self-authored comments as allowed or forbidden.
- The object must not already be liked by the Page. If the Page already reacted (wow, sad) a like succeeds but the reaction stays.
- Delete (`DELETE /{id}/likes`) needs the MODERATE task, and a Page can only delete its own likes.
- The Comment node has `like_count` and `user_likes` fields (viewer has liked). Our gateway does not return them, which is why the like could not be read back through it. Reading `user_likes` with the Page token is the proper way to verify.
- Post likes: only aggregated `total_count` via `summary=true` is available.
- The `like` count includes "like" and "care" reactions.

Rate limits for Pages calls made with a Page or system user token:
- Calls within 24 hours = 4800 x Number of Engaged Users (users who engaged with the Page in 24 hours). A near-empty test Page therefore has a very small quota.
- Error 80001 means "too many calls to this Page account"; 613 is the generic rate limit; 368 means the action was judged abusive or disallowed; 200 is a permissions error.
- Calls made with a user or app token follow platform limits instead: 200 x users per rolling hour.
- Meta advises backing off on throttling; the response headers expose usage.

Consequence for the Page-likes-own-comment item: the docs make it plausible and the UI proves Facebook allows it, but only a real `POST` with a Page token can settle the API side. Unknown stays UNVERIFIED until then.

## Like on the Page's own comment: now drawn, API result pending

Branch `feat/facebook-page-like-comment` (not merged). The Like button now shows on the Page's own comment, as on Facebook (tested in the owner's browser). Two tests failed first, then passed. Pressing it calls the existing `POST /facebook/objects/{id}/like`; if Meta rejects it the screen shows the error and does not keep the like (the existing `run` wrapper). The first real press on the test Page is what settles the API side. Known gap: the initial pressed state is not read from Meta's `user_likes`, because storing it needs a new column and migration; the like count shown is the stored `like_count`.

## Verified live on 2026-11-21 (main ba515de4, Vercel READY)

- Notifications header menu: opened on fihrist.world, shows "Mark all as read" and "Notification settings"; settings landed on /settings/channels. Same two items as real Facebook.
- Like on the Page's own comment: the button shows beside Reply and Delete. Pressing it reached Meta: after a sync our counter went 1 to 2, matching Facebook's own 2 on that comment. So the API accepted a Page like on a comment the Page wrote (the Page token and pages_manage_engagement are enough). Caveat: that comment was already liked once from Facebook's UI, and the press added the second like instead of being refused, so the like was counted as a new one in the count; a repeat press on the same Page identity is not proven to toggle off.
- Known gap left: the pressed state after a reload is not read from Meta's user_likes (needs a column and a migration), and the screen shows the count only after a sync.

## Release state

main = c14fa23c. It carries the whole parity line (comment look, post card look, comment order gateway, comment sort menu, shares count, the matrices and this report) plus the migration fe2026112013. Verified after the push: frontend suite 174 files, 2400 tests green; the affected backend tests (facebook pages, shares count, migrations, openapi lock) 28 passed; Vercel production deployment of c14fa23c READY and its bundle contains the sort menu, the share counter and the comment counter; the Northflank build of c14fa23c succeeded, its log shows `Running upgrade fe2026112012 -> fe2026112013` and the new container is running. A visual check on the live site was not done: the owner's browser tools were unavailable.

## Open items, not done

- Page liking a comment the Page itself wrote: Meta's docs are silent. Left hidden until tested against the real API.
- Shares count: done on its own branch, feat/facebook-shares-count (93655bbd backend with migration fe2026112013, 8e2d262d screen). It is cut from main, not from this branch, so it merges separately. Not deployed.
- Comment order: done on branch feat/facebook-comment-sort (59f8f167 sortComments, 06245ccb the menu), 6 + 4 tests that failed first. Facebook's three choices appear above a thread of two or more comments. "Newest" and "All comments" (oldest first) are real orders on our own copy of the thread; "Most relevant" is Facebook's private ranking, which the Graph API does not hand a Page, so it shows the API's order (oldest first) under that name. The gateway `order` parameter (feat/facebook-comment-order) stays for reads that go to Meta. Frontend suite on that branch: 169 files, 2254 tests, lint clean. Merged into main as c14fa23c on owner approval ("ادمج"), 2026-11-21.
- Notifications header "..." button: inspected on real Facebook on 2026-11-21. The menu has two items: "Mark all as read" and "Notification settings". Both are now built on branch `feat/facebook-notifications-menu`. Meta gives no read state for a Page's comments, so "read" is a time kept in the browser (localStorage) and the Unread tab hides what is at or before it; the settings item opens /settings/channels, where the Page is connected.
- Publishing matrix: reels are confirmed against Meta's reference; stories, pin, live, albums, events, polls and call-to-action are UNVERIFIED because Meta's own pages did not load from the sandbox. Nothing there is claimed either way.
- The ranked list of MISSING-ALLOWED items is in the two matrix files above.
