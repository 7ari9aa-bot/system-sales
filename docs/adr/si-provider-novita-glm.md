# ADR: SI agent provider — Novita serving GLM (D16)

Status: accepted (2026-10-03)

## Context

Spec §2.1 pins the SI agent's primary model via config, and open decision
D16 asks which provider is approved for GLM and whether data-privacy
requirements are satisfied. The provider key was supplied by the owner for
development; production keys rotate through the owner's channel.

## Decision

* Provider: **Novita** (`https://api.novita.ai/v3/openai`, OpenAI-compatible).
* Models: `glm-5.3` (strong alias — deep analyses), `glm-5.3-flash` (fast
  alias — interactive turns). Exact names live in `model_configs` rows that
  `scripts/configure_si.py` upserts; swapping provider is a row update.
* The SI agent resolves through the platform gateway (`resolve_model_config`):
  tenant `model_configs` row first, then settings — never hard-coded.

## Data flow

Analysis requests ship: the question text, resolved periods, and compact
capability summaries (aggregated numbers only — no raw customer rows, no
PII-bearing evidence; §14 aggregates first). Product names may transit the
model and are treated as untrusted text (§14 prompt-injection rules).

## Consequences

* PII-bearing drilldowns must reach the model only after aggregation; the
  evidence pack carries ids, the drilldown route returns rows to the
  DASHBOARD, never to the model.
* Key handling: the provider key lives in the environment / `backend/.env`
  (gitignored). The key shared in chat is rotated by the owner; the dev
  key in the tree's ignored env is development-scoped.
* Per-tenant override stays available: a tenant's own `model_configs` row
  outranks this deployment default (§2.1 "config keys, not code constants").
