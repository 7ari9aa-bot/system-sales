# ADR-019: Human Approval Workflow

**Date:** 2026-09-21  
**Status:** Accepted  
**Spec:** §135

## Problem
High-risk AI actions (create_order, refund, cancel_order, change_price, delete_data) need human-in-the-loop approval, but there was no durable approval mechanism.

## Decision
ApprovalRequest, ApprovalStep, and ApprovalDecision are first-class entities. An AI run that hits a high-risk tool enters WAITING_APPROVAL (persisted). On approval it resumes; on rejection/expiry it stops.

## Alternatives
- Block and fail (rejected: poor UX, wastes the AI run)
- Email-based approval (rejected: not auditable, not durable)

## Rationale
§15: "HIGH-risk actions require human-in-the-loop approval. AI cannot bypass via prompt or retry."

## Consequences
- If a customer sends a new message while approval is pending, the approval becomes stale and context is re-evaluated
- Approval has an expiry; expired approvals auto-cancel the run
