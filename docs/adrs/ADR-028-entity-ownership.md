# ADR-028: Canonical Entity & Ownership Model

**Date:** 2026-09-21  
**Status:** Accepted  
**Spec:** §150-151

## Problem
Every entity was implicitly tenant-scoped, but some entities (conversations, inventory, channel accounts) are location or workspace scoped. RLS policies reflected only tenant_id.

## Decision
Each entity has an explicit `ownership_scope`: Tenant, Workspace, or Location. RLS policies reflect the full ownership hierarchy (Tenant -> Workspace -> Location). Users can only access locations they are authorized for.

## Alternatives
- tenant_id only everywhere (rejected: §151 "not everything is tenant_id only")
- Application-level filtering (rejected: §11 RLS is defense-in-depth)

## Rationale
§151: "RLS must reflect the same ownership hierarchy."

## Consequences
- Migration adds workspace_id/location_id to entities that need them
- RLS policies check the full hierarchy chain
