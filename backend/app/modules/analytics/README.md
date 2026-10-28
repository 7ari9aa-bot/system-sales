# analytics

Metrics and findings: the semantic metric layer, retention, evidence-backed answers and the typed capabilities the sales-intelligence agent may call.

## Where things are

- `capabilities.py`
- `compiler.py`
- `confidence.py`
- `contracts.py`
- `coverage.py`
- `drivers.py`
- `engines.py`
- `evaluation/`
- `events.py`
- `evidence.py`
- `findings.py`
- `maturity.py`
- `models.py`
- `numbers.py`
- `persistence.py`
- `retention.py`
- `router.py`
- `routers/`
- `schemas.py`
- `semantic.py`
- `service.py`
- `services/`
- `timekit.py`
- `validators.py`

## HTTP

8 endpoints. Route prefixes: `/analytics`. Registered in `app/main.py`.

## Tables

- `analysis_evidence`
- `analysis_findings`

## Depends on

Other modules imported from here: `identity`, `platform`.
Import boundaries between modules are ratcheted by `tests/test_module_boundaries.py`; do not add
new cross-module imports without a reason, and never raise that baseline yourself.

## Rules for working here

- Business rules live in the service layer. Routers parse and authorise, then call a service.
- Services `flush()` and never `commit()`; the caller owns the transaction.
- Every tenant table has row-level security. Bind the tenant before touching data.
- Emit events through the outbox in the same transaction as the change.
- Tests for this module are in `backend/tests/` (search for `analytics` in the file names and imports).

_The sections above are derived from the code; if you change the structure, update them._
