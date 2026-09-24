# ADR-053 — A tenant trades in one currency, so a second currency is a refusal

- **Status:** Accepted
- **Date:** 2026-09-23
- **Spec:** §47 (money: currency belongs to the tenant) · §78 (order API)
- **Related:** ADR-054 (refund ledger), `docs/COMPLIANCE_MATRIX.md` §47

Wave 4 / task W4-T3. Evidence: `backend/tests/test_tenant_currency.py`
(21 cases; the DB-backed ones run on CI Postgres). Closes GAP M7 and the §47 row of
`docs/COMPLIANCE_MATRIX.md`.

## Context

§47 asks for two things: `كل monetary object يجب أن يخزن amount_minor + currency، وليس
floating point money`, and for cross-currency reporting an original amount that is never
rewritten — the rate is stored beside it (`لا نغير المبلغ الأصلي`).

The second half was already true by accident: every money column is `NUMERIC(14,2)` and
every value a `Decimal`. The first half was not true at all, and the audit's evidence was
that `amount_minor` appeared nowhere in the codebase — while `docs/adr/ADR-001-to-004.md`
claimed an adapter lived in `model_kit.py`. What actually existed was worse than a missing
integer column:

* **The currency was a literal.** `"EGP"` appeared in eight places across five modules —
  checkout, payments, refunds, billing invoices, marketing conversions, the customer money
  card. A tenant was Egyptian whether it liked it or not, and there was no setting anywhere
  to say otherwise.
* **`grand_total` was a copy of `subtotal`.** `discount_total`, `shipping_total` and
  `tax_total` were columns checkout left at zero. A merchant who quoted a discount collected
  full price; one who charged shipping invoiced it nowhere.
* **The price ladder was write-only.** `ProductPrice` rows could be created and listed, and
  nothing read them: `create_order` priced every line from `variant.price`.
* **`app/core/money.py` was a second answer to "what is an amount".** A complete minor-unit
  value object, imported by nobody, living beside `orders/money.py`, which is the one the
  money path actually uses.

## Decisions

### 1. One currency per tenant, on the tenant row

`tenants.currency` (`String(3)`, `server_default 'EGP'`) is the only answer to "what is
money here". Migration `b8e1c4d5a7f2`, model at `identity/models.py:66`.

Every read path takes it from one of two places, and neither is a literal:

* the request path — `get_tenant_ctx` selects it on the same query it already runs for the
  §48 lifecycle state, so `ctx.currency` costs no extra round trip;
* everything without a request — the AI tool runtime, a worker, a script — through
  `app.core.tenancy.resolve_tenant_currency(session, tenant_id)`.

*Why a column on the tenant and not a settings blob:* the value gates writes in five
modules. A JSONB setting cannot be compared in the same SELECT, and the eight literals it
replaces were all in `WHERE`-adjacent positions.

*Why `resolve_tenant_currency` reaches for `identity.models` from `app.core`:* the
alternative is an `orders → identity`, `billing → identity`, `marketing → identity` import
for one column — the boundary ratchet counts each. `app/core/mfa.py` already sets that
precedent, and `tests/test_module_boundaries.py` counts only edges from files under
`app/modules/**`.

### 2. A foreign currency is refused, never converted

Because the tenant has one currency, a write that names another is not a rate to apply — it
is a mistake, or a different shop's row. So:

* checkout in a currency other than the tenant's → `ConflictError`
  ("money no rate has agreed on");
* a payment stamped in a currency other than the order's → `ConflictError`, because the
  amount received would not be the amount owed;
* a price tier in a currency the tenant does not trade in → refused **on write**, since a
  tier that can never be sold is not data but a future wrong invoice;
* billing invoices, marketing conversions and the customer money card take the tenant's
  currency instead of asserting EGP.

**One exception, in the other direction.** `billing.Invoice` is the PLATFORM's bill to
the tenant, and the only money that path computes is `ai_cost` — a USD figure (every AI
cap and per-minute price in `core/config.py` is USD). A tenant's trading currency is what
its *customers* pay it, which says nothing about what the tenant owes here. So that row is
stamped `core.currency.PLATFORM_BILLING_CURRENCY` (`"USD"`), and
`test_the_invoice_is_stamped_in_the_currency_its_cost_was_computed_in` pins it: §47's label
rule is not "use the tenant's currency", it is "the currency on a money row is the currency
its own numbers are in". The old `"EGP"` literal broke that; a naive `tenants.currency`
would have broken it differently.

`app/core/currency.py` is the single table of what a code means (its minor-unit exponent)
and whether it can be used here at all. It is stdlib-only data, so
`orders/money.py` — the pure rule set — can read it without gaining a session.

### 3. Storage stays `NUMERIC(14,2)`; `amount_minor` is derived

The 15-column `amount_minor BIGINT` migration in the audit's reading of §47 was rejected.
The two-decimal column is what every row already is, what Postgres sums without overflow
concerns, and what the reports read. Minor units are a **provider boundary**, so
`amount_minor(value, currency)` / `from_amount_minor(minor, currency)` convert there — and
both are scale-aware: the first draft rounded through the two-decimal quantum on the way
out, so a 19.995 IQD became 20000 fils. That is the exact class of bug the column was meant
to prevent, caught by a parametrized round-trip test.

A three-decimal currency (`IQD`, `BHD`, `JOD`, `KWD`, `OMR`) therefore cannot be a tenant's
currency: the columns would round every price, order and refund to a fifth of its real minor
unit, and the ledger would disagree with the provider on every line. `storage_refusal` says
so out loud instead of losing the difference silently. It remains usable at a provider
boundary, where the exponent is honored.

### 4. A total is computed

`orders/money.compute_totals(subtotal, discount, shipping, tax)` returns the five components
with `grand_total = subtotal - discount + shipping + tax`, each term quantized **before**
summing so the arithmetic is about the values the columns will hold. A negative component is
a `ValueError`; a discount past the order's worth is refused with the reason spelled out — a
negative total is a refund, and a refund is a money movement with a row of its own.

`POST /orders` accepts the three components, each defaulting to zero, and the response now
reports them. Absent fields keep the old behavior for every existing caller.

### 5. The ladder is read at checkout

`CatalogService.price_for(session, tenant_id, variant, currency=…, quantity=…)` picks the
highest applicable `min_quantity` tier **in the order's currency**, falling back to
`variant.price`. A tier quoted in another currency prices nothing, so a shop with a stray
USD tier cannot bill it by accident.

### 6. `app/core/money.py` is deleted, not rewired

It duplicated `orders/money.py` with a value object nothing used. Keeping two answers to
"what is an amount" is how one of them ends up wrong, so the file is gone and
`test_no_dead_core_modules.py` records that it was deleted rather than wired (its
`KNOWN_DEAD_CORE_MODULES` entry removed).

### 7. Setting the currency is an audited, mostly-once decision

`PUT /api/v1/tenants/{tenant_id}/currency`, gated `settings:write`, actor recorded with
before/after in `audit_logs`. An unknown code and a three-decimal code are 422s. Once the
tenant has an order in a currency other than the one requested the change is refused:
orders keep the currency they were sold in, and the aggregates that label a sum with one
currency (`customers/timeline.py` reports `min(currency)` beside the total) would silently
become a sum of two.

## Consequences

* The §47 matrix row is ✅ with its own test file; GAP M7's "no discount/shipping/tax
  engine", "currency hardcoded EGP" and "tiers write-only" clauses are closed.
* Cross-currency analytics is **not** implemented, and §47's rate-alongside-original rule is
  therefore unmet *by design*: with one currency per tenant there is no pair to report. If a
  tenant ever needs to sell in two, the honest sequence is an FX rate table plus per-currency
  grouping in the aggregates — not a relaxation of the refusal.
* The currency of a row is stamped at write time and never rewritten, so historical rows keep
  the currency the customer actually paid.
* `catalog/external/shopify_adapter.py:256` still defaults a synced order to `"EGP"`. It is
  left as found: `catalog/external/*` is dead inventory, and `shopify_adapter.py:173` calls
  an `upsert_from_external` that does not exist. When that sync is wired (GAP register,
  Wave 4), the external store's currency must be compared against the tenant's — not
  defaulted.
* The frontend does not send the money components yet, so a discount entered in the UI is
  still not what the API records — Wave 5.
