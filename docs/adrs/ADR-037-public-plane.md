# ADR-037: Public Customer Plane / Payment Boundary

**Date:** 2026-09-21  
**Status:** Accepted  
**Spec:** §159

## Problem
Webchat and checkout were treated as staff-plane endpoints, risking anonymous users getting staff permissions. Card data risked becoming application business data.

## Decision
Separate Customer-facing App plane: Public Gateway -> Session/Signed Token -> Tenant Resolution -> Rate Limit/CAPTCHA -> Allowed Public APIs. Payments use hosted payment page or provider tokenization. Payment entity stores provider reference, amount, currency, status, method metadata — never raw card data.

## Alternatives
- Same plane for staff and public (rejected: security risk)
- Store card data (rejected: PCI-DSS compliance nightmare)

## Rationale
§159: "Do not give anonymous users staff permissions."

## Consequences
- Public APIs are a separate subset with their own rate limits
- Payment provider tokenization means we never touch card data
