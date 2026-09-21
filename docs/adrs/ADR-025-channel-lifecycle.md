# ADR-025: Channel Account Lifecycle

**Date:** 2026-09-21  
**Status:** Accepted  
**Spec:** §145

## Problem
ChannelAccount had no lifecycle states — a disconnected account looked the same as an active one, causing silent message failures.

## Decision
Full lifecycle: PENDING -> CONNECTING -> ACTIVE -> REAUTH_REQUIRED -> RESTRICTED -> DISCONNECTED -> DISABLED. Supports credential/token refresh, provider account mapping, quality/status metadata, rate limits, webhook health.

## Alternatives
- Boolean is_active (rejected: too coarse)
- External monitoring only (rejected: state must be in our DB)

## Rationale
§145: "Core sees canonical state; each adapter has provider-specific state."

## Consequences
- Messages to a DISCONNECTED account are queued, not sent
- REAUTH_REQUIRED triggers a notification to reconnect
