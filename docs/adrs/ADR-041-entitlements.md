# ADR-041: Entitlement Enforcement

**Date:** 2026-09-21  
**Status:** Accepted  
**Spec:** §165

## Problem
Entitlement checks (can_create_channel, can_add_user, can_send_campaign, can_use_ai, can_use_api) were scattered across modules, making it easy to miss checks and hard to audit.

## Decision
Central EntitlementService: takes tenant plan + tenant status + entitlement + current usage. Every Application Service calls it. Flow: Auth -> Tenant -> Permission -> Entitlement -> Domain rule -> Execute.

## Alternatives
- Per-module checks (rejected: inconsistent, easy to miss)
- Frontend-only checks (rejected: §12 backend is the final authority)

## Rationale
§165: "Entitlements are centrally enforced."

## Consequences
- Adding a new entitlement is a single service registration
- Entitlement denial is a clean 402/403 error, not a silent failure
