# ADR-048: Entity Ownership Scope Concretization

**Date:** 2026-09-23  
**Status:** Accepted (amends ADR-028)  
**Spec:** §151 (Q4)

## Problem
ADR-028 decided that "each entity has an explicit ownership_scope: Tenant, Workspace, or Location" but left the per-entity assignment open ("per business decision"), and nothing stamped a scope on writes: every mutation created rows with tenant_id only, so the §151 hierarchy was structurally present (Q1–Q3: FORCE RLS tables, GUC binding, admin API) but inert for data.

## Decision
Concrete ownership map, enforced by the write path:

| Scope | Entities |
|---|---|
| **Location** | Conversation, Message, Assignment, Attachment, AI session, Inventory (balances, movements, transfers, reservations, warehouses), Tasks + SLA policies/events + business calendars, Channel accounts |
| **Workspace** | Order (+items, payments, shipments, refunds, status history), Customer (+identities, notes, tags, events), Campaign (+ad sets, ads, leads, conversions, touchpoints, attributions), Catalog (products, variants, prices, brands, categories), Workflow + executions + failures, Journeys |
| **Tenant (by design)** | Billing (invoices, subscriptions, entitlements), privacy/DPA tables, platform meta (FeatureFlag, SavedView, SecretValue, Job, integrations config), users/roles/tenancy |

Two notes on the fuzzy rows: a conversation is Location-keyed because the channel number lives at a site; orders are Workspace-keyed because checkout may be fulfilled from any location in the workspace (inventory is the per-location concern).

**Stamping mechanism (how mutations get the scope without per-call-site plumbing):**
1. `get_tenant_ctx` validates the requested scope fail-closed (`resolve_scope`, Q2) and publishes it to a request-scoped contextvar: `app.core.tenancy.set_current_scope(workspace_id, location_id)`.
2. `WorkspaceScopeMixin` columns read that contextvar as their INSERT default — every row of every mixin-bearing table is stamped automatically inside a scoped request; unscoped writers (workers, jobs) keep NULL = tenant-wide, the pre-§151 semantics.
3. The outbox writer (`add_outbox_event`) fills `workspace_id`/`location_id` envelope keys from the same context when the caller omits them — the event scope always matches the mutation scope it describes (explicit args win).
4. Rows explicitly constructed with a scope value keep it — the context is a default, never an override.

## Alternatives
- Thread `ctx.workspace_id` through every service signature (rejected: ~90 call sites, easy to miss one, and workers have no ctx).
- DB trigger reading the GUCs (rejected: business semantics belong in the domain layer; triggers are invisible to tests and ORM objects).
- RLS-only scoping without stamped columns (rejected: §151 says the RLS must reflect ownership — with NULL columns there is nothing to reflect).

## Consequences
- Migration d4a7c1e9f0b5 adds workspace_id/location_id (+FK SET NULL, indexes) to the seven operations/automation tables that lacked them.
- Existing rows stay NULL (tenant-wide) — no backfill: the system has no production users yet, and scope becomes meaningful only once clients start sending X-Workspace-Id / X-Location-Id.
- Scope-having events now carry the keys in meta from the first scoped write; consumers must keep treating them as optional (they already do).
- ADR-028's "per business decision" is now decided; COMPLIANCE_MATRIX §151 can move to done.
