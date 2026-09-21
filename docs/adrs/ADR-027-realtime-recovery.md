# ADR-027: Realtime Recovery

**Date:** 2026-09-21  
**Status:** Accepted  
**Spec:** §149

## Problem
When a realtime client reconnects, it might miss events that were published during the disconnection. Role changes or tenant suspension must also be reflected immediately.

## Decision
Each realtime client has connection_id, subscription scope, and last_event_id/cursor. On reconnect: re-authenticate, re-check tenant/role/permissions, resume from cursor or resync authoritative state. If role changed or tenant was suspended, subscription is revoked.

## Alternatives
- Full resync on every reconnect (rejected: too expensive)
- No cursor (rejected: event gaps)

## Rationale
§149: "Realtime supports reconnect and authorization revalidation."

## Consequences
- Realtime gateway stores cursors per connection
- Subscription revocation is immediate on role/tenant change
