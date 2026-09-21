# ADR-020: n8n vs Internal Workflow Ownership

**Date:** 2026-09-21  
**Status:** Accepted  
**Spec:** §136

## Problem
n8n was being treated as the source of truth for tenant workflows, meaning workflow definitions lived in n8n and were lost if n8n was reinstalled.

## Decision
Our Workflow Domain is the canonical workflow definition (stored in our DB). n8n is an execution/integration adapter. Tenant credentials use Secret References, not raw text in workflow definitions. n8n callbacks use Automation Actor + tenant-scoped token.

## Alternatives
- n8n as source of truth (rejected: §3 n8n never owns core business truth)
- Build our own full workflow engine (rejected: too costly, n8n is good at execution)

## Rationale
§136: "Tenant Workflow -> Our DB -> Our Workflow Version -> Execution Policy -> Internal engine and/or n8n adapter."

## Consequences
- Workflow definitions survive n8n reinstalls
- Scoped credentials prevent n8n from accessing other tenants' data
