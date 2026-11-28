# pricing

PRICING domain — which price applies, and what comes off it (§07 Sales & pricing).

The resolver is the point of this module: a product can have its own price history, several named
price lists and a set of running offers, and the till still has to answer one number. Everything
funnels through `PricingService.resolve` (one price) and `PricingService.quote` (a basket), and
both read their policy from the settings engine instead of hard-coding a rule.

## Where things are

- `router.py` — the HTTP surface
- `service.py` — resolution, tiers, discounts, the quote
- `models.py` — `price_lists`, `price_list_items`, `discount_rules`

## HTTP

9 endpoints. Route prefixes: `/price-lists`, `/discount-rules`, `/quote`.
Registered in `app/main.py`.

## Tables

- `price_lists`
- `price_list_items`
- `discount_rules`

## Settings this module reads

Home page for all seven is section 07, page `pricing`
(`docs/settings/center-map.md`):

- `pricing.price_lists_enabled` — off means the product's own price stands; the lists stay in the
  database untouched, so switching back on restores them.
- `pricing.quantity_tiers_enabled`
- `pricing.stacked_discounts` — off means the single best rule wins.
- `pricing.max_order_discount_pct` — ceiling on the whole quote; a rule's own `max_discount`
  caps that rule.
- `pricing.auto_apply_offers`
- `pricing.allow_price_below_cost`
- `pricing.round_prices_to` — applied to the final unit price, never an intermediate step, so the
  rounding cannot compound across tiers.

## Depends on

Other modules imported from here: `catalog` (variant rows for a resolution), `identity` (route
deps), `settings` (the policy above).
Import boundaries between modules are ratcheted by `tests/test_module_boundaries.py`; do not add
new cross-module imports without a reason, and never raise that baseline yourself.

## Rules for working here

1. A discount is applied to a QUOTE, never stored on a rule: the same rule on a different basket
   gives a different number, and storing the number makes the rule lie the moment anything
   changes.
2. Money is `Decimal` end to end (ADR-001); nothing here goes through `float()`.
3. A tie between two lists is broken in the customer's favour, never by insertion order.
4. Clamp rather than refuse: a smaller discount than promised is a smaller problem than a sale
   that cannot be completed.
