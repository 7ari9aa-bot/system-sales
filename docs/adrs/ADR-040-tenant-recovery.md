# ADR-040: Tenant-Scoped Recovery

**Date:** 2026-09-21  
**Status:** Accepted  
**Spec:** §164

## Problem
PITR restores the entire database. If Tenant A accidentally deletes 3000 customers, restoring the entire DB overwrites all other tenants' recent data.

## Decision
Soft-delete/tombstones + tenant-scoped restore process: restore backup to isolated recovery DB, extract target tenant records, validate against current state, restore selected records. Never restore the entire production database over other tenants.

## Alternatives
- Full PITR for every incident (rejected: §164 overwrites other tenants)
- No recovery (rejected: data loss is unacceptable)

## Rationale
§164: "Tenant-specific recovery is different from full-database DR."

## Consequences
- TenantRestoreJob orchestrates the full process
- Tombstones prevent re-resurrection of intentionally deleted records
