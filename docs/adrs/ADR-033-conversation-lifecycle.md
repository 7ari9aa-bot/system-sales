# ADR-033: Conversation Lifecycle

**Date:** 2026-09-21  
**Status:** Accepted  
**Spec:** §156

## Problem
Conversations were implicitly "one customer = one conversation forever", which didn't reflect reality (customer closes a conversation, starts a new topic; human takeover changes AI state).

## Decision
Explicit lifecycle: OPEN, WAITING_CUSTOMER, WAITING_HUMAN, WAITING_AI, PAUSED, CLOSED. Rules: customer replies after closed -> reopen per policy; new subject -> may create new conversation; human takeover -> AI state changes; customer merge -> preserve conversations, remap canonical customer.

## Alternatives
- Single open conversation per customer (rejected: doesn't model reality)
- No lifecycle states (rejected: can't drive SLA or AI behavior)

## Rationale
§156: "Conversation lifecycle is explicit."

## Consequences
- Reopen policies are configurable per channel
- Customer merge remaps conversation.customer_id
