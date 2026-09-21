# ADR-043: Metric Definition Registry

**Date:** 2026-09-21  
**Status:** Accepted  
**Spec:** §167

## Problem
Revenue, First Response Time, AI Resolution Rate, Conversion Rate, AOV, ROAS were calculated differently in Home, Analytics, Reports, and Billing — leading to inconsistent numbers across the product.

## Decision
MetricDefinition registry: name, definition, source, filters, timezone rule, business-hours rule, currency rule, refund treatment, aggregation, version. Every dashboard/report uses the same definition.

## Alternatives
- Per-page calculation (rejected: inconsistent numbers)
- External BI tool only (rejected: not integrated)

## Rationale
§167: "Metrics have one canonical definition."

## Consequences
- Changing a metric definition bumps the version
- Old reports are reproducible because they reference the version they used
