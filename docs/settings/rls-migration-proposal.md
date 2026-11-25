# RLS Migration Proposal: Platform & Visitor Tables

> **Status:** PROPOSAL — not applied to any database. This document describes
> the RLS policies that *should* be created when the tables below are
> introduced or hardened. No Alembic migration file has been written and no
> `provision.py` change has been made.

## Motivation

Five tables currently either lack RLS entirely or carry no tenant-scoped
policy:

| Table | Current state | Desired state |
|---|---|---|
| `visitor_events` | Does not exist yet | Insert-only for the app role; no SELECT |
| `platform_announcements` | Does not exist yet | Read for all tenants; write for platform roles only |
| `platform_announcement_dismissals` | Does not exist yet | Per-user SELECT/INSERT/DELETE |
| `plan_prices` | In `NO_TENANT_TABLES` (no RLS) | Read-only for the app role |
| `tax_rates` | In `NO_TENANT_TABLES` (no RLS) | Read-only for the app role |

The existing `provision.py` marks `plan_prices` and `tax_rates` as
system/global tables with no RLS. That was acceptable when only the
platform admin wrote them and the app role had no direct access path. Now
that billing and taxation modules read these tables from inside a tenant
transaction, the absence of RLS means a bug in the `app.tenant_id` GUC
binding silently exposes every tenant's prices and tax rates — the
defence-in-depth principle (AGENTS.md rule 5) is violated.

## Proposed policies

### 1. `plan_prices` — read-only for the app

Plan prices are platform-level data: the `plans` table defines subscription
tiers, and `plan_prices` holds the recurring price for each plan in each
currency. The app role (tenant-scoped sessions) must be able to **read**
the price for its own plan but must never **write**.

```sql
ALTER TABLE public.plan_prices ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.plan_prices FORCE ROW LEVEL SECURITY;

-- The app role reads all plan_prices (they are global catalog data, not
-- tenant-scoped).  The policy allows SELECT when the GUC is set (any tenant
-- may read any plan's price — pricing is public), but blocks all writes.
CREATE POLICY plan_prices_read ON public.plan_prices
    FOR SELECT
    USING (current_setting('app.tenant_id', true) IS NOT NULL);

-- No INSERT/UPDATE/DELETE policy: FORCE RLS means the app role cannot
-- write at all.  Platform writes go through the platform admin role,
-- which is RLS-exempt (or uses a separate connection with the GUC unset).
```

**Why read-all, not tenant-filtered:** `plan_prices` has no `tenant_id`
column — it is catalog data shared across all tenants. A tenant needs to
read the price of *its own* plan, but the plan lookup happens through
`tenants.plan_id`, so the app reads `plan_prices` by `plan_id`, not by
`tenant_id`. RLS here is a write-protection fence, not a tenant filter.

### 2. `tax_rates` — read-only for the app

Same shape as `plan_prices`: global tax-rate catalog, read by the
taxation module inside tenant transactions, written only by the platform
admin.

```sql
ALTER TABLE public.tax_rates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tax_rates FORCE ROW LEVEL SECURITY;

CREATE POLICY tax_rates_read ON public.tax_rates
    FOR SELECT
    USING (current_setting('app.tenant_id', true) IS NOT NULL);
```

### 3. `platform_announcements` — read for all, write for platform

Platform announcements are messages the platform operator pushes to all
tenants (maintenance windows, new features, policy changes). Every tenant
may **read** them; only platform-admin roles may **write**.

The table carries a nullable `tenant_id` (NULL = global announcement) or
may be entirely tenant-agnostic. The proposed design:

```sql
ALTER TABLE public.platform_announcements ENABLE ROW LEVEL SECURITY;
-- NOT forced: platform-admin writes with no tenant GUC.

-- Every tenant session (GUC set) may read all announcements.
CREATE POLICY announcements_read ON public.platform_announcements
    FOR SELECT
    USING (true);

-- Only the platform admin role (no tenant GUC, connected as the
-- platform user) may write.  The app role never has INSERT/UPDATE/DELETE.
CREATE POLICY announcements_write ON public.platform_announcements
    FOR ALL
    USING (current_setting('app.tenant_id', true) IS NULL)
    WITH CHECK (current_setting('app.tenant_id', true) IS NULL);
```

**Why not FORCE:** platform-admin writes must work without the tenant GUC.
`FORCE` would block even the table owner. Without `FORCE`, the owner
(superuser/platform admin) bypasses RLS, and the app role (tenant-scoped)
can only SELECT.

### 4. `platform_announcement_dismissals` — per user

Each user may dismiss (hide) an announcement for themselves. The table
carries `user_id` and `announcement_id`. A user may only see, create, or
delete their own dismissals.

```sql
ALTER TABLE public.platform_announcement_dismissals ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.platform_announcement_dismissals FORCE ROW LEVEL SECURITY;

CREATE POLICY dismissal_user_isolation ON public.platform_announcement_dismissals
    FOR ALL
    USING (
        NULLIF(current_setting('app.user_id', true), '')::uuid = user_id
    )
    WITH CHECK (
        NULLIF(current_setting('app.user_id', true), '')::uuid = user_id
    );
```

**Key:** this uses `app.user_id`, not `app.tenant_id`. A dismissal belongs
to a *user*, not a tenant — the same user may exist in multiple tenants
and their dismissals should follow them. The `app.user_id` GUC is already
bound by the application layer alongside `app.tenant_id`.

### 5. `visitor_events` — insert-only

Visitor events track anonymous storefront visitors (page views, product
views, cart events) before they become customers. The app must be able to
**INSERT** these events but must never **SELECT** them (analytics on
visitor events is a platform-level concern, not a tenant one).

```sql
ALTER TABLE public.visitor_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.visitor_events FORCE ROW LEVEL SECURITY;

-- Tenant-scoped INSERT: the event is tagged with the current tenant.
CREATE POLICY visitor_events_insert ON public.visitor_events
    FOR INSERT
    WITH CHECK (
        NULLIF(current_setting('app.tenant_id', true), '')::uuid = tenant_id
    );

-- No SELECT policy: the app role cannot read visitor_events at all.
-- Analytics are run by the platform admin (RLS-exempt) or a dedicated
-- analytics role.
```

## Provision script changes

When this proposal is implemented, `provision.py` must be updated:

1. **Remove** `plan_prices` and `tax_rates` from `NO_TENANT_TABLES`.
2. **Add** `platform_announcement_dismissals` to the `_tenant_tables()` list
   (it has a `tenant_id`) but override its policy to use `app.user_id`.
3. **Add** `platform_announcements` to `NULLABLE_TENANT_TABLES` if it carries
   a nullable `tenant_id`, or handle it as a special case (like `audit_logs`).
4. **Add** `visitor_events` to the standard `_tenant_tables()` flow with a
   custom INSERT-only policy (no SELECT).

## Migration ordering

1. Create the tables (if they don't exist) in a schema migration.
2. Enable RLS + create policies in the same migration.
3. Update `provision.py` to maintain the policies idempotently.
4. Add guard tests to `tests/test_rls_*` that verify the policies enforce
   isolation (insert blocked without GUC, select blocked for app role, etc.).

## Open questions

- **`platform_announcements` tenancy:** should announcements be global
  (no `tenant_id`, one row per announcement) or per-tenant (a row per
  tenant × announcement, created by a fan-out job)? The proposal assumes
  global with `tenant_id IS NULL`.
- **`visitor_events` retention:** the table will grow fast; a retention
  policy (TTL or scheduled purge) should accompany the RLS migration.
- **Platform admin role:** does the codebase already have a separate
  platform-admin database role, or do platform writes use the superuser?
  This affects whether `platform_announcements` needs `FORCE` or not.
