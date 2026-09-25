# features

Nothing here yet — Phase 0 ships no screens.

One directory per product surface (`inbox`, `customers`, `orders`, `analytics`,
`ai`), arriving in Phase 4. A feature directory owns its queries, its contract
schemas and its states; it does **not** own a fetch, an `invoke`, a tenant id, or
a money calculation — those belong to `../platform` and `../shared`
(see `../docs/platform-boundary.md`).
