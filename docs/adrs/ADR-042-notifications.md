# ADR-042: Notification Infrastructure

**Date:** 2026-09-21  
**Status:** Accepted  
**Spec:** §166

## Problem
40 updates to the same conversation would produce 40 notifications, overwhelming users. No quiet hours, no digest, no priority-based delivery.

## Decision
Notification, NotificationPreference, NotificationDelivery, NotificationDigest. Supports in-app, email, push. Priority: Critical, Action Required, Information. Dedupe_key + quiet_hours + digest_policy. 40 updates to one conversation produce one digest.

## Alternatives
- One notification per event (rejected: notification storm)
- Email-only (rejected: no in-app or push)

## Rationale
§166: "40 updates for the same conversation should not produce 40 notifications."

## Consequences
- NotificationAggregator handles dedupe and digest
- SLA escalation follows priority: in-app -> push -> email
