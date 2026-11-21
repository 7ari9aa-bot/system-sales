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

## Open items, not done

- Page liking a comment the Page itself wrote: Meta's docs are silent. Left hidden until tested against the real API.
- Shares count: the API returns `shares`, the app asks for it and drops it. Needs a new column on `social_posts` plus a migration, so it needs the owner's go-ahead.
- Comment order ("most relevant" vs "newest"): the gateway now accepts `order` (branch feat/facebook-comment-order, commit dbbed9ff, 2 backend tests that failed before the change and pass after). It is NOT shown on the screen. The Posts page reads comments from our own database, which has no Meta ranking, so a "Most relevant" button would be fake. "Newest" could be done locally by reversing `commented_at`. Needs the owner's call on whether to ship only that.
- Publishing matrix: reels are confirmed against Meta's reference; stories, pin, live, albums, events, polls and call-to-action are UNVERIFIED because Meta's own pages did not load from the sandbox. Nothing there is claimed either way.
- The ranked list of MISSING-ALLOWED items is in the two matrix files above.
