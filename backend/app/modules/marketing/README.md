# marketing

MARKETING domain — campaigns, ad_sets, ads, touchpoints, leads, conversions, attribution.

## Where things are

- `analytics.py`
- `attribution_service.py`
- `campaign.py`
- `journey.py`
- `models.py`
- `router.py`
- `routers/`
- `schemas.py`
- `service.py`

## HTTP

17 endpoints. Route prefixes: `/analytics`. Registered in `app/main.py`.

## Tables

- `ad_sets`
- `ads`
- `attributions`
- `campaign_runs`
- `campaigns`
- `conversions`
- `journey_runs`
- `journeys`
- `leads`
- `touchpoints`

## Depends on

Other modules imported from here: `analytics`, `billing`, `catalog`, `conversations`, `customers`, `identity`, `orders`, `platform`, `segments`.
Import boundaries between modules are ratcheted by `tests/test_module_boundaries.py`; do not add
new cross-module imports without a reason, and never raise that baseline yourself.

## Rules for working here

- Business rules live in the service layer. Routers parse and authorise, then call a service.
- Services `flush()` and never `commit()`; the caller owns the transaction.
- Every tenant table has row-level security. Bind the tenant before touching data.
- Emit events through the outbox in the same transaction as the change.
- Tests for this module are in `backend/tests/` (search for `marketing` in the file names and imports).

_The sections above are derived from the code; if you change the structure, update them._
