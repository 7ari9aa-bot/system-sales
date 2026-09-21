# ADR-026: Auth / Platform Admin Separation

**Date:** 2026-09-21  
**Status:** Accepted  
**Spec:** §146-147, §160

## Problem
Platform admin operations (managing tenants, plans, DLQ, system incidents) were mixed with tenant admin operations, creating a security risk.

## Decision
Separate Platform Admin plane from Tenant Admin. Platform Admin has separate permissions, separate audit scope, and break-glass access. JWT contains `is_platform_admin` claim. Break-glass requests are time-limited, scoped, and audited.

## Alternatives
- Shared superuser (rejected: §147 "no shared admin credentials")
- Per-tenant admin only (rejected: platform operations need cross-tenant access)

## Rationale
§160: "Platform Admin is separate from Tenant Admin."

## Consequences
- Platform admin routes use `require_platform_admin` dependency
- Break-glass access expires automatically and appears in independent platform audit
