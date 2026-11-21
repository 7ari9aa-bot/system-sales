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

## Release state

main = c14fa23c. It carries the whole parity line (comment look, post card look, comment order gateway, comment sort menu, shares count, the matrices and this report) plus the migration fe2026112013. Verified after the push: frontend suite 174 files, 2400 tests green; the affected backend tests (facebook pages, shares count, migrations, openapi lock) 28 passed; Vercel production deployment of c14fa23c READY and its bundle contains the sort menu, the share counter and the comment counter; the Northflank build of c14fa23c succeeded, its log shows `Running upgrade fe2026112012 -> fe2026112013` and the new container is running. A visual check on the live site was not done: the owner's browser tools were unavailable.

## Open items, not done

- Page liking a comment the Page itself wrote: Meta's docs are silent. Left hidden until tested against the real API.
- Shares count: done on its own branch, feat/facebook-shares-count (93655bbd backend with migration fe2026112013, 8e2d262d screen). It is cut from main, not from this branch, so it merges separately. Not deployed.
- Comment order: done on branch feat/facebook-comment-sort (59f8f167 sortComments, 06245ccb the menu), 6 + 4 tests that failed first. Facebook's three choices appear above a thread of two or more comments. "Newest" and "All comments" (oldest first) are real orders on our own copy of the thread; "Most relevant" is Facebook's private ranking, which the Graph API does not hand a Page, so it shows the API's order (oldest first) under that name. The gateway `order` parameter (feat/facebook-comment-order) stays for reads that go to Meta. Frontend suite on that branch: 169 files, 2254 tests, lint clean. Merged into main as c14fa23c on owner approval ("ادمج"), 2026-11-21.
- Notifications header "..." button: the one confirmed difference left in that screen. Its real menu was not inspected (the owner's browser tools dropped out), so it is not copied from a guess.
- Publishing matrix: reels are confirmed against Meta's reference; stories, pin, live, albums, events, polls and call-to-action are UNVERIFIED because Meta's own pages did not load from the sandbox. Nothing there is claimed either way.
- The ranked list of MISSING-ALLOWED items is in the two matrix files above.
