# website

The in-house website builder: presentation truth (templates, sections,
versions, publishing, the public read model) and the website purchase
lifecycle. Owns NO business truth — commerce entities are referenced by id
only (e.g. `ProductGridProps.collection_id`).

## Where things are

- `models.py` — `websites`, `website_versions`, `website_pages`,
  `website_page_sections`, `website_purchases` (tenant-scoped, RLS) and
  `website_published_sites` (the PUBLIC read model, deliberately no
  `tenant_id` so the Boot Reconciler never demands RLS on it).
- `sections.py` — the declarative section registry (10 types, pydantic props,
  `extra="forbid"`); publish-time validation normalizes every section.
- `slugs.py` — subdomain-safe slug rules + reserved names.
- `errors.py` — domain exceptions (publish validation is a 422).
- `templates/` — `catalog.py` (fail-closed manifest registry) +
  `reference/` (the two built-in templates). A template = manifest + CSS;
  the 20 merchant templates land here as folders.
- `services/purchase_service.py` — purchase lifecycle; manual payment
  confirmation (platform admin) activates + publishes in one transaction.
- `services/publishing_service.py` — draft/published/archived state machine;
  validates BEFORE mutating (failed publish keeps the live site); writes the
  public snapshot in the same transaction.
- `services/content_service.py` — identity edits (live, not versioned),
  section edits (clone live -> draft), editor schema from the registry.
- `services/public_service.py` — snapshot read + live products via
  `Base.metadata.tables` (boundary-safe, no cross-module import).
- `rendering/renderer.py` — snapshot -> HTML; escapes everything, URL scheme
  allowlist, per-template renderer overrides, RTL default.
- `router.py` — two surfaces: merchant (`/website/*`, TenantCtxDep) and
  public (`/sites/{slug}` + Host-based `GET /`) mounted at ROOT in `app/main.py`.
  The owner purchase queue (`/owner/website-purchases*`) was REMOVED: the owner now manages
  websites from the owner console's "Websites" section (Fihrist Sites platform,
  `platform/routers/sites_platform.py`). The purchase service and its SECURITY DEFINER
  functions remain; nothing in the app routes to them any more.

## HTTP

Merchant: `GET /website/templates`, `GET /website/overview`,
`POST /website/purchase`, `POST /website/purchase/payment-reference`,
`POST /website/purchase/cancel`, `GET /website/editor-schema`,
`GET /website/content`, `POST /website/content/identity`,
`POST /website/content/section`, `POST /website/publish`,
`POST /website/rollback`, `GET /website/versions`.
Public (root, no auth): `GET /sites/{slug}`, `GET /` (Host mode when
`websites_served_domain` is set). See `docs/SITES_SERVING.md`.

## Tables

Six — see `models.py`. Cross-tenant helpers are SECURITY DEFINER functions in
migration `fe2026110505`: `website_slug_taken`, `resolve_website_purchase_tenant`,
`admin_website_purchases` — no tenant policy is weakened for the admin path.

## Depends on

Other modules imported from here: `identity` (deps, models — ratcheted edges).
Catalog products are read through `Base.metadata.tables["products"]`, NOT an
import. The old external-platform client (`client.py`) is gone;
`catalog/website_platform.py` (X-WP-Key exposure) remains but is dormant.

## Rules for working here

- Presentation truth only: never copy products/orders/customers into this
  module; sections hold references.
- The public surface reads ONLY `website_published_sites`. Anything new the
  public page needs must be snapshotted at publish time, in that transaction.
- Publish validates first, mutates after — a failed publish never breaks the
  live site.
- The customer agent cannot create websites; purchases are human actions
  confirmed by a platform admin.
- Services `flush()` and never `commit()`; events go through the outbox in
  the same transaction (`website.purchase.created`, `website.purchase.confirmed`,
  `website.published`, `website.rolled_back`).
- Tests: `backend/tests/test_website_builder.py` and the rewritten
  `test_website_bridge.py` (catalog bridge + public surface).

_The sections above are derived from the code; if you change the structure, update them._
