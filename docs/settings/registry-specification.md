# Settings Registry Specification

> Source of truth: `backend/app/modules/settings/registry.py` — 120 settings.
> This document is generated from the code. If the code and this table disagree, the code wins.

## How to read this table

| Column | Meaning |
|---|---|
| **Key** | Dotted identifier used in code and API |
| **Type** | `bool`, `number`, `string`, `enum`, `list` |
| **Default** | Factory value when no override exists at any scope |
| **Scopes** | Which scopes may override this setting (first = lowest meaningful) |
| **Sensitivity** | `normal`, `sensitive`, or `secret` |
| **Apply mode** | `immediate`, `validated`, or `approval_required` |
| **Min / Max** | Numeric bounds (— = unbounded) |
| **Enforced** | Whether a service actually reads this key (in `ENFORCED_KEYS`) |
| **Allowed values** | For `enum` types: the set of valid values |
| **Segments** | Business types this applies to (`all` = every segment) |
| **Storage** | Where overrides live (always `tenant_settings` unless noted) |

All overrides are stored in the `tenant_settings` table (tenant-scoped, RLS-protected).
History is in `tenant_settings_history` (append-only). Approval flows use `setting_change_requests`.

---

## Business & Shop Profile (15 settings)

| Key | Type | Default | Scopes | Sensitivity | Apply | Min | Max | Enforced | Allowed | Segments |
|---|---|---|---|---|---|---|---|---|---|---|
| `business.legal_name` | string | `""` | TENANT | normal | immediate | — | — | ✅ | — | all |
| `business.trade_name` | string | `""` | TENANT | normal | immediate | — | — | ✅ | — | all |
| `business.tax_id` | string | `""` | TENANT | normal | immediate | — | — | ✅ | — | all |
| `business.commercial_register` | string | `""` | TENANT | normal | immediate | — | — | ✅ | — | all |
| `business.phone` | string | `""` | TENANT, BRANCH | normal | immediate | — | — | ✅ | — | all |
| `business.email` | string | `""` | TENANT, BRANCH | normal | immediate | — | — | ✅ | — | all |
| `business.website` | string | `""` | TENANT | normal | immediate | — | — | ✅ | — | all |
| `business.address.line1` | string | `""` | TENANT, BRANCH | normal | immediate | — | — | ✅ | — | all |
| `business.address.city` | string | `""` | TENANT, BRANCH | normal | immediate | — | — | ✅ | — | all |
| `business.address.postal_code` | string | `""` | TENANT, BRANCH | normal | immediate | — | — | ✅ | — | all |
| `business.type` | enum | `retail` | TENANT | normal | immediate | — | — | ✅ | retail, fnb, services, wholesale | all |
| `business.vertical` | enum | `DEFAULT_VERTICAL` | TENANT, WORKSPACE | normal | immediate | — | — | ✅ | (from VERTICALS) | all |
| `business.setup_state` | enum | `done` | TENANT | normal | immediate | — | — | ✅ | pending, done | all |
| `reports.managers_see_profit` | bool | `True` | TENANT | normal | immediate | — | — | ✅ | — | all |
| `business.terms_accepted_at` | string | `""` | TENANT | normal | immediate | — | — | ✅ | — | all |

## POS / Cashier (16 settings)

| Key | Type | Default | Scopes | Sensitivity | Apply | Min | Max | Enforced | Allowed | Segments |
|---|---|---|---|---|---|---|---|---|---|---|
| `pos.require_customer` | bool | `False` | TENANT, BRANCH, POS_PROFILE | normal | immediate | — | — | ✅ | — | all |
| `pos.cash_movement_limit` | number | `0` | TENANT, BRANCH | normal | immediate | 0 | 1,000,000 | ✅ | — | all |
| `pos.max_discount_pct` | number | `None` | TENANT, BRANCH, POS_PROFILE | normal | immediate | 0 | 100 | ✅ | — | all |
| `pos.allow_hold_cart` | bool | `True` | TENANT, POS_PROFILE | normal | immediate | — | — | ✅ | — | all |
| `pos.return_max_days` | number | `30` | TENANT, BRANCH | normal | immediate | 0 | 365 | ✅ | — | all |
| `pos.exchange_max_days` | number | `0` | TENANT, BRANCH | normal | immediate | 0 | 365 | ✅ | — | all |
| `pos.return_restock_default` | bool | `True` | TENANT, BRANCH | normal | immediate | — | — | ✅ | — | all |
| `pos.refund_cash_only` | bool | `False` | TENANT, BRANCH | normal | immediate | — | — | ✅ | — | all |
| `pos.return_reasons` | list | `["size","defect","changed_mind","wrong_item"]` | TENANT | normal | immediate | — | — | ✅ | — | all |
| `pos.take_payments` | bool | `False` | TENANT, BRANCH, POS_PROFILE | normal | immediate | — | — | ✅ | — | retail |
| `pos.allow_record_only_sales` | bool | `False` | TENANT, BRANCH, POS_PROFILE | normal | immediate | — | — | ✅ | — | retail |
| `pos.settle_payment_methods` | bool | `False` | TENANT, BRANCH, POS_PROFILE | normal | immediate | — | — | ✅ | — | retail |
| `pos.allow_sale_on_account` | bool | `False` | TENANT, BRANCH, POS_PROFILE | normal | immediate | — | — | ✅ | — | retail |
| `pos.reference_required_methods` | list | `["card","bank_transfer","wallet"]` | TENANT, BRANCH, POS_PROFILE | normal | immediate | — | — | ✅ | — | retail |
| `pos.variance_reason_required` | bool | `True` | TENANT, BRANCH, POS_PROFILE | normal | immediate | — | — | ✅ | — | retail |
| `pos.variance_approval_threshold` | number | `0` | TENANT, BRANCH, POS_PROFILE | normal | immediate | 0 | 1,000,000 | ✅ | — | retail |

## E-Invoice / ETA (14 settings)

| Key | Type | Default | Scopes | Sensitivity | Apply | Min | Max | Enforced | Allowed | Segments |
|---|---|---|---|---|---|---|---|---|---|---|
| `einvoice.eta_enabled` | bool | `False` | TENANT | normal | immediate | — | — | ✅ | — | all |
| `einvoice.settings_confirmed` | bool | `False` | TENANT | normal | immediate | — | — | ✅ | — | all |
| `einvoice.prices_include_vat` | bool | `True` | TENANT | normal | immediate | — | — | ✅ | — | all |
| `einvoice.default_payment_method` | enum | `C` | TENANT | normal | immediate | — | — | ✅ | C, P, O | all |
| `einvoice.split_payment_rule` | enum | `largest` | TENANT | normal | immediate | — | — | ✅ | largest, cash_first | all |
| `einvoice.vat_category` | enum | `taxable` | TENANT | normal | immediate | — | — | ✅ | taxable, exempt, zero | all |
| `einvoice.unit_code` | string | `EA` | TENANT | normal | immediate | — | — | ✅ | — | all |
| `einvoice.delivery_mode` | enum | `FC` | TENANT | normal | immediate | — | — | ✅ | FC, PP | all |
| `einvoice.warn_hours_before_deadline` | number | `24` | TENANT | normal | immediate | 1 | 96 | ✅ | — | all |
| `einvoice.branch_code` | string | `""` | TENANT | normal | immediate | — | — | ✅ | — | all |
| `einvoice.activity_code` | string | `""` | TENANT | normal | immediate | — | — | ✅ | — | all |
| `einvoice.branch_governate` | string | `""` | TENANT | normal | immediate | — | — | ✅ | — | all |
| `einvoice.branch_region_city` | string | `""` | TENANT | normal | immediate | — | — | ✅ | — | all |
| `einvoice.branch_street` | string | `""` | TENANT | normal | immediate | — | — | ✅ | — | all |
| `einvoice.branch_building_number` | string | `""` | TENANT | normal | immediate | — | — | ✅ | — | all |

## Print & Barcode (9 settings)

| Key | Type | Default | Scopes | Sensitivity | Apply | Min | Max | Enforced | Allowed | Segments |
|---|---|---|---|---|---|---|---|---|---|---|
| `print.paper_width` | enum | `80mm` | TENANT, REGISTER | normal | immediate | — | — | ✅ | 80mm, 58mm | all |
| `print.show_logo` | bool | `True` | TENANT, REGISTER | normal | immediate | — | — | ✅ | — | all |
| `print.header_text` | string | `""` | TENANT, BRANCH | normal | immediate | — | — | ✅ | — | all |
| `print.footer_text` | string | `""` | TENANT, BRANCH | normal | immediate | — | — | ✅ | — | all |
| `print.copies` | number | `1` | TENANT, REGISTER | normal | immediate | 1 | 5 | ✅ | — | all |
| `print.show_tax_detail` | bool | `True` | TENANT | normal | immediate | — | — | ✅ | — | all |
| `print.barcode_format` | enum | `code128` | TENANT | normal | immediate | — | — | ✅ | code128, ean13, ean8 | all |
| `print.invoice_prefix` | string | `INV` | TENANT, BRANCH | normal | immediate | — | — | ✅ | — | all |

## Inventory (12 settings)

| Key | Type | Default | Scopes | Sensitivity | Apply | Min | Max | Enforced | Allowed | Segments |
|---|---|---|---|---|---|---|---|---|---|---|
| `inventory.auto_reserve` | bool | `True` | TENANT | normal | immediate | — | — | ✅ | — | all |
| `inventory.expiry_alert_days` | number | `30` | TENANT | normal | immediate | 1 | 730 | ✅ | — | all |
| `inventory.dead_stock_days` | number | `60` | TENANT | normal | immediate | 7 | 730 | ✅ | — | all |
| `inventory.reserve_ttl_minutes` | number | `15` | TENANT | normal | immediate | 5 | 43,200 | ✅ | — | all |
| `inventory.fifo_enabled` | bool | `True` | TENANT | normal | immediate | — | — | ✅ | — | retail, fnb, wholesale |
| `inventory.track_locations` | bool | `False` | TENANT, WAREHOUSE | normal | immediate | — | — | ✅ | — | retail, fnb, wholesale |
| `inventory.show_warehouse_transfers` | bool | `True` | TENANT | normal | immediate | — | — | ✅ | — | all |
| `inventory.show_channel_allocation` | bool | `True` | TENANT | normal | immediate | — | — | ✅ | — | all |
| `inventory.show_units_of_measure` | bool | `True` | TENANT | normal | immediate | — | — | ✅ | — | all |
| `inventory.quality_check_on_receipt` | bool | `False` | TENANT, WAREHOUSE | normal | immediate | — | — | ✅ | — | retail, fnb, wholesale |
| `inventory.stocktake_approval_required` | bool | `True` | TENANT, WAREHOUSE | normal | immediate | — | — | ✅ | — | retail, fnb, wholesale |
| `inventory.safety_stock_default` | number | `0` | TENANT, WAREHOUSE | normal | immediate | 0 | 1,000,000 | ✅ | — | retail, fnb, wholesale |

## Purchasing (6 settings)

| Key | Type | Default | Scopes | Sensitivity | Apply | Min | Max | Enforced | Allowed | Segments |
|---|---|---|---|---|---|---|---|---|---|---|
| `purchasing.approval_required` | bool | `False` | TENANT, BRANCH | normal | immediate | — | — | ✅ | — | all |
| `purchasing.approval_threshold` | number | `0` | TENANT, BRANCH | normal | immediate | 0 | — | ✅ | — | all |
| `purchasing.allow_partial_receipt` | bool | `True` | TENANT | normal | immediate | — | — | ✅ | — | all |
| `purchasing.allow_over_receipt` | bool | `False` | TENANT | normal | immediate | — | — | ✅ | — | retail, fnb, wholesale |
| `purchasing.centralized` | bool | `False` | TENANT | normal | immediate | — | — | ✅ | — | all |

## Orders (3 settings)

| Key | Type | Default | Scopes | Sensitivity | Apply | Min | Max | Enforced | Allowed | Segments |
|---|---|---|---|---|---|---|---|---|---|---|
| `orders.reserve_on` | enum | `create` | TENANT | normal | immediate | — | — | ✅ | create, checkout | all |
| `orders.allow_backorder` | bool | `False` | TENANT, CHANNEL | normal | immediate | — | — | ✅ | — | retail, fnb, wholesale |
| `orders.deduct_stock_on` | enum | `confirm` | TENANT | normal | immediate | — | — | ✅ | confirm, ship, deliver | all |

## Imports (1 setting)

| Key | Type | Default | Scopes | Sensitivity | Apply | Min | Max | Enforced | Allowed | Segments |
|---|---|---|---|---|---|---|---|---|---|---|
| `imports.legacy_csv_endpoint` | bool | `False` | TENANT | normal | immediate | — | — | ✅ | — | all |

## Customer AI Agent (9 settings)

| Key | Type | Default | Scopes | Sensitivity | Apply | Min | Max | Enforced | Allowed | Segments |
|---|---|---|---|---|---|---|---|---|---|---|
| `customer_agent.enabled` | bool | `False` | TENANT | normal | immediate | — | — | ✅ | — | all |
| `customer_agent.dialect` | enum | `egyptian` | TENANT | normal | immediate | — | — | ✅ | egyptian, gulf, levantine, maghrebi, msa | all |
| `customer_agent.formality` | enum | `friendly` | TENANT | normal | immediate | — | — | ✅ | friendly, formal, neutral | all |
| `customer_agent.response_language` | enum | `ar` | TENANT | normal | immediate | — | — | ✅ | ar, en | all |
| `customer_agent.handoff_enabled` | bool | `True` | TENANT | normal | immediate | — | — | ✅ | — | all |
| `customer_agent.max_turns_before_handoff` | number | `5` | TENANT | normal | immediate | 1 | 50 | ✅ | — | all |
| `customer_agent.show_prices` | bool | `True` | TENANT | normal | immediate | — | — | ✅ | — | all |
| `customer_agent.show_stock` | bool | `True` | TENANT | normal | immediate | — | — | ✅ | — | all |

## Analytics Agent (4 settings)

| Key | Type | Default | Scopes | Sensitivity | Apply | Min | Max | Enforced | Allowed | Segments |
|---|---|---|---|---|---|---|---|---|---|---|
| `analytics_agent.enabled` | bool | `False` | TENANT | normal | immediate | — | — | ✅ | — | all |
| `analytics_agent.default_period` | enum | `30d` | TENANT | normal | immediate | — | — | ✅ | 7d, 30d, 90d, ytd, all | all |
| `analytics_agent.include_branches` | list | `[]` | TENANT | normal | immediate | — | — | ✅ | — | all |
| `analytics_agent.min_confidence` | number | `0.7` | TENANT | normal | immediate | 0.0 | 1.0 | ✅ | — | all |

## Organization (5 settings)

| Key | Type | Default | Scopes | Sensitivity | Apply | Min | Max | Enforced | Allowed | Segments |
|---|---|---|---|---|---|---|---|---|---|---|
| `organization.fiscal_year_start_month` | number | `1` | TENANT | normal | immediate | 1 | 12 | ✅ | — | all |
| `organization.multi_branch` | bool | `False` | TENANT | normal | immediate | — | — | ✅ | — | all |
| `organization.max_branches` | number | `0` | TENANT | normal | immediate | 0 | 1000 | ✅ | — | all |
| `organization.default_language` | enum | `ar` | TENANT | normal | immediate | — | — | ✅ | ar, en | all |
| `organization.brand_color` | string | `""` | TENANT | normal | immediate | — | — | ✅ | — | all |

## Branch (4 settings)

| Key | Type | Default | Scopes | Sensitivity | Apply | Min | Max | Enforced | Allowed | Segments |
|---|---|---|---|---|---|---|---|---|---|---|
| `branch.auto_close_shift` | bool | `False` | TENANT, BRANCH | normal | immediate | — | — | ✅ | — | all |
| `branch.shift_end_time` | string | `23:59` | TENANT, BRANCH | normal | immediate | — | — | ✅ | — | all |
| `branch.notify_manager_on_variance` | bool | `True` | TENANT, BRANCH | normal | immediate | — | — | ✅ | — | all |
| `branch.allow_independent_purchasing` | bool | `False` | TENANT, BRANCH | normal | immediate | — | — | ✅ | — | all |

## Catalog (5 settings)

| Key | Type | Default | Scopes | Sensitivity | Apply | Min | Max | Enforced | Allowed | Segments |
|---|---|---|---|---|---|---|---|---|---|---|
| `catalog.sku_format` | string | `{category}-{number}` | TENANT | normal | immediate | — | — | ✅ | — | all |
| `catalog.barcode_auto_generate` | bool | `True` | TENANT | normal | immediate | — | — | ✅ | — | all |
| `catalog.default_tax_rate` | number | `0` | TENANT | normal | immediate | 0 | 100 | ✅ | — | all |
| `catalog.show_out_of_stock` | bool | `True` | TENANT | normal | immediate | — | — | ✅ | — | all |
| `catalog.max_variants_per_product` | number | `100` | TENANT | normal | immediate | 1 | 10,000 | ✅ | — | all |

## Team (3 settings)

| Key | Type | Default | Scopes | Sensitivity | Apply | Min | Max | Enforced | Allowed | Segments |
|---|---|---|---|---|---|---|---|---|---|---|
| `team.default_role` | enum | `cashier` | TENANT | normal | immediate | — | — | ✅ | cashier, manager, owner | all |
| `team.require_2fa` | bool | `False` | TENANT | sensitive | immediate | — | — | ✅ | — | all |
| `team.session_timeout_minutes` | number | `0` | TENANT | normal | immediate | 0 | 10,080 | ✅ | — | all |
| `team.allow_member_invites` | bool | `True` | TENANT | normal | immediate | — | — | ✅ | — | all |

## Security (4 settings)

| Key | Type | Default | Scopes | Sensitivity | Apply | Min | Max | Enforced | Allowed | Segments |
|---|---|---|---|---|---|---|---|---|---|---|
| `security.require_strong_passwords` | bool | `True` | TENANT | sensitive | immediate | — | — | ✅ | — | all |
| `security.api_key_rotation_days` | number | `90` | TENANT | sensitive | immediate | 0 | 365 | ✅ | — | all |
| `security.audit_retention_days` | number | `365` | TENANT | normal | immediate | 30 | 2,555 | ✅ | — | all |
| `security.ip_allowlist` | list | `[]` | TENANT | sensitive | immediate | — | — | ✅ | — | all |

## Billing (3 settings)

| Key | Type | Default | Scopes | Sensitivity | Apply | Min | Max | Enforced | Allowed | Segments |
|---|---|---|---|---|---|---|---|---|---|---|
| `billing.auto_renew` | bool | `True` | TENANT | normal | immediate | — | — | ✅ | — | all |
| `billing.currency` | enum | `EGP` | TENANT | normal | immediate | — | — | ✅ | EGP, SAR, USD, EUR, ... | all |
| `billing.notify_before_renewal_days` | number | `7` | TENANT | normal | immediate | 0 | 30 | ✅ | — | all |

## Notifications (5 settings)

| Key | Type | Default | Scopes | Sensitivity | Apply | Min | Max | Enforced | Allowed | Segments |
|---|---|---|---|---|---|---|---|---|---|---|
| `notifications.low_stock_alert` | bool | `True` | TENANT, WAREHOUSE | normal | immediate | — | — | ✅ | — | all |
| `notifications.order_received` | bool | `True` | TENANT, USER | normal | immediate | — | — | ✅ | — | all |
| `notifications.quiet_hours_start` | string | `""` | TENANT | normal | immediate | — | — | ✅ | — | all |
| `notifications.quiet_hours_end` | string | `""` | TENANT | normal | immediate | — | — | ✅ | — | all |
| `notifications.digest_mode` | enum | `realtime` | TENANT | normal | immediate | — | — | ✅ | realtime, hourly, daily | all |
| `notifications.email_enabled` | bool | `False` | TENANT | normal | immediate | — | — | ✅ | — | all |
| `notifications.push_enabled` | bool | `True` | TENANT | normal | immediate | — | — | ✅ | — | all |

---

## Scope inheritance chain

```
TENANT → WORKSPACE → BRANCH → WAREHOUSE → POS_PROFILE → REGISTER
TENANT → CHANNEL
TENANT → USER
```

## Storage schema

### `tenant_settings`

| Column | Type | Description |
|---|---|---|
| `id` | UUID | Primary key |
| `tenant_id` | UUID | Tenant (RLS) |
| `key` | text | Setting key (FK to registry, not DB) |
| `scope` | enum | `tenant`, `workspace`, `branch`, `warehouse`, `pos_profile`, `register`, `channel`, `user` |
| `scope_id` | UUID? | Entity ID for non-tenant scopes (NULL for tenant scope) |
| `value` | JSONB | `{"v": <typed_value>}` |
| `created_at` | timestamp | |
| `updated_at` | timestamp | |

Unique constraint: `(tenant_id, key, scope, scope_id)`.

### `tenant_settings_history`

Append-only audit trail. Every write to `tenant_settings` creates a row here
with the before/after values, who changed it, and when.

### `setting_change_requests`

Pending approval flow for `APPROVAL_REQUIRED` settings. Status transitions:
`pending` → `approved` / `rejected`.
