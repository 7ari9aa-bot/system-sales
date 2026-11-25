# Settings Registry Specification

> Source of truth: `backend/app/modules/settings/registry.py` — 127 settings.
> This document is **generated** from the code by `backend/scripts/dev/gen_registry_spec.py`.
> If the code and this table disagree, the code wins; run the script to regenerate.

## Setting count

The registry has **127 settings** (`len(REGISTRY)`). The source file contains
120 `_reg()` call sites — fewer than 127 because one `_reg()` sits inside a
`for` loop over `CAPABILITIES` (8 iterations), producing 8 setting definitions
from a single call. So: 119 non-loop calls + 1 loop call × 8 iterations =
127 definitions. There is no duplicate-key deduping: every `_reg()` call
produces a unique key, and `len(REGISTRY) == len(_DEFINITIONS) == 127`.

A review that reports **119** is counting only the non-loop `_reg()` call sites
— the calls that are visible as individual statements outside any `for` body.
The loop's single `_reg()` call site is not counted by a line-by-line review
because it appears once in the source but runs 8 times. To count accurately:
`len(REGISTRY)` is the source of truth; an AST walk that counts `_reg()` call
nodes (including those inside `For` bodies) gives 120; multiplying by loop
iterations and adding the non-loop count reproduces 127.

## Channel scope — open question

`Scope.CHANNEL` exists in the `Scope` enum and the inheritance chain
(`channel → tenant`), and `orders.allow_backorder` declares it as an allowed
scope. However, **per-channel settings within the same warehouse are not
fully implemented**:

* `require_scope_entity` redirects `Scope.CHANNEL` to `Scope.WAREHOUSE` for
  validation, meaning the `scope_id` is checked against the `warehouses`
  table — not a channels table (no `channels` table exists in the schema).
* This means the current behaviour does not support different values for
  individual channels served by the same warehouse; it only validates that
  the `scope_id` refers to a valid warehouse.

**Open product question:** Should `scope_id` for channel scope be the real
channel/conversation ID (requiring a new validation path against a channels
entity), or should channel-level overrides use a composite key (warehouse +
channel) stored in a `channel` field on the request? This needs a product
decision before per-channel differentiation can be implemented. Until then,
channel scope works as a warehouse-level override with channel semantics
documented but not individually addressable.

## How to read this table

| Column | Meaning |
|---|---|
| **Key** | Dotted identifier used in code and API |
| **Type** | `bool`, `number`, `string`, `enum`, `list` |
| **Default** | Factory value when no override exists at any scope |
| **Scopes** | Which scopes may override (first = lowest meaningful) |
| **Sens.** | `normal`, `sensitive`, or `secret` |
| **Apply** | `immediate`, `validated`, or `approval_required` |
| **Min / Max** | Numeric bounds (— = unbounded) |
| **Enforced** | ✅ if a service actually reads this key (in `ENFORCED_KEYS`) |
| **Allowed** | For `enum` types: the set of valid values (— = n/a) |
| **Segments** | Business types this applies to (`all` = every segment) |

All overrides are stored in the `tenant_settings` table (tenant-scoped, RLS-protected). History is in `tenant_settings_history` (append-only). Approval flows use `setting_change_requests`.

---

## Business & Shop Profile (23 settings)

| Key | Type | Default | Scopes | Sens. | Apply | Min | Max | Enforced | Allowed | Segments |
|---|---|---|---|---|---|---|---|---|---|---|
| `business.legal_name` | string | `""` | TENANT | normal | validated | — | — | ✅ | — | all |
| `business.trade_name` | string | `""` | TENANT | normal | validated | — | — | ✅ | — | all |
| `business.tax_id` | string | `""` | TENANT | normal | validated | — | — | ✅ | — | all |
| `business.commercial_register` | string | `""` | TENANT | normal | validated | — | — | ✅ | — | all |
| `business.phone` | string | `""` | TENANT, BRANCH | normal | validated | — | — | ✅ | — | all |
| `business.email` | string | `""` | TENANT, BRANCH | normal | validated | — | — | ✅ | — | all |
| `business.website` | string | `""` | TENANT | normal | validated | — | — | ✅ | — | all |
| `business.address.line1` | string | `""` | TENANT, BRANCH | normal | validated | — | — | ✅ | — | all |
| `business.address.city` | string | `""` | TENANT, BRANCH | normal | validated | — | — | ✅ | — | all |
| `business.address.postal_code` | string | `""` | TENANT, BRANCH | normal | validated | — | — | ✅ | — | all |
| `business.type` | enum | `retail` | TENANT | normal | validated | — | — | ✅ | retail, fnb, services, wholesale | all |
| `business.vertical` | enum | `general` | TENANT, WORKSPACE | normal | validated | — | — | ✅ | general, apparel, pharmacy, restaurant | all |
| `business.setup_state` | enum | `done` | TENANT | normal | validated | — | — | ✅ | done, not_started, skipped | all |
| `reports.managers_see_profit` | bool | true | TENANT | normal | validated | — | — | ✅ | — | all |
| `business.terms_accepted_at` | string | `""` | TENANT | normal | validated | — | — | ✅ | — | all |
| `capability.variant_matrix` | bool | false | TENANT, WORKSPACE | normal | validated | — | — | — | — | all |
| `capability.lot_expiry` | bool | false | TENANT, WORKSPACE | normal | validated | — | — | — | — | all |
| `capability.fefo_picking` | bool | false | TENANT, WORKSPACE | normal | validated | — | — | — | — | all |
| `capability.prescription_required` | bool | false | TENANT, WORKSPACE | normal | validated | — | — | — | — | all |
| `capability.modifiers` | bool | false | TENANT, WORKSPACE | normal | validated | — | — | — | — | all |
| `capability.recipe_bom` | bool | false | TENANT, WORKSPACE | normal | validated | — | — | — | — | all |
| `capability.serial_tracking` | bool | false | TENANT, WORKSPACE | normal | validated | — | — | — | — | all |
| `capability.weight_scale` | bool | false | TENANT, WORKSPACE | normal | validated | — | — | — | — | all |

## POS / Cashier (16 settings)

| Key | Type | Default | Scopes | Sens. | Apply | Min | Max | Enforced | Allowed | Segments |
|---|---|---|---|---|---|---|---|---|---|---|
| `pos.require_customer` | bool | false | TENANT, BRANCH, POS_PROFILE | normal | validated | — | — | ✅ | — | all |
| `pos.cash_movement_limit` | number | 0 | TENANT, BRANCH | normal | validated | 0 | 1000000 | ✅ | — | all |
| `pos.max_discount_pct` | number | null | TENANT, BRANCH, POS_PROFILE | normal | validated | 0 | 100 | ✅ | — | all |
| `pos.allow_hold_cart` | bool | true | TENANT, POS_PROFILE | normal | validated | — | — | ✅ | — | all |
| `pos.return_max_days` | number | 30 | TENANT, BRANCH | normal | validated | 0 | 365 | ✅ | — | all |
| `pos.exchange_max_days` | number | 0 | TENANT, BRANCH | normal | validated | 0 | 365 | ✅ | — | all |
| `pos.return_restock_default` | bool | true | TENANT, BRANCH | normal | validated | — | — | ✅ | — | all |
| `pos.refund_cash_only` | bool | false | TENANT, BRANCH | normal | validated | — | — | ✅ | — | all |
| `pos.return_reasons` | list | `[size, defect, changed_mind, wrong_item]` | TENANT | normal | validated | — | — | ✅ | — | all |
| `pos.take_payments` | bool | false | TENANT, BRANCH, POS_PROFILE | normal | validated | — | — | ✅ | — | retail |
| `pos.allow_record_only_sales` | bool | false | TENANT, BRANCH, POS_PROFILE | normal | validated | — | — | ✅ | — | retail |
| `pos.settle_payment_methods` | bool | false | TENANT, BRANCH, POS_PROFILE | normal | validated | — | — | ✅ | — | retail |
| `pos.allow_sale_on_account` | bool | false | TENANT, BRANCH, POS_PROFILE | normal | validated | — | — | ✅ | — | retail |
| `pos.reference_required_methods` | list | `[card, bank_transfer, wallet]` | TENANT, BRANCH, POS_PROFILE | normal | validated | — | — | ✅ | — | retail |
| `pos.variance_reason_required` | bool | true | TENANT, BRANCH, POS_PROFILE | normal | validated | — | — | ✅ | — | retail |
| `pos.variance_approval_threshold` | number | 0 | TENANT, BRANCH, POS_PROFILE | normal | validated | 0 | 1000000 | ✅ | — | retail |

## E-Invoice / ETA (15 settings)

| Key | Type | Default | Scopes | Sens. | Apply | Min | Max | Enforced | Allowed | Segments |
|---|---|---|---|---|---|---|---|---|---|---|
| `einvoice.eta_enabled` | bool | false | TENANT | normal | validated | — | — | ✅ | — | all |
| `einvoice.settings_confirmed` | bool | false | TENANT | normal | validated | — | — | ✅ | — | all |
| `einvoice.prices_include_vat` | bool | true | TENANT | normal | validated | — | — | ✅ | — | all |
| `einvoice.default_payment_method` | enum | `C` | TENANT | normal | validated | — | — | ✅ | C, V, CC, VC, VO, PR, GC, P, O | all |
| `einvoice.split_payment_rule` | enum | `largest` | TENANT | normal | validated | — | — | ✅ | largest, cash_first | all |
| `einvoice.vat_category` | enum | `taxable` | TENANT | normal | validated | — | — | ✅ | taxable, exempt, non_taxable | all |
| `einvoice.unit_code` | string | `EA` | TENANT | normal | validated | — | — | ✅ | — | all |
| `einvoice.delivery_mode` | enum | `FC` | TENANT | normal | validated | — | — | ✅ | FC, TO, TC | all |
| `einvoice.warn_hours_before_deadline` | number | 24 | TENANT | normal | validated | 1 | 96 | ✅ | — | all |
| `einvoice.branch_code` | string | `""` | TENANT | normal | validated | — | — | ✅ | — | all |
| `einvoice.activity_code` | string | `""` | TENANT | normal | validated | — | — | ✅ | — | all |
| `einvoice.branch_governate` | string | `""` | TENANT | normal | validated | — | — | ✅ | — | all |
| `einvoice.branch_region_city` | string | `""` | TENANT | normal | validated | — | — | ✅ | — | all |
| `einvoice.branch_street` | string | `""` | TENANT | normal | validated | — | — | ✅ | — | all |
| `einvoice.branch_building_number` | string | `""` | TENANT | normal | validated | — | — | ✅ | — | all |

## Imports (1 settings)

| Key | Type | Default | Scopes | Sens. | Apply | Min | Max | Enforced | Allowed | Segments |
|---|---|---|---|---|---|---|---|---|---|---|
| `imports.legacy_csv_endpoint` | bool | false | TENANT | normal | validated | — | — | ✅ | — | all |

## Inventory (12 settings)

| Key | Type | Default | Scopes | Sens. | Apply | Min | Max | Enforced | Allowed | Segments |
|---|---|---|---|---|---|---|---|---|---|---|
| `inventory.auto_reserve` | bool | true | TENANT | normal | validated | — | — | ✅ | — | all |
| `inventory.expiry_alert_days` | number | 30 | TENANT | normal | validated | 1 | 730 | ✅ | — | all |
| `inventory.dead_stock_days` | number | 60 | TENANT | normal | validated | 7 | 730 | ✅ | — | all |
| `inventory.reserve_ttl_minutes` | number | 15 | TENANT | normal | validated | 5 | 43200 | ✅ | — | all |
| `inventory.fifo_enabled` | bool | true | TENANT | normal | validated | — | — | ✅ | — | retail, fnb, wholesale |
| `inventory.track_locations` | bool | false | TENANT, WAREHOUSE | normal | validated | — | — | ✅ | — | retail, fnb, wholesale |
| `inventory.show_warehouse_transfers` | bool | true | TENANT | normal | validated | — | — | ✅ | — | all |
| `inventory.show_channel_allocation` | bool | true | TENANT | normal | validated | — | — | ✅ | — | all |
| `inventory.show_units_of_measure` | bool | true | TENANT | normal | validated | — | — | ✅ | — | all |
| `inventory.quality_check_on_receipt` | bool | false | TENANT, WAREHOUSE | normal | validated | — | — | ✅ | — | retail, fnb, wholesale |
| `inventory.stocktake_approval_required` | bool | true | TENANT, WAREHOUSE | normal | validated | — | — | ✅ | — | retail, fnb, wholesale |
| `inventory.safety_stock_default` | number | 0 | TENANT, WAREHOUSE | normal | validated | 0 | 1000000 | ✅ | — | retail, fnb, wholesale |

## Purchasing (5 settings)

| Key | Type | Default | Scopes | Sens. | Apply | Min | Max | Enforced | Allowed | Segments |
|---|---|---|---|---|---|---|---|---|---|---|
| `purchasing.approval_required` | bool | false | TENANT, BRANCH | normal | validated | — | — | ✅ | — | all |
| `purchasing.approval_threshold` | number | 0 | TENANT, BRANCH | normal | validated | 0 | — | ✅ | — | all |
| `purchasing.allow_partial_receipt` | bool | true | TENANT | normal | validated | — | — | ✅ | — | all |
| `purchasing.allow_over_receipt` | bool | false | TENANT | normal | validated | — | — | ✅ | — | retail, fnb, wholesale |
| `purchasing.centralized` | bool | false | TENANT | normal | validated | — | — | ✅ | — | all |

## Orders (3 settings)

| Key | Type | Default | Scopes | Sens. | Apply | Min | Max | Enforced | Allowed | Segments |
|---|---|---|---|---|---|---|---|---|---|---|
| `orders.reserve_on` | enum | `create` | TENANT | normal | validated | — | — | ✅ | create, confirm | all |
| `orders.allow_backorder` | bool | false | TENANT, CHANNEL | normal | validated | — | — | ✅ | — | retail, fnb, wholesale |
| `orders.deduct_stock_on` | enum | `confirm` | TENANT | normal | validated | — | — | ✅ | confirm, ship, deliver | all |

## Print & Barcode (8 settings)

| Key | Type | Default | Scopes | Sens. | Apply | Min | Max | Enforced | Allowed | Segments |
|---|---|---|---|---|---|---|---|---|---|---|
| `print.paper_width` | enum | `80mm` | TENANT, REGISTER | normal | validated | — | — | ✅ | 58mm, 80mm, a4 | all |
| `print.show_logo` | bool | true | TENANT, REGISTER | normal | validated | — | — | ✅ | — | all |
| `print.header_text` | string | `""` | TENANT, BRANCH | normal | validated | — | — | ✅ | — | all |
| `print.footer_text` | string | `""` | TENANT, BRANCH | normal | validated | — | — | ✅ | — | all |
| `print.copies` | number | 1 | TENANT, REGISTER | normal | validated | 1 | 5 | ✅ | — | all |
| `print.show_tax_detail` | bool | true | TENANT | normal | validated | — | — | ✅ | — | all |
| `print.barcode_format` | enum | `code128` | TENANT | normal | validated | — | — | ✅ | code128, ean13, upc_a, qr | all |
| `print.invoice_prefix` | string | `INV` | TENANT, BRANCH | normal | validated | — | — | ✅ | — | all |

## Notifications (7 settings)

| Key | Type | Default | Scopes | Sens. | Apply | Min | Max | Enforced | Allowed | Segments |
|---|---|---|---|---|---|---|---|---|---|---|
| `notifications.low_stock_alert` | bool | true | TENANT, WAREHOUSE | normal | validated | — | — | ✅ | — | all |
| `notifications.order_received` | bool | true | TENANT, USER | normal | validated | — | — | ✅ | — | all |
| `notifications.quiet_hours_start` | string | `""` | TENANT | normal | validated | — | — | ✅ | — | all |
| `notifications.quiet_hours_end` | string | `""` | TENANT | normal | validated | — | — | ✅ | — | all |
| `notifications.digest_mode` | enum | `realtime` | TENANT | normal | validated | — | — | ✅ | realtime, hourly, daily | all |
| `notifications.email_enabled` | bool | false | TENANT | normal | validated | — | — | ✅ | — | all |
| `notifications.push_enabled` | bool | true | TENANT | normal | validated | — | — | ✅ | — | all |

## Customer AI Agent (8 settings)

| Key | Type | Default | Scopes | Sens. | Apply | Min | Max | Enforced | Allowed | Segments |
|---|---|---|---|---|---|---|---|---|---|---|
| `customer_agent.enabled` | bool | false | TENANT | normal | validated | — | — | ✅ | — | all |
| `customer_agent.dialect` | enum | `egyptian` | TENANT | normal | validated | — | — | ✅ | msa, egyptian, gulf, levantine | all |
| `customer_agent.formality` | enum | `friendly` | TENANT | normal | validated | — | — | ✅ | formal, friendly, casual | all |
| `customer_agent.response_language` | enum | `ar` | TENANT | normal | validated | — | — | ✅ | ar, en, auto | all |
| `customer_agent.handoff_enabled` | bool | true | TENANT | normal | validated | — | — | ✅ | — | all |
| `customer_agent.max_turns_before_handoff` | number | 5 | TENANT | normal | validated | 1 | 50 | ✅ | — | all |
| `customer_agent.show_prices` | bool | true | TENANT | normal | validated | — | — | ✅ | — | all |
| `customer_agent.show_stock` | bool | true | TENANT | normal | validated | — | — | ✅ | — | all |

## Analytics Agent (4 settings)

| Key | Type | Default | Scopes | Sens. | Apply | Min | Max | Enforced | Allowed | Segments |
|---|---|---|---|---|---|---|---|---|---|---|
| `analytics_agent.enabled` | bool | false | TENANT | normal | validated | — | — | ✅ | — | all |
| `analytics_agent.default_period` | enum | `30d` | TENANT | normal | validated | — | — | ✅ | 7d, 30d, 90d, ytd, all | all |
| `analytics_agent.include_branches` | list | `[]` | TENANT | normal | validated | — | — | ✅ | — | all |
| `analytics_agent.min_confidence` | number | 0.7 | TENANT | normal | validated | 0.0 | 1.0 | ✅ | — | all |

## Organization (5 settings)

| Key | Type | Default | Scopes | Sens. | Apply | Min | Max | Enforced | Allowed | Segments |
|---|---|---|---|---|---|---|---|---|---|---|
| `organization.fiscal_year_start_month` | number | 1 | TENANT | normal | validated | 1 | 12 | ✅ | — | all |
| `organization.multi_branch` | bool | false | TENANT | normal | validated | — | — | ✅ | — | all |
| `organization.max_branches` | number | 0 | TENANT | normal | validated | 0 | 1000 | ✅ | — | all |
| `organization.default_language` | enum | `ar` | TENANT | normal | validated | — | — | ✅ | ar, en | all |
| `organization.brand_color` | string | `""` | TENANT | normal | validated | — | — | ✅ | — | all |

## Branch (4 settings)

| Key | Type | Default | Scopes | Sens. | Apply | Min | Max | Enforced | Allowed | Segments |
|---|---|---|---|---|---|---|---|---|---|---|
| `branch.auto_close_shift` | bool | false | TENANT, BRANCH | normal | validated | — | — | ✅ | — | all |
| `branch.shift_end_time` | string | `23:59` | TENANT, BRANCH | normal | validated | — | — | ✅ | — | all |
| `branch.notify_manager_on_variance` | bool | true | TENANT, BRANCH | normal | validated | — | — | ✅ | — | all |
| `branch.allow_independent_purchasing` | bool | false | TENANT, BRANCH | normal | validated | — | — | ✅ | — | all |

## Catalog (5 settings)

| Key | Type | Default | Scopes | Sens. | Apply | Min | Max | Enforced | Allowed | Segments |
|---|---|---|---|---|---|---|---|---|---|---|
| `catalog.sku_format` | string | `{category}-{number}` | TENANT | normal | validated | — | — | ✅ | — | all |
| `catalog.barcode_auto_generate` | bool | true | TENANT | normal | validated | — | — | ✅ | — | all |
| `catalog.default_tax_rate` | number | 0 | TENANT | normal | validated | 0 | 100 | ✅ | — | all |
| `catalog.show_out_of_stock` | bool | true | TENANT | normal | validated | — | — | ✅ | — | all |
| `catalog.max_variants_per_product` | number | 100 | TENANT | normal | validated | 1 | 10000 | ✅ | — | all |

## Team (4 settings)

| Key | Type | Default | Scopes | Sens. | Apply | Min | Max | Enforced | Allowed | Segments |
|---|---|---|---|---|---|---|---|---|---|---|
| `team.default_role` | enum | `cashier` | TENANT | normal | validated | — | — | ✅ | cashier, manager, admin | all |
| `team.require_2fa` | bool | false | TENANT | sensitive | validated | — | — | ✅ | — | all |
| `team.session_timeout_minutes` | number | 0 | TENANT | normal | validated | 0 | 10080 | ✅ | — | all |
| `team.allow_member_invites` | bool | true | TENANT | normal | validated | — | — | ✅ | — | all |

## Security (4 settings)

| Key | Type | Default | Scopes | Sens. | Apply | Min | Max | Enforced | Allowed | Segments |
|---|---|---|---|---|---|---|---|---|---|---|
| `security.require_strong_passwords` | bool | true | TENANT | sensitive | validated | — | — | ✅ | — | all |
| `security.api_key_rotation_days` | number | 90 | TENANT | sensitive | validated | 0 | 365 | ✅ | — | all |
| `security.audit_retention_days` | number | 365 | TENANT | normal | validated | 0 | 2555 | ✅ | — | all |
| `security.ip_allowlist` | list | `[]` | TENANT | sensitive | validated | — | — | ✅ | — | all |

## Billing (3 settings)

| Key | Type | Default | Scopes | Sens. | Apply | Min | Max | Enforced | Allowed | Segments |
|---|---|---|---|---|---|---|---|---|---|---|
| `billing.auto_renew` | bool | true | TENANT | normal | validated | — | — | ✅ | — | all |
| `billing.currency` | enum | `EGP` | TENANT | normal | validated | — | — | ✅ | EGP, USD, SAR, AED | all |
| `billing.notify_before_renewal_days` | number | 7 | TENANT | normal | validated | 0 | 30 | ✅ | — | all |

---

## Scope inheritance chain

```
TENANT → WORKSPACE → BRANCH → WAREHOUSE → POS_PROFILE → REGISTER
TENANT → CHANNEL
TENANT → USER
```

## Capabilities (owner switches)

Each capability is a `capability.<name>` setting (domain `business`, type `bool`). The vertical picks the starting answer; the owner's override wins.

