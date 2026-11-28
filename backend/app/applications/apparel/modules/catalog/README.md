# catalog

PRODUCTS domain — products, variants, categories, brands, images, prices.

## Where things are

- `external/`
- `models.py`
- `router.py`
- `routers/`
- `service.py`
- `services/`
- `website_platform.py`

## HTTP

28 endpoints. Route prefixes: see `router.py`. Registered in `app/main.py`.

## Tables

- `brands`
- `categories`
- `product_identifiers`
- `product_images`
- `product_option_values`
- `product_options`
- `product_prices`
- `product_variant_option_values`
- `product_variants`
- `products`
- `source_of_truth_policies`

## Depends on

Other modules imported from here: `customers`, `identity`, `inventory`.
Import boundaries between modules are ratcheted by `tests/test_module_boundaries.py`; do not add
new cross-module imports without a reason, and never raise that baseline yourself.

## Rules for working here

- Business rules live in the service layer. Routers parse and authorise, then call a service.
- Services `flush()` and never `commit()`; the caller owns the transaction.
- Every tenant table has row-level security. Bind the tenant before touching data.
- Emit events through the outbox in the same transaction as the change.
- Tests for this module are in `backend/tests/` (search for `catalog` in the file names and imports).

_The sections above are derived from the code; if you change the structure, update them._
