# ADR-046: Channel Test Environments

**Date:** 2026-09-21  
**Status:** Accepted  
**Spec:** §170

## Problem
Production channels (WhatsApp, Instagram) were sometimes connected to dev/staging, risking real customer messages being processed in test environments.

## Decision
Development and staging use test accounts, test numbers, sandbox/test credentials. Configuration is environment-scoped: channel credentials, webhooks, templates, provider IDs. Production channels are never connected to dev/staging by default.

## Alternatives
- Use production credentials in dev (rejected: risk of real customer interaction)
- Mock everything (rejected: need integration testing)

## Rationale
§170: "Production channels do not connect to dev/staging by default."

## Consequences
- Environment config separates production and test credentials
- Template testing is part of the deployment strategy
