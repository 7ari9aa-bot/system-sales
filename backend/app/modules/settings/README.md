# settings

SETTINGS domain —
FIHRIST Configuration Control Plane (Retail Operations Configuration v2).

## Where things are

- `models.py`: Database models (`tenant_settings`, `tenant_settings_history`, `setting_change_requests`)
- `registry.py`: Settings Registry and definitions (`SettingDef`, types, scopes, validation, `ApplyMode`, `Sensitivity`)
- `service.py`: Hierarchical resolver, CRUD, change management, rollback (`SettingsService`)
- `presets.py`: Out-of-the-box configuration presets (see [Presets](#presets) below)
- `schemas.py`: Pydantic input/output schemas
- `router.py`: REST endpoints mounted under `/settings`
- `events.py`: `settings.changed` event type for the transactional outbox (§36–§38)
- `policy.py`: Permission-based write authorization
- `scope_graph.py`: Scope hierarchy resolution from the database
- `capabilities.py`: Vertical-based capability defaults and owner overrides

## HTTP

Endpoints registered in `app/main.py`:
- `GET /settings/definitions`: Lists setting definitions and metadata (`?domain=`, `?segment=retail|fnb|services|wholesale`)
- `GET /settings/domains`: Lists registered domains
- `GET /settings/capabilities`: Shop's vertical and enabled capabilities
- `GET /settings/effective`: Resolves effective settings with hierarchical inheritance
- `GET /settings/effective/{key}`: Resolves single setting key
- `GET /settings/overrides`: Lists raw tenant overrides
- `PUT /settings/{key}`: Sets a scoped override (supports `expected_history_id` for optimistic concurrency)
- `POST /settings/bulk`: Sets multiple overrides at once
- `DELETE /settings/{key}`: Reverts an override to inherited value
- `GET /settings/presets`: Lists presets
- `POST /settings/presets/{preset_name}`: Applies a preset at tenant scope
- `GET /settings/history`: Audit log of configuration changes
- `POST /settings/change-requests`: Create a change request for approval-gated settings (§28)
- `GET /settings/change-requests`: List change requests (optional `?status=` filter)
- `POST /settings/change-requests/{id}/approve`: Approve and apply a change request
- `POST /settings/change-requests/{id}/reject`: Reject a change request
- `POST /settings/rollback`: Roll back a setting to a previous revision (§34)

## Tables

- `tenant_settings` (overrides table with full tenant isolation RLS)
- `tenant_settings_history` (append-only change audit log with RLS)
- `setting_change_requests` (change request lifecycle with RLS, §28)

## Architecture contracts (§11, §27)

Every `SettingDef` carries:
- `apply_mode`: `immediate` | `validated` | `approval_required` — how a change reaches the runtime
- `sensitivity`: `normal` | `sensitive` | `secret` — data classification
- `feature_requirement`: optional entitlement link (§72)
- `rollback_supported`: whether this setting can be rolled back (§35)

## Event-driven sync (§36–§38)

Every setting write (set, reset, bulk_set) stages a `settings.changed` event in the
transactional outbox, in the same transaction as the write. Runtime systems (POS,
inventory, agents) consume the event and invalidate their cached config. The event
carries the key, scope, revision (history row id), and action for idempotency.

## Registered domains

The registry defines **119 settings across 18 domains**. Every key is listed below
with its English label and default value.

### `business` — shop identity and legal info (15 keys)

| Key | Label | Default |
|---|---|---|
| `business.legal_name` | Legal Name | `""` |
| `business.trade_name` | Trade Name | `""` |
| `business.tax_id` | Tax ID | `""` |
| `business.commercial_register` | Commercial Register | `""` |
| `business.phone` | Phone | `""` |
| `business.email` | Email | `""` |
| `business.website` | Website | `""` |
| `business.address.line1` | Address Line 1 | `""` |
| `business.address.city` | City | `""` |
| `business.address.postal_code` | Postal Code | `""` |
| `business.type` | Business Type | `"retail"` |
| `business.vertical` | Industry | `DEFAULT_VERTICAL` |
| `business.setup_state` | Activity setup state | `"done"` |
| `business.terms_accepted_at` | Terms accepted at | `""` |
| `reports.managers_see_profit` | Managers see cost and profit reports | `True` |

Consumed by: `pos/service.py` (vertical), `pos/receipt_settings.py` (legal info on
receipts), `pos/eta_adapter.py` (legal info for e-invoice).

### `pos` — cashier / till behaviour (16 keys)

| Key | Label | Default | Segments |
|---|---|---|---|
| `pos.require_customer` | Require Customer | `False` | |
| `pos.cash_movement_limit` | Cash movement limit | `0` | |
| `pos.max_discount_pct` | Max Discount % | `None` | |
| `pos.allow_hold_cart` | Allow Hold Cart | `True` | |
| `pos.return_max_days` | Return Window (Days) | `30` | |
| `pos.exchange_max_days` | Exchange Window (Days) | `0` | |
| `pos.return_restock_default` | Restock Returned Items by Default | `True` | |
| `pos.refund_cash_only` | Refund Cash Only | `False` | |
| `pos.return_reasons` | Return Reasons | `["size", ...]` | |
| `pos.take_payments` | Record Payments at the Till | `False` | retail |
| `pos.allow_record_only_sales` | Allow Selling Without Collecting | `False` | retail |
| `pos.settle_payment_methods` | Settle Every Payment Method at Close | `False` | retail |
| `pos.allow_sale_on_account` | Sell on Customer Account | `False` | retail |
| `pos.reference_required_methods` | Payment Methods That Need a Reference | `["card", ...]` | retail |
| `pos.variance_reason_required` | Require a Reason for a Drawer Variance | `True` | retail |
| `pos.variance_approval_threshold` | Drawer Variance That Needs a Manager | `0` | retail |

Consumed by: `pos/service.py` (return policy, discount limit, payment flow, drawer
variance), `pos/receipt_settings.py` (exchange window on receipts).

### `inventory` — stock, reservations, warehouses (12 keys)

| Key | Label | Default | Segments |
|---|---|---|---|
| `inventory.auto_reserve` | Auto Reserve for Orders | `True` | |
| `inventory.expiry_alert_days` | Expiry alert window (days) | `30` | |
| `inventory.dead_stock_days` | Dead stock after (days without a sale) | `60` | |
| `inventory.reserve_ttl_minutes` | Reservation TTL (Minutes) | `15` | |
| `inventory.fifo_enabled` | Enable FIFO Costing | `True` | retail, fnb, wholesale |
| `inventory.track_locations` | Track Warehouse Locations | `False` | retail, fnb, wholesale |
| `inventory.show_warehouse_transfers` | Show transfers between warehouses | `True` | |
| `inventory.show_channel_allocation` | Show online stock allocation | `True` | |
| `inventory.show_units_of_measure` | Show units of measure | `True` | |
| `inventory.quality_check_on_receipt` | Quality Check on Receipt | `False` | retail, fnb, wholesale |
| `inventory.stocktake_approval_required` | Stocktake Requires Approval | `True` | retail, fnb, wholesale |
| `inventory.safety_stock_default` | Default Safety Stock | `0` | retail, fnb, wholesale |

Consumed by: `orders/service.py` (auto_reserve, reserve_ttl), `inventory/services/valuation.py`
(fifo), `inventory/services/locations.py` (track_locations), `inventory/services/expiry.py`
(expiry_alert_days), `inventory/services/screens.py` (show_* toggles),
`inventory/services/replenishment.py` (safety_stock), `inventory/services/stocktakes.py`
(approval), `purchasing/service.py` (quality_check).

### `orders` — order lifecycle and stock deduction (3 keys)

| Key | Label | Default | Segments |
|---|---|---|---|
| `orders.reserve_on` | Reserve Stock On | `"create"` | |
| `orders.allow_backorder` | Allow Backorder | `False` | retail, fnb, wholesale |
| `orders.deduct_stock_on` | Deduct Stock On (Orders) | `"confirm"` | |

Consumed by: `orders/service.py` — controls when stock is reserved (creation vs
confirmation) and when it is deducted (confirm/ship/deliver), and whether backorders
are allowed.

### `einvoice` — Egyptian Tax Authority e-receipts (15 keys)

| Key | Label | Default |
|---|---|---|
| `einvoice.eta_enabled` | ETA e-receipt | `False` |
| `einvoice.settings_confirmed` | I reviewed the price, VAT and payment settings | `False` |
| `einvoice.prices_include_vat` | Prices include VAT | `True` |
| `einvoice.default_payment_method` | Default receipt payment method | `"C"` |
| `einvoice.split_payment_rule` | Split-payment rule on the receipt | `"largest"` |
| `einvoice.vat_category` | Item VAT category | `"taxable"` |
| `einvoice.unit_code` | Receipt unit of measure | `"EA"` |
| `einvoice.delivery_mode` | Delivery mode | `"FC"` |
| `einvoice.warn_hours_before_deadline` | Warn before send deadline (hours) | `24` |
| `einvoice.branch_code` | Branch code at the authority | `""` |
| `einvoice.activity_code` | Activity code | `""` |
| `einvoice.branch_governate` | Branch governorate | `""` |
| `einvoice.branch_region_city` | Branch city or region | `""` |
| `einvoice.branch_street` | Branch street | `""` |
| `einvoice.branch_building_number` | Branch building number | `""` |

Consumed by: `pos/eta_adapter.py` (all e-invoice fields), `einvoice/providers/eta/delivery.py`
(deadline warning).

### `customer_agent` — AI customer-facing agent (8 keys)

| Key | Label | Default |
|---|---|---|
| `customer_agent.enabled` | Customer Agent Enabled | `False` |
| `customer_agent.dialect` | Response Dialect | `"egyptian"` |
| `customer_agent.formality` | Formality Level | `"friendly"` |
| `customer_agent.response_language` | Response Language | `"ar"` |
| `customer_agent.handoff_enabled` | Human Handoff | `True` |
| `customer_agent.max_turns_before_handoff` | Max Turns Before Handoff | `5` |
| `customer_agent.show_prices` | Show Prices | `True` |
| `customer_agent.show_stock` | Show Stock | `True` |

Consumed by: `ai/hooks.py` (enabled, dialect, formality, language, handoff, max_turns —
injected as `style_directive`), `ai/agents/customer/tools/catalog.py` (show_prices,
show_stock), `ai/agents/customer/tools/support.py` (handoff_enabled).

### `analytics_agent` — AI sales-intelligence agent (4 keys)

| Key | Label | Default |
|---|---|---|
| `analytics_agent.enabled` | Analytics Agent Enabled | `False` |
| `analytics_agent.default_period` | Default Period | `"30d"` |
| `analytics_agent.include_branches` | Included Branches | `[]` |
| `analytics_agent.min_confidence` | Minimum Confidence | `0.7` |

Consumed by: `ai/agents/sales_intelligence/agent.py`.

### `catalog` — product and variant management (5 keys)

| Key | Label | Default |
|---|---|---|
| `catalog.sku_format` | SKU Format | `"{category}-{number}"` |
| `catalog.barcode_auto_generate` | Auto-Generate Barcodes | `True` |
| `catalog.default_tax_rate` | Default Tax Rate % | `0` |
| `catalog.show_out_of_stock` | Show Out-of-Stock Items | `True` |
| `catalog.max_variants_per_product` | Max Variants Per Product | (see registry) |

Consumed by: `catalog/services/products.py` (tax_rate), `catalog/services/variants.py`
(sku_format, barcode, max_variants), `ai/agents/customer/tools/catalog.py`
(show_out_of_stock), `catalog/routers/imports.py` (legacy_csv_endpoint).

### `purchasing` — purchase orders and receiving (5 keys)

| Key | Label | Default | Segments |
|---|---|---|---|
| `purchasing.approval_required` | PO Requires Approval | `False` | |
| `purchasing.approval_threshold` | Approval Threshold Amount | `0` | |
| `purchasing.allow_partial_receipt` | Allow Partial Receipt | `True` | |
| `purchasing.allow_over_receipt` | Allow Over Receipt | `False` | retail, fnb, wholesale |
| `purchasing.centralized` | Centralized Purchasing | `False` | |

Consumed by: `purchasing/service.py`.

### `notifications` — alert and digest preferences (7 keys)

| Key | Label | Default |
|---|---|---|
| `notifications.low_stock_alert` | Low Stock Alert | `True` |
| `notifications.order_received` | New Order Notification | `True` |
| `notifications.quiet_hours_start` | Quiet Hours Start | (see registry) |
| `notifications.quiet_hours_end` | Quiet Hours End | (see registry) |
| `notifications.digest_mode` | Digest Mode | (see registry) |
| `notifications.email_enabled` | Email Notifications | (see registry) |
| `notifications.push_enabled` | Push Notifications | (see registry) |

Consumed by: `platform/services/notifications.py`, `notifications/digest.py` (digest_mode,
quiet hours via direct SQL read), `billing/services/trial_expiry.py` (notify_before_renewal_days).

### `organization` — tenant-wide structure (5 keys)

| Key | Label | Default |
|---|---|---|
| `organization.fiscal_year_start_month` | Fiscal Year Start Month | `1` |
| `organization.multi_branch` | Multi-Branch Operations | `False` |
| `organization.max_branches` | Maximum Branches | `0` |
| `organization.default_language` | Default Language | `"ar"` |
| `organization.brand_color` | Brand Color | `""` |

Consumed by: frontend workspace settings (brand_color injected into global CSS),
organization structure screens.

### `branch` — per-branch operations (4 keys)

| Key | Label | Default |
|---|---|---|
| `branch.auto_close_shift` | Auto-Close Shift | `False` |
| `branch.shift_end_time` | Shift End Time | `"23:59"` |
| `branch.notify_manager_on_variance` | Notify Manager on Drawer Variance | `True` |
| `branch.allow_independent_purchasing` | Independent Branch Purchasing | `False` |

Consumed by: `pos/service.py` (notify_manager_on_variance), `purchasing/service.py`
(allow_independent_purchasing).

### `print` — receipt and invoice printing (8 keys)

| Key | Label | Default |
|---|---|---|
| `print.paper_width` | Paper Width | `"80mm"` |
| `print.show_logo` | Show Logo | `True` |
| `print.header_text` | Receipt Header Text | `""` |
| `print.footer_text` | Receipt Footer Text | `""` |
| `print.copies` | Print Copies | `1` |
| `print.show_tax_detail` | Show Tax Detail | `True` |
| `print.barcode_format` | Barcode Format | `"code128"` |
| `print.invoice_prefix` | Invoice Number Prefix | `"INV"` |

Consumed by: `pos/receipt_settings.py` (paper_width, show_logo, header, footer, copies,
tax_detail), `pos/eta_adapter.py` (invoice_prefix).

### `billing` — subscription and invoicing (3 keys)

| Key | Label | Default |
|---|---|---|
| `billing.auto_renew` | Auto Renew | (see registry) |
| `billing.currency` | Billing Currency | (see registry) |
| `billing.notify_before_renewal_days` | Notify Before Renewal (days) | (see registry) |

Consumed by: `billing/services/trial_expiry.py` (auto_renew, notify_before_renewal_days
via direct SQL read).

### `security` — access control policies (4 keys)

| Key | Label | Default |
|---|---|---|
| `security.require_strong_passwords` | Require Strong Passwords | (see registry) |
| `security.api_key_rotation_days` | API Key Rotation Days | (see registry) |
| `security.audit_retention_days` | Audit Retention Days | (see registry) |
| `security.ip_allowlist` | IP Allowlist | (see registry) |

Consumed by: `identity/services/auth.py` (require_strong_passwords via direct SQL read).

### `team` — team member management (4 keys)

| Key | Label | Default |
|---|---|---|
| `team.default_role` | Default Role | (see registry) |
| `team.require_2fa` | Require 2FA for All Members | (see registry) |
| `team.session_timeout_minutes` | Session Timeout (Minutes) | (see registry) |
| `team.allow_member_invites` | Allow Member Invites | (see registry) |

Consumed by: `identity/services/auth.py` (require_2fa via direct SQL read).

### `reports` — reporting access (1 key)

| Key | Label | Default |
|---|---|---|
| `reports.managers_see_profit` | Managers see cost and profit reports | `True` |

Registered under the `business` domain block; controls whether manager-role users see
cost and profit figures in reports and can apply season markdowns.

### `imports` — data import toggles (1 key)

| Key | Label | Default |
|---|---|---|
| `imports.legacy_csv_endpoint` | Re-open the legacy CSV import endpoint | `False` |

Consumed by: `catalog/routers/imports.py`.

## Segments

Segments control which settings the settings screen shows for a given business type.
They never affect what a key resolves to — code that reads a setting never branches on
the segment. Segments used in the registry:

- **retail**: POS payment-flow keys (`take_payments`, `settle_payment_methods`, etc.)
- **retail, fnb, wholesale**: inventory costing/tracking keys, purchasing over-receipt,
  orders backorder

A setting with no segments (`()`) is shown to every business type.

## Presets

Five presets ship out of the box, each a `{key: value}` dict applied at tenant scope:

| Preset | Keys | What it optimizes for |
|---|---|---|
| `physical_retail` | 12 | Single shop, face-to-face POS, cash. No auto-reserve, no FIFO, no location tracking. |
| `ecommerce` | 12 | Online-only. Auto-reserve with 24h TTL, FIFO, orders reserve on create. |
| `omnichannel` | 12 | POS + online. Auto-reserve 24h, FIFO, no location tracking. |
| `enterprise` | 17 | Multi-branch chain. Centralised purchasing with approval, location tracking, quality checks, stocktake approval. |
| `apparel_ground_shop` | 26 | Single apparel store, walk-in cash. Hides transfers/channel/UoM screens, disables serial/lot/expiry capabilities. |

> **Note**: `ecommerce`, `omnichannel` and `enterprise` set `inventory.reserve_ttl_minutes`
> to 1440 (24h). The registry default is 15, so a shop that applies no preset is unchanged.

## How settings are consumed

Two patterns, chosen to avoid circular imports:

1. **`SettingsService(session, tenant_id).value(key)`** — the standard pattern. Used by
   `pos/service.py`, `orders/service.py`, `purchasing/service.py`, `inventory/services/*`,
   `catalog/services/*`, `ai/hooks.py`, `ai/agents/customer/tools/*`,
   `einvoice/providers/eta/delivery.py`.

2. **Direct SQL read** — used in modules where importing `SettingsService` would create a
   cycle (identity → settings, billing → settings). A small `SELECT` against
   `tenant_settings` resolves the key without importing the settings service:
   - `identity/services/auth.py`: `security.require_strong_passwords`, `team.require_2fa`
   - `billing/services/trial_expiry.py`: `billing.auto_renew`, `billing.notify_before_renewal_days`
   - `notifications/digest.py`: `notifications.digest_mode`, quiet hours

## Depends on

- Core: `app.core.db`, `app.core.model_kit`, `app.core.events.writer`, `app.core.audit`
- Auth: `app.modules.identity.deps` (TenantContext, require_permission)

## Rules for working here

- Every new setting must be defined in `registry.py` with its type, default, allowed scopes, and `apply_mode`.
- Decide a new setting's `segments` on purpose: `()` (the default) means every kind of business sees
  it; name segments only when the key is meaningless to the others (shelf stock for a services
  shop). Segments only change what the settings screen lists, never what a key resolves to, so the
  code that reads it never branches on the segment.
- Database stores overrides only; defaults stay in code.
- Scoped inheritance walks: `register -> pos_profile -> warehouse -> branch -> tenant -> default`.
- All writes are audited in `tenant_settings_history` and stage a `settings.changed` outbox event.
- Services `flush()` and never `commit()`.
- For approval-gated settings (`apply_mode = approval_required`), use `create_change_request` —
  never call `set` directly.
- When wiring a new consumer, prefer `SettingsService.value()`. If that creates a circular
  import, use a direct SQL read and document it here so the pattern stays visible.
