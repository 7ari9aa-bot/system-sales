# ADR-038: External Commerce Source of Truth

**Date:** 2026-09-21  
**Status:** Accepted  
**Spec:** §161

## Problem
Connecting Shopify/WooCommerce required blind two-way sync, which caused data conflicts and no clear authority.

## Decision
SourceOfTruthPolicy per entity: INTERNAL, EXTERNAL, or HYBRID. For each, define sync direction, conflict policy, last_synced_at, external_version, internal_version. CSV import goes through Validation -> Identity Resolution -> Deduplication -> Domain Application Services (never direct DB).

## Alternatives
- Blind two-way sync (rejected: no conflict resolution)
- External always wins (rejected: some entities are internal)

## Rationale
§161: "No blind two-way sync."

## Consequences
- The ShopifyAdapter uses SourceOfTruthPolicy to decide direction
- Conflicts surface for manual resolution when policy is "manual"
