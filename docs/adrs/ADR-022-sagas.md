# ADR-022: Sagas / Process Managers

**Date:** 2026-09-21  
**Status:** Accepted  
**Spec:** §139

## Problem
Long business processes (Order -> Payment -> Inventory -> Fulfillment -> Shipment) relied on implicit choreography. Failures were hard to debug and compensation was ad-hoc.

## Decision
Explicit Saga/Process Manager state machine. Each step has execute() and compensate(). State is persisted in the `sagas` table. On failure, compensation runs in reverse order.

## Alternatives
- Pure event choreography (rejected: §139 "not ambiguous choreography")
- Distributed sagas with compensation only (rejected: need forward progress too)

## Rationale
§139: "Long business processes use explicit state machines/process managers."

## Consequences
- Each saga type registers step handlers with the SagaManager
- Compensation is best-effort; some actions (e.g. sending an email) cannot be undone
- Saga state is queryable for operations monitoring
