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

## Open items, not done

- Page liking a comment the Page itself wrote: Meta's docs are silent. Left hidden until tested against the real API.
- Shares count: the API returns `shares`, the app asks for it and drops it. Needs a new column on `social_posts` plus a migration, so it needs the owner's go-ahead.
- Comment order ("most relevant" vs "newest") and the low-quality filter: the gateway pins `order=chronological` and `filter=toplevel`. The backend test environment is not installed in the sandbox, so a failing-first test could not be run and no change was made.
- Visual comparison of Insights, Messages and Reels against real Facebook: not done. The owner's local browser tools were not available.
- Publishing matrix: reels are confirmed against Meta's reference; stories, pin, live, albums, events, polls and call-to-action are UNVERIFIED because Meta's own pages did not load from the sandbox. Nothing there is claimed either way.
- The ranked list of MISSING-ALLOWED items is in the two matrix files above.
