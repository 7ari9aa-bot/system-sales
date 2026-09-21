# ADR-013: Tenant Context Across Execution Modes

**Date:** 2026-09-21  
**Status:** Accepted  
**Spec:** §125

## Problem
Tenant context was originally HTTP-only. Workers, webhooks, scheduled jobs, n8n callbacks, and AI runs all need tenant scoping, but without a unified mechanism, each path could leak data across tenants.

## Decision
Every execution path (HTTP, webhook, worker, outbox relay, Redis consumer, scheduled job, n8n callback, AI run, maintenance/billing/retention/analytics job) must resolve and set a transaction-scoped tenant context before touching tenant-scoped data.

## Alternatives
- Application-level filtering only (rejected: §11 RLS is defense-in-depth)
- Thread-local tenant context (rejected: async context is more reliable in FastAPI)

## Rationale
RLS policies use the tenant context set via `SET LOCAL app.tenant_id`. Without setting it in every execution path, RLS is bypassed for non-HTTP paths.

## Consequences
- Workers must call `bind_tenant()` at the start of each job
- Cross-tenant jobs enumerate tenants and open separate transactions per tenant
- Webhook ingress resolves tenant via ingress mapping before entering the business path

## Security Implications
Prevents cross-tenant data leakage in all execution modes.

## Migration / Exit Strategy
If we move to per-tenant database isolation, the tenant context mechanism becomes the routing key.
