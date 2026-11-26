# RLS Migration: Platform & Visitor Tables (FINAL DESIGN)

> **Status:** APPLIED — migration `fe2026112602` + `provision.py` update.
> This document is the final design; it supersedes the original proposal.

## Motivation

Five platform-level tables either lacked RLS entirely or carried no
tenant-scoped policy. All five have **no `tenant_id` column** — they are
platform-level, not tenant-scoped — so the standard `tenant_isolation` policy
(which keys on `tenant_id`) does not apply. Each gets a hand-written policy.

| Table | RLS | SELECT | INSERT/UPDATE/DELETE |
|---|---|---|---|
| `visitor_events` | ENABLE (not forced) | app role, only when tenant GUC is bound | INSERT allowed (public telemetry); no UPDATE/DELETE |
| `platform_announcements` | ENABLE (not forced) | everyone (`USING (true)`) | none — app role cannot write; owner bypasses |
| `platform_announcement_dismissals` | ENABLE + FORCE | own `user_id` only | own `user_id` only (INSERT granted; no UPDATE/DELETE privilege) |
| `plan_prices` | ENABLE + FORCE | everyone (`USING (true)`) | none — privilege REVOKE'd in provision.py |
| `tax_rates` | ENABLE + FORCE | everyone (`USING (true)`) | none — privilege REVOKE'd in provision.py |

## Design decisions

### The GUC gate must use `NULLIF`, not bare `IS NOT NULL`

`current_setting('app.tenant_id', true)` returns `''` (empty string), not
`NULL`, after `SET LOCAL` scopes the GUC to a transaction that has ended. A
bare `IS NOT NULL` test is therefore always true on a pooled connection that
has seen a prior `SET LOCAL`, so the gate never closes. The correct guard is:

```sql
NULLIF(current_setting('app.tenant_id', true), '') IS NOT NULL
```

This matches the standard `tenant_isolation` policy in `provision.py`, which
uses `NULLIF(current_setting('app.tenant_id', true), '')::uuid`.

### `plan_prices` and `tax_rates` are NOT GUC-gated

The public marketing page (`GET /public/markets/{country}`) reads these tables
**with no tenant GUC bound** — it is a public, no-auth endpoint. A GUC gate
would return zero rows and break the page. The policy is `USING (true)`
(read for all); writes are blocked by the absence of a write policy and by
the `REVOKE INSERT, UPDATE, DELETE` in `provision.py`'s `PRIVILEGE_REFREEZE`.

The legacy `sales_app_read` policy that `provision.py` used to re-create on
these tables is dropped by the migration and **not** re-created —
`plan_prices_read` / `tax_rates_read` are the working replacements.

### `visitor_events` needs an INSERT policy

The public telemetry endpoint (`POST /public/telemetry`) writes visitor
events **without binding a tenant** (the caller is an anonymous website
visitor). The table has no `tenant_id` column, so the INSERT policy cannot
check tenancy. It is `WITH CHECK (true)` — the GRANT (SELECT, INSERT from
`fe2026103001`) is the first gate; RLS is the second (defense in depth).

Without this policy, RLS silently denied every INSERT and the telemetry
endpoint returned `{"ok": False}` for every event — the write was broken by
the original migration that added RLS without an INSERT policy.

### `platform_announcements` is NOT forced

Platform-admin writes go through the management API as the table owner, who
bypasses RLS when FORCE is not set. The app role (sales_app) has only a
SELECT policy and cannot write.

### `platform_announcement_dismissals` IS forced and uses `app.user_id`

A dismissal belongs to a *user*, not a tenant. The `app.user_id` GUC is
bound alongside `app.tenant_id` by the application layer. FORCE ensures even
the owner must bind the user GUC to read or write.

## Final policies

### 1. `visitor_events`

```sql
ALTER TABLE public.visitor_events ENABLE ROW LEVEL SECURITY;
-- NOT forced: owner/platform admin bypasses RLS for analytics reads.

CREATE POLICY visitor_events_read ON public.visitor_events
    FOR SELECT
    USING (NULLIF(current_setting('app.tenant_id', true), '') IS NOT NULL);

CREATE POLICY visitor_events_insert ON public.visitor_events
    FOR INSERT
    WITH CHECK (true);
-- No UPDATE/DELETE policy: sales_app cannot modify visitor events.
```

### 2. `platform_announcements`

```sql
ALTER TABLE public.platform_announcements ENABLE ROW LEVEL SECURITY;
-- NOT forced: platform admin writes bypass RLS as the owner.

CREATE POLICY announcements_read ON public.platform_announcements
    FOR SELECT USING (true);
-- No write policy: sales_app cannot write; owner bypasses.
```

### 3. `platform_announcement_dismissals`

```sql
ALTER TABLE public.platform_announcement_dismissals ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.platform_announcement_dismissals FORCE ROW LEVEL SECURITY;

CREATE POLICY dismissal_user_isolation ON public.platform_announcement_dismissals
    FOR ALL
    USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)
    WITH CHECK (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid);
```

### 4. `plan_prices`

```sql
ALTER TABLE public.plan_prices ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.plan_prices FORCE ROW LEVEL SECURITY;

CREATE POLICY plan_prices_read ON public.plan_prices
    FOR SELECT USING (true);
-- No write policy + REVOKE INSERT, UPDATE, DELETE in provision.py.
```

### 5. `tax_rates`

```sql
ALTER TABLE public.tax_rates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tax_rates FORCE ROW LEVEL SECURITY;

CREATE POLICY tax_rates_read ON public.tax_rates
    FOR SELECT USING (true);
-- No write policy + REVOKE INSERT, UPDATE, DELETE in provision.py.
```

## Provision script changes

1. `plan_prices` and `tax_rates` stay in `NO_TENANT_TABLES` (no `tenant_id` —
   the standard `tenant_isolation` policy does not apply).
2. `plan_prices` and `tax_rates` are **removed** from
   `REFERENCE_PLANE_READ_POLICIES` — the migration's `plan_prices_read` /
   `tax_rates_read` policies supersede the legacy `sales_app_read`.
3. `visitor_events`, `platform_announcements`, and
   `platform_announcement_dismissals` are not in `NO_TENANT_TABLES` and have
   no `tenant_id`, so `provision.py`'s `_tenant_tables()` never touches them.
   Their RLS policies are entirely migration-owned.

## Tests

`backend/tests/security/test_platform_visitor_rls.py` verifies, as the
`sales_app` role (not the owner), that each table's RLS policy allows and
denies the right operations per this design.
