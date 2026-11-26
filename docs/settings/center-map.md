# Settings Center — the map / خريطة مركز الإعدادات

> **Status:** live — the target information architecture for the Settings Center, and the
> build order that closes the gap between it and the code.
> **Last updated:** 2026-11-26 · **Owner's proposal:** Hamed, 2026-11-26

This document is the **navigation contract**. `frontend-specification.md` says what each screen
consumes today; this one says what the Settings Center is supposed to look like when it is
finished, section by section, so that no page is invented twice and no setting is homeless.

Twenty sections in five groups. They are **navigation groups**, not twenty sibling pages.

---

## 1. Groups and sections

### Group 1 — Account and administration

| # | Section | Pages |
|---|---|---|
| 01 | **My Account** — everything about the signed-in person, whatever workspace they are in | Profile · Sign-in · Personal security · Preferences · Personal notifications |
| 02 | **Workspace** — the organisational container, which may hold more than one business | Overview · Workspace data · Ownership and administration · Manage workspaces · Workspace settings |
| 03 | **Team & permissions** — who exists and what they may do | Members · Invitations · Roles · Permission matrix · Teams and departments · Access scope |

### Group 2 — Business and structure

| # | Section | Pages |
|---|---|---|
| 04 | **Store & business** — identity and the facts used inside the system and in front of customers | Business profile · Brand identity · Contact details · Working hours · Business policies · Legal data |
| 05 | **Locations** — the physical structure | All branches · Branch data · Branch hours · Branch settings · Branch staff · Operating scopes |

A **branch**, a **warehouse** and a **register** are three different things. A branch may own one
warehouse and several registers; they are not the same entity and must not share a page.

### Group 3 — Commerce and operations

| # | Section | Pages |
|---|---|---|
| 06 | **Products & catalog** | Product settings · Categories · Variants and options · Attributes and specs · SKU and barcode · Images and media · Product states |
| 07 | **Sales, pricing and tax** — the rules of selling, not the act of selling | Sales settings · Price lists · Pricing · Discounts and offers · Taxes and fees · Exchange and returns |
| 08 | **POS & registers** — configuring the till, not building a payment processor | POS settings · Registers and devices · Collection methods · Shifts · Cash movement · Invoices and receipts · Peripherals · Offline mode |
| 09 | **Inventory & warehousing** | Inventory settings · Warehouses · Stock states · Stock limits · Counts and adjustments · Transfers · Inventory cost |
| 10 | **Purchasing & suppliers** | Suppliers · Purchasing settings · Purchase orders · Receiving and inspection · Supplier returns · Approval limits |
| 11 | **Customers & support** — the customer relationship; the agent's behaviour lives in 13 | Customer data · Customer segments · Customer records · Inbox · Conversation routing · Reply templates · Support hours · Escalation to a human |

### Group 4 — Channels and intelligence

| # | Section | Pages |
|---|---|---|
| 12 | **Channels & integrations** | Connected channels · WhatsApp Business · Facebook · Instagram · Data sync · External integrations · Connection health |
| 13 | **AI & agents** | Agent management · Customer Agent · Analytics Agent · Knowledge sources · Models and routing · Tools and permissions · Policies and safety · Testing and evaluation · Versions and publishing |
| 14 | **Analytics & reports** | Dashboards · Metrics and indicators · Reports · Scheduled reports · Analysis settings · Report permissions |
| 15 | **Automation & workflows** | Rules · Workflows · Triggers and events · Schedules · Approvals · Execution attempts |
| 16 | **Notifications** — workspace rules, where 01 holds the person's preferences | Notification channels · Notification rules · Message templates · Recipients · Alerts and escalation |

Agent boundaries are part of the design, not a prompt detail:

- **Customer Agent** answers enquiries, understands text, images and voice, finds products and
  shows their pictures, and may hand over to a human. It does **not** add to cart, create orders,
  take payment or sell.
- **Analytics Agent** analyses and reports, and every figure it gives is backed by evidence — it
  never presents an LLM guess as an account.
- Agent permissions are **independent of staff permissions** and are declared per agent type.

### Group 5 — Advanced administration

| # | Section | Pages |
|---|---|---|
| 17 | **Data & privacy** | Import · Export · Retention · Backups and restore · Data privacy · Data deletion |
| 18 | **Security & governance** | Security policies · Session control · Audit log · Settings change log · Approval requests · Sensitive settings · Emergency procedures |
| 19 | **Plan & billing** | Current plan · Usage · Invoices · Payment methods · Billing details · Renewal and upgrade |
| 20 | **Developers & API** — hidden from ordinary users; shown only to developer/integration roles | API keys · Webhooks · Connected apps · Rate limits · API logs · Developer environment |

Section 18 is where the existing Settings Engine (approvals, change history, sensitive keys,
restore) becomes visible to the merchant. Section 20 is the only section that may be hidden by
role rather than by plan.

---

## 2. Scope model — every setting declares where it may live

The one failure mode a centre of this size must not have: a value changed in one place that
silently changes a branch, a register or a channel.

```
Platform · Workspace/Tenant · Store · Branch · Register · Channel · Agent · User
```

This is a **set of allowed paths per setting**, not one inheritance tree. Each setting declares:

- may it be set at workspace level?
- may it be overridden per store?
- per branch? per register?
- is it channel- or agent-specific?
- is it personal, and therefore unaffected by the workspace?

Example: receipt layout defaults at the business level, with an exception for one branch or one
register. The person's own language must never change because they moved to another branch.

---

## 3. Anatomy of a settings page

Every page, whatever it configures, answers the same questions in the same order:

1. what this setting does, in one line;
2. grouped, comprehensible controls;
3. the current effective value **and where it comes from**;
4. inherited or overridden — visibly;
5. who may read it and who may change it;
6. validation before saving;
7. the impact of the change when it is not obvious;
8. immediate save, or a change request when the change is risky;
9. history and restore where supported;
10. clear success and error messages.

## 4. Rules that bind every section

1. **No duplicated setting.** One canonical home; another page may link to it, never edit it.
2. **Settings vs operational data.** The low-stock *rule* is a setting; the stock *quantity* is
   operational data. The barcode *format* is a setting; a product's barcode is product data.
3. **Per-section permissions.** Reading, writing and approving are three different rights.
4. **High-risk settings need extra protection** — tax, return policy, cash limits, sensitive
   permissions, channel credentials, agent knowledge sources.
5. **No single inheritance path.** POS settings, inventory settings and personal preferences each
   have their own valid scope paths.
6. **Merchant surface and platform surface stay apart.** Plans, central model settings,
   infrastructure and tenant administration belong to a separate Platform Admin control plane,
   never to a store's settings.

## 5. One engine, many screens

```
Settings Center (frontend: sections, search, forms, visibility)
        ↓
Settings API & application services (read/write, validation, change requests, approvals)
        ↓
Registry · Scope resolver · Policy engine · Validation engine · History & audit · Change workflow
        ↓
Postgres configuration store  →  outbox/events  →  workers, caches, consumers
```

The **registry is the source of truth**: `key`, `section`, `page`, `type`, `default_value`,
`allowed_scopes`, `validation`, `permission`, `sensitive`, `approval_policy`, `dependencies`,
`impact_level`, `status`. A key with no owner, or a control on a screen that changes nothing, is a
defect. See [registry-specification.md](registry-specification.md) for the keys that exist today.

---

## 6. Build status

| Section | State | Where |
|---|---|---|
| 01 Profile | done | `/settings` — photo, name, email, phone, job title, verification, account closure |
| 01 Sign-in | done | `/settings/login` — password change, sign-in method, recovery |
| 01 Personal security | done | `/settings/security` — two-step verification, signed-in devices |
| 01 Preferences | done | `/settings/preferences` — language, appearance, the person's own timezone, date format, landing page; stored on the account (migration fe2026112610) |
| 01 Personal notifications | done | `/settings/notifications` — email/push switches (in-app locked as the record), quiet hours as real times read in the person's own zone; `GET`/`PUT /users/me/notification-preferences`; one row per person (migration fe2026112611) and the dispatcher now honours it |
| 02 Workspace overview | done | `/settings/workspace` — the container, its state, your role in it, member count, region |
| 02 Workspace data | done | `/settings/workspace/data` — name (editable), identifier (read-only: other systems address it), country/currency/timezone; brand logo stays in Store & business, where the identity belongs |
| 02 Ownership and administration | done | `/settings/workspace/ownership` — owner and administrators from `GET /workspaces/current/admins` (settings read); transfer is explained, not offered, because no transfer endpoint exists behind it |
| 02 Manage workspaces | done | `/settings/workspace/switch` — every membership from `GET /workspaces`, entering one through `POST /auth/switch-tenant` |
| 02 Workspace settings | done | `/settings/workspace/defaults` — the inherited values read-only, each with a link to the single page that owns it |
| 03 Members | done | `/settings/team/members` (and `/settings/members`) — the real roster with a working role change (`PUT /tenants/{id}/members/{user_id}`, rank-guarded) and removal (`DELETE`, refused for the owner and for yourself) |
| 03 Invitations | done | `/settings/team/invitations` — create through `POST /tenants/{id}/invitations`, copy the one-time link, list and revoke; seat limits still enforced server-side |
| 03 Roles | done | `/settings/team/roles` — the seeded roles and the permission count each actually carries, from `GET /roles/matrix`; read-only because the guards are written against these codes |
| 03 Permission matrix | done | `/settings/team/matrix` — every real permission row against every role, read/write/approve shown as distinct actions; ticks come from `role_permissions`, so no cell can promise an unchecked action |
| 03 Teams and departments | done | `/settings/team/groups` — real teams (migration fe2026112612, tenant RLS on both tables) with add/remove members; a team grants nothing by design and the page says so |
| 03 Access scope | done | `/settings/team/access` — per-branch grants through `/hierarchy/locations/{id}/access`; warehouses and tills stay on their own pages |
| 04 Business profile | done | `/settings/store/business-profile` — trade name, business type, vertical, setup state, the shop's default language and the capability switches, rendered from the registry |
| 04 Brand identity | done | `/settings/store/brand-identity` — the brand colour (`organization.brand_color`) |
| 04 Contact details | done | `/settings/store/contact-details` — phone, email, website and address lines, tenant and branch scoped |
| 04 Legal data | done | `/settings/store/legal-data` — legal name, tax ID, commercial register, terms acceptance; all four already reach the receipt read model |
| 04 Working hours | done | `/settings/store/working-hours` — publishes the `hours` store policy, the text the customer agent answers "when are you open" from. Not a registry key: the promise is prose the agent quotes, and it lives in one row of `knowledge_items` |
| 04 Business policies | done | `/settings/store/business-policies` — the enforced windows (`pos.return_max_days`, `pos.exchange_max_days`, both high impact) plus the published exchange, return, warranty, cancellation, shipping and ordering policies and the deposit rules |
| 05 All branches | done | `/settings/locations/all-branches` — the branches that exist, read from the hierarchy (`workspaces` → `locations`) beside the keys that limit how many there may be |
| 05 Branch settings | done | `/settings/locations/branch-settings` — the four `branch.*` keys at branch scope |
| 05 Branch data | done | `/settings/locations/branch-data` — name, code and "this branch trades", written through `PATCH /hierarchy/locations/{id}` |
| 05 Branch hours | done | `/settings/locations/branch-hours` — the branch's own week in the new `locations.hours` column (migration `fe2026112613`); empty means "follows the store", which is what every existing row says |
| 05 Branch staff | done | `/settings/locations/branch-staff` — the real grants: list, grant with a per-branch role override, revoke, over `user_location_access` |
| 05 Operating scopes | done | `/settings/locations/operating-scopes` — read-only: every key that accepts a branch value, its resolved value and whether it was inherited, set for the branch, or is the default |
| 06 Product settings | done | `/settings/catalog/product-settings` — `catalog.default_tax_rate` (high impact: it lands on every new product) |
| 06 Categories | done | `/settings/catalog/categories` — the real category list from `GET /catalog/categories`, with add; ordering and linking stay in the catalogue screen, which is where shop data belongs |
| 06 Variants and options | done | `/settings/catalog/variants-and-options` — `catalog.max_variants_per_product` |
| 06 Attributes and specs | done | `/settings/catalog/attributes-and-specs` — the shop's own size sets and colours (`GET/PUT/DELETE /catalog/apparel/options`), the apparel case: defined once, used by thousands of products |
| 06 SKU and barcode | done | `/settings/catalog/sku-and-barcode` — `catalog.sku_format` and `catalog.barcode_auto_generate`: the FORMAT, never a product's own barcode |
| 06 Product states | done | `/settings/catalog/product-states` — `catalog.show_out_of_stock` |
| 06 Images and media | pending | no media rule exists to edit (limits, ordering, placeholders are per-product data today); a page here would be switches wired to nothing |
| 07 Sales settings | done | `/settings/sales/sales-settings` — `orders.reserve_on`, `orders.deduct_stock_on`, `orders.allow_backorder` |
| 07 Taxes and fees | done | `/settings/sales/taxes-and-fees` — the fifteen `einvoice.*` keys, with `vat_category` and `prices_include_vat` marked high impact because they change what the customer is charged |
| 07 Exchange and returns | done | `/settings/sales/exchange-and-returns` — reads the windows in force (`GET /settings/effective`) and LINKS to their single home on `/settings/store/business-policies`; it offers no second editor |
| 07 Price lists | pending | no price-list table or endpoint exists; a product's price is append-only rows in `product_prices` per variant, currency and quantity tier |
| 07 Pricing | pending | no pricing-rule key exists: currency and tiers are per-product data, so a page would edit nothing |
| 07 Discounts and offers | pending | no offer engine exists; the only discount control is the till cap (`pos.max_discount_pct` at tenant level, `pos_profiles.max_discount_pct` per register), which belongs to section 08 |
| 08 POS settings | done | `/settings/pos/pos-settings` — customer required, hold cart, restock default, cash-only refunds, return reasons, record-only sales; `pos.max_discount_pct` is here and now high impact |
| 08 Registers and devices | done | `/settings/pos/registers-and-devices` — reuses the till's existing `DevicesSection` (profiles, registers, warehouses, members) rather than growing a second register editor |
| 08 Collection methods | done | `/settings/pos/collection-methods` — `take_payments`, `settle_payment_methods` (high impact), `allow_sale_on_account`, `reference_required_methods` |
| 08 Shifts | done | `/settings/pos/shifts` — `variance_reason_required`, `variance_approval_threshold` (high impact) |
| 08 Cash movement | done | `/settings/pos/cash-movement` — `cash_movement_limit` (high impact) |
| 08 Invoices and receipts | done | `/settings/pos/invoices-and-receipts` — the eight `print.*` keys |
| 08 Peripherals | pending | no peripheral configuration is stored anywhere: the printer and drawer are driven by the print keys and the device's own settings |
| 08 Offline mode | pending | the till has no offline queue or offline policy in the codebase, so a page would be a switch wired to nothing |
| 09 Inventory settings | done | `/settings/inventory/inventory-settings` — `inventory.track_locations`, `inventory.show_channel_allocation`, `inventory.show_units_of_measure` |
| 09 Warehouses | done | `/settings/inventory/warehouses` — the active warehouses from `GET /inventory/warehouses`, with where they are really created and edited stated on the page |
| 09 Stock states | done | `/settings/inventory/stock-states` — `auto_reserve`, `reserve_ttl_minutes`, `expiry_alert_days`, `dead_stock_days`: how stock is classified, which is not the same question as how it is costed |
| 09 Stock limits | done | `/settings/inventory/stock-limits` — `inventory.safety_stock_default`, the rule behind a low-stock warning (the quantities themselves stay operational data) |
| 09 Counts and adjustments | done | `/settings/inventory/counts-and-adjustments` — `inventory.stocktake_approval_required` (high impact) over the real stocktake list from `GET /inventory/stocktakes` |
| 09 Transfers | done | `/settings/inventory/transfers` — `show_warehouse_transfers`, `quality_check_on_receipt` over the real transfer list from `GET /inventory/transfers` |
| 09 Inventory cost | done | `/settings/inventory/inventory-cost` — `inventory.fifo_enabled` (high impact: it decides how the cost of goods sold is worked out) |
| 10 Suppliers | done | `/settings/purchasing/suppliers` — reads `GET /purchasing/suppliers` (the real list) and says where a supplier is created |
| 10 Purchasing settings | done | `/settings/purchasing/purchasing-settings` — `purchasing.centralized` |
| 10 Purchase orders | done | `/settings/purchasing/purchase-orders` — reads `GET /purchasing/purchase-orders` with number, date, total, status and the DERIVED payment state |
| 10 Receiving and inspection | done | `/settings/purchasing/receiving-and-inspection` — `allow_partial_receipt`, `allow_over_receipt` |
| 10 Supplier returns | done | `/settings/purchasing/supplier-returns` — reads `GET /purchasing/supplier-returns` with number, date, total and status |
| 10 Approval limits | done | `/settings/purchasing/approval-limits` — `approval_required` and `approval_threshold`, both high impact: one removes approval entirely, the other sets the amount above which it applies |
| 11–20 | pending | see the tables above |

The remaining sections are built one at a time, each with the page anatomy in §3, its bilingual
copy, its tests, and the gates in [runtime-testing-specification.md](runtime-testing-specification.md).

**Where the return promise lives.** A return is two objects, not one: the *window* the system
enforces (`pos.return_max_days`, read by `pos/service.py::return_policy` and printed on the receipt)
and the *wording* the customer agent quotes (the `return` policy row). Both are owned by
`04 Business policies` so the promise is read and written in one place. Section 07's
`exchange-and-returns` page links here; it must not offer a second editor for either.

**How a page is produced.** Every key declares its home in the registry (`section` + `page`, with
a domain default in `_DOMAIN_HOME` and per-key overrides where a domain spans pages). A Settings
Center page asks the server for `GET /settings/definitions?section=…&page=…` and renders exactly
those keys, so a control can only ever edit a setting whose canonical home is that page — the §4
"no duplicated setting" rule is enforced by construction rather than by review. `tests/test_settings_registry_homes.py`
fails if a registered key has no home, names a section outside the twenty, or could appear on two pages.
