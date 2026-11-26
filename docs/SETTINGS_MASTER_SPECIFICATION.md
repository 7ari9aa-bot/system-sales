# Settings Master Specification — FIHRIST Configuration Control Plane

> **Status:** live — مرجع تنفيذي يحتوي على كل إعداد في النظام بالتفصيل.
> **مطابق بالكود في:** `backend/app/modules/settings/`
> **آخر تحديث:** 2026-11-25
> **الإصدار:** v2.1

---

## 0. الغرض من هذه الوثيقة

هذه الوثيقة هي **المرجع التنفيذي الواحد** لكل إعداد في FIHRIST. ليست وصفاً
معمارياً — هي **جدول كامل** يربط كل مفتاح بنوعه وقيمته الافتراضية ونطاقه
وصلاحيته وقيوده ومكان تخزينه ومكان استهلاكه في الكود.

تم بناؤها بـ**مطابقة الكود الحالي** (`registry.py`, `service.py`, `models.py`,
`router.py`, `policy.py`, `scope_graph.py`, `presets.py`, `capabilities.py`,
`events.py`) — كل رقم وكل مفتاح في هذه الوثيقة مأخوذ من الكود الفعلي، لا من
تخمين.

### الأولويات التنفيذية

| الأولوية | المجال | الحالة |
|---|---|---|
| **P0** — Architecture Foundation | Registry · Scopes · Resolver · Validation · Permissions · Revisions · Audit | ✅ منفّذ |
| **P1** — Business Configuration | Organization · Branches · Catalog · Inventory · POS | ✅ منفّذ وموصّل |
| **P2** — Communication & Intelligence | Channels · Customer Agent · Analytics Agent | ✅ منفّذ (جزئياً للقنوات) |
| **P3** — Platform Management | Team · Security · Notifications · Integrations · Billing · Preferences | ✅ منفّذ (الإعدادات موصّلة، الواجهات قيد التطوير) |
| **P4** — Advanced Governance | Advanced Approvals · Config Migrations · Extended Presets | 🟡 جزئي (Change Requests منفّذ، Migrations غير منفّذ) |

> **تصحيح بعد مطابقة الكود:** `SecretStorePort` (§68-69) **مُنفّذ بالكامل** في
> `app/core/secrets.py` (Protocol + EnvSecretStore + InMemorySecretStore +
> DatabaseSecretStore + EnvelopeSecretStore + rotation). كذلك، حدود الوحدات
> مُفرضة بالفعل عبر `tests/test_module_boundaries.py` بنظام AST baseline ratchet
> (بديل import-linter). كلا النقطتين لم تكن مفقودتين كما سُجّل أول مرة.

---

## 1. البنية المعمارية الحالية (ما هو موجود فعلاً)

### 1.1 الملفات والمسؤوليات

| الملف | المسؤولية | سطور |
|---|---|---|
| `registry.py` | Registry ثابت في الكود: تعريف كل `SettingDef` مع النوع والنطاق والافتراضي والقيود | 2346 |
| `service.py` | Resolver هرمي + CRUD + Change Requests + Rollback — الكاتب الوحيد لـ `tenant_settings` | ~850 |
| `models.py` | 3 جداول: `tenant_settings`, `tenant_settings_history`, `setting_change_requests` | ~180 |
| `router.py` | 17 endpoint تحت `/settings` | ~500 |
| `policy.py` | صلاحيات الكتابة: `settings:write` و `settings:branch_write` | ~55 |
| `scope_graph.py` | سلسلة الوراثة من قاعدة البيانات (register → profile → warehouse → branch → tenant) | ~150 |
| `presets.py` | 5 presets: physical_retail, ecommerce, omnichannel, enterprise, apparel_ground_shop | ~140 |
| `capabilities.py` | 8 capabilities حسب الـvertical (variant_matrix, lot_expiry, etc.) | ~220 |
| `events.py` | `settings.changed` event عبر الـtransactional outbox | ~60 |
| `schemas.py` | Pydantic input/output schemas لكل endpoint | ~130 |

### 1.2 نطاقات الوراثة (Scope Hierarchy)

```
tenant (النطاق الجذري — لا scope_id)
  └── workspace (نشاط/قطاع واحد داخل الحساب)
        └── branch (فرع/موقع جغرافي)
              └── warehouse (مخزن داخل الفرع)
                    └── pos_profile (ملف نقطة بيع)
                          └── register (جهاز كاشير محدد)
  └── channel (قناة: whatsapp, pos, website — مرتبطة بـwarehouse)
  └── user (تفضيلات شخصية — يرث مباشرة من tenant)
```

**قاعدة الوراثة:** القيمة عند النطاق الأدنى تتجاوز القيمة عند النطاق الأعلى.
عند عدم وجود override عند أي نطاق، تُرجع القيمة الافتراضية من الـRegistry.

### 1.3 أنواع البيانات المدعومة

| النوع | الوصف | التحقق |
|---|---|---|
| `bool` | true/false | isinstance check |
| `number` | int/float/Decimal | min/max bounds |
| `string` | نص | max_length |
| `enum` | قيمة من قائمة مغلقة | allowed_values |
| `list` | قائمة JSON | لا تحقق إضافي حالياً |

### 1.4 أوضاع التطبيق (Apply Modes)

| الوضع | الوصف | مثال |
|---|---|---|
| `immediate` | يُطبّق فور التحقق | تفضيلات الواجهة |
| `validated` | تحقق من الـdomain قبل القبول | قواعد المخزون، الكاشير |
| `approval_required` | موافقة شخص ثانٍ قبل التطبيق | سياسات مالية حساسة |

### 1.5 تصنيف الحساسية (Sensitivity)

| التصنيف | الوصف | التخزين |
|---|---|---|
| `normal` | مرئي وقابل للتعديل عبر الـUI | `tenant_settings.value` |
| `sensitive` | وصول مقيد، القيمة مُقنّعة | `tenant_settings.value` (مُقنّعة في العرض) |
| `secret` | لا تُخزّن في جدول الإعدادات | SecretStore (غير منفّذ بعد — §68-69) |

---

## 2. الجداول وعلاقاتها

### 2.1 `tenant_settings` — جدول الـOverrides

| العمود | النوع | القيد |
|---|---|---|
| `id` | UUID PK | |
| `tenant_id` | UUID FK→tenants | RLS |
| `key` | VARCHAR(127) | NOT NULL |
| `scope` | VARCHAR(31) | default 'tenant' |
| `scope_id` | UUID | NULL (tenant only) |
| `value` | JSONB | NOT NULL — `{"v": <value>}` |
| `updated_by` | UUID FK→users | nullable |
| `created_at` / `updated_at` | timestamps | |

**القيود:**
- `UNIQUE(tenant_id, key, scope, scope_id)` مع `NULLS NOT DISTINCT`
- `CHECK (scope = 'tenant') = (scope_id IS NULL)`
- RLS على `tenant_id`

### 2.2 `tenant_settings_history` — سجل التدقيق (Append-Only)

| العمود | النوع | القيد |
|---|---|---|
| `id` | UUID PK | |
| `tenant_id` | UUID FK→tenants | RLS |
| `setting_id` | UUID FK→tenant_settings | nullable (SET NULL on delete) |
| `key` | VARCHAR(127) | NOT NULL |
| `scope` | VARCHAR(31) | NOT NULL |
| `scope_id` | UUID | nullable |
| `old_value` | JSONB | nullable |
| `new_value` | JSONB | nullable |
| `action` | VARCHAR(15) | 'set' \| 'reset' \| 'bulk_set' |
| `changed_by` | UUID FK→users | nullable |
| `change_reason` | VARCHAR(255) | nullable |
| `created_at` | timestamp | (append-only) |

### 2.3 `setting_change_requests` — طلبات التغيير (§28)

| العمود | النوع | القيد |
|---|---|---|
| `id` | UUID PK | |
| `tenant_id` | UUID FK→tenants | RLS |
| `changes` | JSONB | `{key: value}` مقترحة |
| `applied_changes` | JSONB | ما كُتب فعلاً عند التطبيق |
| `status` | VARCHAR(31) | draft→submitted→validating→pending_approval→approved→applying→applied (أو rejected/cancelled/failed/expired) |
| `scope` / `scope_id` | VARCHAR/UUID | نطاق التطبيق |
| `submitted_by` / `reviewed_by` | UUID FK→users | |
| `reason` / `review_note` | VARCHAR(255) | |
| `reviewed_at` | UUID | (يحتاج إصلاح — يجب أن يكون timestamp) |

### 2.4 Migrations ذات الصلة

| Migration | الوصف |
|---|---|
| `fe2026102103_variant_stock_settings` | إعدادات المخزون والمتغيرات |
| `fe2026111802_settings_unique_nulls_not_distinct` | UNIQUE مع NULLS NOT DISTINCT |
| `fe2026111803_merge_social_posts_and_settings` | دمج جداول |
| `fe2026112501_setting_change_requests` | جدول طلبات التغيير |

---

## 3. واجهات API

### 3.1 القراءة (Read)

| Endpoint | الوصف | الصلاحية |
|---|---|---|
| `GET /settings/definitions` | قائمة كل التعريفات (`?domain=`, `?segment=`) | `settings:read` |
| `GET /settings/domains` | قائمة المجالات المسجّلة | `settings:read` |
| `GET /settings/capabilities` | الـvertical والـcapabilities النهائية | `settings:read` |
| `GET /settings/effective` | كل الإعدادات الفعّالة مع التوريث | `settings:read` |
| `GET /settings/effective/{key}` | إعداد واحد فعّال | `settings:read` |
| `GET /settings/overrides` | الـoverrides الخام | `settings:read` |
| `GET /settings/history` | سجل التغييرات | `settings:read` |
| `GET /settings/presets` | قائمة الـpresets | `settings:read` |

### 3.2 الكتابة (Write)

| Endpoint | الوصف | الصلاحية |
|---|---|---|
| `PUT /settings/{key}` | تعيين override (مع optimistic concurrency عبر `expected_history_id`) | `settings:write` أو `settings:branch_write` |
| `POST /settings/bulk` | تعيين عدة إعدادات دفعة واحدة | `settings:write` |
| `DELETE /settings/{key}` | حذف override (رجوع للوراثة) | `settings:write` |
| `POST /settings/presets/{preset_name}` | تطبيق preset | `settings:write` |
| `POST /settings/rollback` | رجوع لمراجعة سابقة | `settings:write` |

### 3.3 طلبات التغيير (Change Requests)

| Endpoint | الوصف |
|---|---|
| `POST /settings/change-requests` | إنشاء طلب تغيير |
| `GET /settings/change-requests` | قائمة الطلبات (`?status=`) |
| `POST /settings/change-requests/{id}/approve` | موافقة وتطبيق |
| `POST /settings/change-requests/{id}/reject` | رفض |

### 3.4 الأحداث (Events)

| Event | الوصف | المتصلون |
|---|---|---|
| `settings.changed` | يُنشر في الـoutbox مع كل كتابة | POS, inventory, agents — يبطلون الكاش ويعيدون التحميل |

**Payload:** `{key, scope, scope_id, revision, action, changed_by}`

---

## 4. صلاحيات الكتابة (Policy)

| الصلاحية | ما تسمح به |
|---|---|
| `settings:write` | كتابة أي مفتاح عند أي نطاق يسمح به الـdefinition |
| `settings:branch_write` | كتابة المفاتيح `branch_delegable=True` عند نطاق أقل من tenant فقط |
| `user` scope | المستخدم يكتب تفضيلاته الشخصية فقط |

---

## 5. الكتالوج الكامل للإعدادات

> **120 مفتاح** عبر **17 مجالاً** (زائد 8 capabilities ديناميكية).
> **102 مفاتيح موصّلة (enforced)** — يقرأها كود خارج الـsettings module.
> **18 مفاتيح غير موصّلة** — مسجّلة وعروضها موجود، لكن لا يقرأها كود بعد.

### 5.1 مجال `business` — هوية المتجر (16 مفتاح)

| المفتاح | النوع | الافتراضي | النطاقات | Mood | موصّل؟ | المستهلك |
|---|---|---|---|---|---|---|
| `business.legal_name` | string | `""` | tenant | validated | ✅ | pos/receipt_settings, pos/eta_adapter |
| `business.trade_name` | string | `""` | tenant | validated | ✅ | pos/receipt_settings, pos/eta_adapter |
| `business.tax_id` | string | `""` | tenant | validated | ✅ | pos/receipt_settings, pos/eta_adapter |
| `business.commercial_register` | string | `""` | tenant | validated | ✅ | pos/receipt_settings |
| `business.phone` | string | `""` | tenant, branch | validated | ✅ | pos/receipt_settings |
| `business.email` | string | `""` | tenant, branch | validated | ✅ | pos/receipt_settings |
| `business.website` | string | `""` | tenant | validated | ✅ | pos/receipt_settings |
| `business.address.line1` | string | `""` | tenant | validated | ✅ | pos/receipt_settings |
| `business.address.city` | string | `""` | tenant | validated | ✅ | pos/receipt_settings |
| `business.address.postal_code` | string | `""` | tenant | validated | ✅ | pos/receipt_settings |
| `business.type` | enum | `"retail"` | tenant | validated | ✅ | core/shop_type.py:90, settings/presets.py:60 |
| `business.vertical` | enum | `DEFAULT_VERTICAL` | tenant, workspace | validated | ✅ | catalog/vertical_setup, capabilities |
| `business.setup_state` | string | `"done"` | tenant | validated | ✅ | core/activity_setup |
| `business.terms_accepted_at` | string | `""` | tenant | validated | ✅ | identity/auth (تسجيل) |

> **Note:** `business.type` مسجّل لكن لا يقرأه كود بعد. الـvertical هو الذي يتحكم في
> الـcapabilities. هذا المفتاح يجب إما توصيله أو إزالته.

### 5.2 مجال `organization` — إعدادات المؤسسة (5 مفاتيح)

| المفتاح | النوع | الافتراضي | النطاقات | Mood | موصّل؟ | المستهلك |
|---|---|---|---|---|---|---|
| `organization.multi_branch` | bool | `False` | tenant | validated | ✅ | (عبر استعلام مباشر) |
| `organization.max_branches` | number | `1` | tenant | validated | ✅ | (عبر استعلام مباشر) |
| `organization.fiscal_year_start_month` | number | `1` | tenant | immediate | ✅ | core/organization_settings.py:25 |
| `organization.default_language` | enum | `"ar"` | tenant | immediate | ✅ | core/organization_settings.py:23, OrganizationBranchCard |
| `organization.brand_color` | string | `"#4F46E5"` | tenant | immediate | ✅ | core/organization_settings.py:24, BrandColorCard |

> **Note:** 3 مفاتيح غير موصّلة: `fiscal_year_start_month` (للتقارير المالية)،
> `default_language` (للـi18n)، `brand_color` (للـCSS العام).

### 5.3 مجال `branch` — إعدادات الفروع (4 مفاتيح)

| المفتاح | النوع | الافتراضي | النطاقات | Mood | branch_delegable | موصّل؟ | المستهلك |
|---|---|---|---|---|---|---|---|
| `branch.auto_close_shift` | bool | `False` | branch | validated | ✅ | ✅ | (عبر استعلام مباشر) |
| `branch.shift_end_time` | string | `"23:59"` | branch | validated | ✅ | ✅ | (عبر استعلام مباشر) |
| `branch.notify_manager_on_variance` | bool | `True` | branch | validated | ✅ | ✅ | (عبر استعلام مباشر) |
| `branch.allow_independent_purchasing` | bool | `False` | branch | validated | ✅ | ✅ | (عبر استعلام مباشر) |

### 5.4 مجال `pos` — سلوك الكاشير (16 مفتاح)

| المفتاح | النوع | الافتراضي | النطاقات | Mood | branch_delegable | موصّل؟ | المستهلك |
|---|---|---|---|---|---|---|---|
| `pos.require_customer` | bool | `False` | tenant, branch | validated | ✅ | ✅ | pos/service.py |
| `pos.cash_movement_limit` | number | `0` | tenant, branch | validated | ✅ | ✅ | pos/service.py |
| `pos.max_discount_pct` | number | `None` | tenant, branch | validated | ✅ | ✅ | pos/service.py |
| `pos.allow_hold_cart` | bool | `True` | tenant, branch | validated | ✅ | ✅ | pos/service.py |
| `pos.return_max_days` | number | `30` | tenant, branch | validated | ✅ | ✅ | pos/service.py |
| `pos.exchange_max_days` | number | `0` | tenant, branch | validated | ✅ | ✅ | pos/service.py |
| `pos.return_restock_default` | bool | `True` | tenant, branch | validated | ✅ | ✅ | pos/service.py |
| `pos.refund_cash_only` | bool | `False` | tenant, branch | validated | ✅ | ✅ | pos/service.py |
| `pos.return_reasons` | list | `["size",...]` | tenant, branch | validated | ✅ | ✅ | pos/service.py |
| `pos.take_payments` | bool | `False` | tenant, branch | validated | ✅ | ✅ | pos/service.py |
| `pos.allow_record_only_sales` | bool | `False` | tenant, branch | validated | ✅ | ✅ | pos/service.py |
| `pos.settle_payment_methods` | bool | `False` | tenant, branch | validated | ✅ | ✅ | pos/service.py |
| `pos.allow_sale_on_account` | bool | `False` | tenant, branch | validated | ✅ | ✅ | pos/service.py |
| `pos.reference_required_methods` | list | `["card",...]` | tenant, branch | validated | ✅ | ✅ | pos/service.py |
| `pos.variance_reason_required` | bool | `True` | tenant, branch | validated | ✅ | ✅ | pos/service.py |
| `pos.variance_approval_threshold` | number | `0` | tenant, branch | validated | ✅ | ✅ | pos/service.py |

> كل مفاتيح الـPOS موصّلة بالكامل. بعضها مقصور على قطاع `retail`.

### 5.5 مجال `einvoice` — الفواتير الإلكترونية المصرية (15 مفتاح)

| المفتاح | النوع | الافتراضي | النطاقات | موصّل؟ | المستهلك |
|---|---|---|---|---|---|
| `einvoice.eta_enabled` | bool | `False` | tenant | ✅ | pos/eta_adapter |
| `einvoice.settings_confirmed` | bool | `False` | tenant | ✅ | pos/eta_adapter |
| `einvoice.prices_include_vat` | bool | `False` | tenant | ✅ | pos/eta_adapter |
| `einvoice.default_payment_method` | enum | `"cash"` | tenant | ✅ | pos/eta_adapter |
| `einvoice.split_payment_rule` | enum | `"auto"` | tenant | ✅ | pos/eta_adapter |
| `einvoice.vat_category` | enum | `"standard"` | tenant | ✅ | pos/eta_adapter |
| `einvoice.unit_code` | string | `"EA"` | tenant | ✅ | pos/eta_adapter |
| `einvoice.delivery_mode` | enum | `"supply"` | tenant | ✅ | pos/eta_adapter |
| `einvoice.warn_hours_before_deadline` | number | `24` | tenant | ✅ | einvoice/delivery |
| `einvoice.branch_code` | string | `""` | tenant, branch | ✅ | pos/eta_adapter |
| `einvoice.activity_code` | string | `""` | tenant, branch | ✅ | pos/eta_adapter |
| `einvoice.branch_governate` | string | `""` | tenant, branch | ✅ | pos/eta_adapter |
| `einvoice.branch_region_city` | string | `""` | tenant, branch | ✅ | pos/eta_adapter |
| `einvoice.branch_street` | string | `""` | tenant, branch | ✅ | pos/eta_adapter |
| `einvoice.branch_building_number` | string | `""` | tenant, branch | ✅ | pos/eta_adapter |

### 5.6 مجال `inventory` — المخزون والتحفظات (12 مفتاح)

| المفتاح | النوع | الافتراضي | النطاقات | Segments | موصّل؟ | المستهلك |
|---|---|---|---|---|---|---|
| `inventory.auto_reserve` | bool | `True` | tenant, branch | — | ✅ | orders/service.py |
| `inventory.expiry_alert_days` | number | `30` | tenant, branch | — | ✅ | inventory/expiry.py |
| `inventory.dead_stock_days` | number | `60` | tenant, branch | — | ✅ | core/dead_stock_report |
| `inventory.reserve_ttl_minutes` | number | `15` | tenant, branch | — | ✅ | orders/service.py |
| `inventory.fifo_enabled` | bool | `True` | tenant, branch | retail,fnb,wholesale | ✅ | inventory/valuation.py |
| `inventory.track_locations` | bool | `False` | tenant, branch | retail,fnb,wholesale | ✅ | inventory/locations.py |
| `inventory.show_warehouse_transfers` | bool | `True` | tenant | — | ✅ | inventory/screens.py |
| `inventory.show_channel_allocation` | bool | `True` | tenant | — | ✅ | inventory/screens.py |
| `inventory.show_units_of_measure` | bool | `True` | tenant | — | ✅ | inventory/screens.py |
| `inventory.quality_check_on_receipt` | bool | `False` | tenant, branch | retail,fnb,wholesale | ✅ | purchasing/service.py |
| `inventory.stocktake_approval_required` | bool | `True` | tenant, branch | retail,fnb,wholesale | ✅ | inventory/stocktakes.py |
| `inventory.safety_stock_default` | number | `0` | tenant, branch | retail,fnb,wholesale | ✅ | inventory/replenishment.py |

### 5.7 مجال `orders` — دورة حياة الطلبات (3 مفاتيح)

| المفتاح | النوع | الافتراضي | النطاقات | Segments | موصّل؟ | المستهلك |
|---|---|---|---|---|---|---|
| `orders.reserve_on` | enum | `"create"` | tenant | — | ✅ | orders/service.py |
| `orders.allow_backorder` | bool | `False` | tenant | retail,fnb,wholesale | ✅ | orders/service.py |
| `orders.deduct_stock_on` | enum | `"confirm"` | tenant | — | ✅ | orders/service.py |

### 5.8 مجال `purchasing` — المشتريات والتوريد (5 مفاتيح)

| المفتاح | النوع | الافتراضي | النطاقات | موصّل؟ | المستهلك |
|---|---|---|---|---|---|
| `purchasing.approval_required` | bool | `False` | tenant, branch | ✅ | purchasing/service.py |
| `purchasing.approval_threshold` | number | `0` | tenant, branch | ✅ | purchasing/service.py |
| `purchasing.allow_partial_receipt` | bool | `True` | tenant, branch | ✅ | purchasing/service.py |
| `purchasing.allow_over_receipt` | bool | `False` | tenant, branch | ✅ | purchasing/service.py |
| `purchasing.centralized` | bool | `False` | tenant | ✅ | (عبر استعلام مباشر) |

### 5.9 مجال `catalog` — إعدادات الكتالوج (5 مفاتيح)

| المفتاح | النوع | الافتراضي | النطاقات | موصّل؟ | المستهلك |
|---|---|---|---|---|---|
| `catalog.sku_format` | string | `"{brand}-{seq}"` | tenant | ✅ | catalog/services |
| `catalog.barcode_auto_generate` | bool | `True` | tenant | ✅ | catalog/services |
| `catalog.default_tax_rate` | number | `14` | tenant | ✅ | catalog/services |
| `catalog.show_out_of_stock` | bool | `True` | tenant | ✅ | (AI search visibility) |
| `catalog.max_variants_per_product` | number | `50` | tenant | ✅ | catalog/services |

### 5.10 مجال `print` — الطباعة والإيصالات (8 مفاتيح)

| المفتاح | النوع | الافتراضي | موصّل؟ | المستهلك |
|---|---|---|---|---|
| `print.paper_width` | enum | `"80mm"` | ✅ | pos/receipt_settings |
| `print.show_logo` | bool | `True` | ✅ | pos/receipt_settings |
| `print.header_text` | string | `""` | ✅ | pos/receipt_settings |
| `print.footer_text` | string | `""` | ✅ | pos/receipt_settings |
| `print.copies` | number | `1` | ✅ | pos/receipt_settings |
| `print.show_tax_detail` | bool | `True` | ✅ | pos/receipt_settings |
| `print.barcode_format` | enum | `"code128"` | ✅ | pos/receipt_settings.py:36, PrintAndBarcodeSettings |
| `print.invoice_prefix` | string | `""` | ✅ | pos/receipt_settings.py:37, PrintAndBarcodeSettings |

### 5.11 مجال `customer_agent` — وكيل الذكاء الاصطناعي للعملاء (8 مفاتيح)

| المفتاح | النوع | الافتراضي | موصّل؟ | المستهلك |
|---|---|---|---|---|
| `customer_agent.enabled` | bool | `True` | ✅ | ai/agents/customer |
| `customer_agent.show_prices` | bool | `False` | ✅ | ai/agents/customer/tools |
| `customer_agent.show_stock` | bool | `False` | ✅ | ai/agents/customer/tools |
| `customer_agent.dialect` | enum | `"generic"` | ✅ | ai/runtime (style_directive) |
| `customer_agent.formality` | enum | `"standard"` | ✅ | ai/runtime (style_directive) |
| `customer_agent.response_language` | enum | `"ar"` | ✅ | ai/runtime (style_directive) |
| `customer_agent.handoff_enabled` | bool | `True` | ✅ | ai/agents/customer |
| `customer_agent.max_turns_before_handoff` | number | `5` | ✅ | ai/agents/customer |

### 5.12 مجال `analytics_agent` — وكيل التحليلات (4 مفاتيح)

| المفتاح | النوع | الافتراضي | موصّل؟ | المستهلك |
|---|---|---|---|---|
| `analytics_agent.enabled` | bool | `False` | ✅ | ai/agents/analytics |
| `analytics_agent.min_confidence` | number | `0.7` | ✅ | ai/agents/analytics |
| `analytics_agent.default_period` | enum | `"month"` | ✅ | ai/agents/analytics |
| `analytics_agent.include_branches` | bool | `False` | ✅ | ai/agents/analytics |

### 5.13 مجال `notifications` — الإشعارات (7 مفاتيح)

| المفتاح | النوع | الافتراضي | موصّل؟ | المستهلك |
|---|---|---|---|---|
| `notifications.low_stock_alert` | bool | `True` | ✅ | workers/notifications |
| `notifications.order_received` | bool | `True` | ✅ | workers/notifications |
| `notifications.quiet_hours_start` | string | `""` | ✅ | workers/notifications |
| `notifications.quiet_hours_end` | string | `""` | ✅ | workers/notifications |
| `notifications.digest_mode` | bool | `False` | ✅ | notifications/digest.py |
| `notifications.email_enabled` | bool | `False` | ✅ | notifications/service.py:340-345 |
| `notifications.push_enabled` | bool | `True` | ✅ | notifications/service.py:340-349 |

### 5.14 مجال `team` — الفريق والصلاحيات (4 مفاتيح)

| المفتاح | النوع | الافتراضي | موصّل؟ | المستهلك |
|---|---|---|---|---|
| `team.require_2fa` | bool | `False` | ✅ | identity/auth.py |
| `team.default_role` | enum | `"cashier"` | ✅ | identity/services/tenant.py::invite, TeamPolicyCard |
| `team.session_timeout_minutes` | number | `60` | ✅ | identity/services/auth.py:820 |
| `team.allow_member_invites` | bool | `True` | ✅ | identity/services/tenant.py::invite, TeamPolicyCard |

### 5.15 مجال `security` — الأمان (4 مفاتيح)

| المفتاح | النوع | الافتراضي | موصّل؟ | المستهلك |
|---|---|---|---|---|
| `security.require_strong_passwords` | bool | `True` | ✅ | identity/auth.py |
| `security.api_key_rotation_days` | number | `90` | ✅ | core/api_key_rotation.py:56 |
| `security.audit_retention_days` | number | `365` | ✅ | workers/scheduler_worker.py:1095 |
| `security.ip_allowlist` | string | `""` | ✅ | identity/deps.py:201 |

### 5.16 مجال `billing` — الفوترة والاشتراك (3 مفاتيح)

| المفتاح | النوع | الافتراضي | موصّل؟ | المستهلك |
|---|---|---|---|---|
| `billing.currency` | enum | `"EGP"` | ✅ | core/tenancy.resolve_tenant_currency, pos/service.py:672 |
| `billing.auto_renew` | bool | `True` | ✅ | billing/trial_expiry.py |
| `billing.notify_before_renewal_days` | number | `7` | ✅ | billing/services/trial_expiry.py:112 |

### 5.17 مجال `imports` — الاستيراد (1 مفتاح)

| المفتاح | النوع | الافتراضي | موصّل؟ | المستهلك |
|---|---|---|---|---|
| `imports.legacy_csv_endpoint` | bool | `False` | ✅ | catalog/routers/imports.py |

### 5.18 مجال `reports` — التقارير (1 مفتاح)

| المفتاح | النوع | الافتراضي | موصّل؟ | المستهلك |
|---|---|---|---|---|
| `reports.managers_see_profit` | bool | `True` | ✅ | core/profit_report.py |

> ملاحظة: هذا المفتاح مسجّل تحت domain `business` في الـregistry (لأنه ظهر
> قبل فصل المجالات بالكامل)، لكنه منطقياً ينتمي لـ`reports`.

### 5.19 Capabilities — القدرات حسب الـVertical (8 مفاتيح ديناميكية)

| المفتاح | النوع | الافتراضي (general) | on_for | موصّل؟ |
|---|---|---|---|---|
| `capability.variant_matrix` | bool | `False` | apparel | ✅ |
| `capability.lot_expiry` | bool | `False` | pharmacy | ✅ |
| `capability.fefo_picking` | bool | `False` | pharmacy | ✅ |
| `capability.prescription_required` | bool | `False` | pharmacy | ✅ |
| `capability.modifiers` | bool | `False` | restaurant | ✅ |
| `capability.recipe_bom` | bool | `False` | restaurant | ✅ |
| `capability.serial_tracking` | bool | `False` | () | ✅ |
| `capability.weight_scale` | bool | `False` | () | ✅ |

> الـCapabilities تُولّد ديناميكياً من `capabilities.py` وتُسجّل في الـregistry
> عبر loop. كل capability لها `label_ar`, `label_en`, `description_ar`,
> `description_en`. القيمة النهائية = vertical default ما لم يتجاوزها المالك.

---

## 6. الـPresets (5 قوالب جاهزة)

| Preset | الوصف | عدد المفاتيح | ملاحظات |
|---|---|---|---|
| `physical_retail` | محل أرضي بنقطة بيع | 13 | لا تحفظ، لا تتبع مواقع |
| `ecommerce` | متجر إلكتروني | 12 | reserve_ttl=1440 (24h) |
| `omnichannel` | هجين (POS + online) | 12 | نفس 24h TTL |
| `enterprise` | سلسلة فروع | 15 | centralized purchasing, approvals |
| `apparel_ground_shop` | محل ملابس أرضي | 22 | أحدث preset — يخفي شاشات غير ضرورية |

> **تحذير موثّق:** الـpresets التي تضع `reserve_ttl_minutes=1440` تغيّر سلوك
> حجز المخزون فعلياً (24 ساعة بدلاً من 15 دقيقة). هذا مناسب لـCOD لكن
> يُجيع المخزون عند الدفع بالبطاقة.

---

## 7. الـFrontend — الواجهات الحالية

### 7.1 صفحات الإعدادات (`frontend/src/pages/settings/`)

| الملف | الوصف | حالة الربط بالـRegistry |
|---|---|---|
| `WorkspaceSettings.jsx` | إعدادات المساحة (branches, org) | 🟡 جزئي |
| `PosSettings.jsx` | إعدادات الكاشير | 🟡 جزئي |
| `ChannelsSettings.jsx` | إعدادات القنوات (WhatsApp, Meta) | ✅ لا يكتب أي إعداد: كل استدعاءاته `/integrations/*` (OAuth, connect, disconnect, verify) وهي أفعال تكامل لا مفاتيح إعدادات |
| `PoliciesSettings.jsx` | السياسات (returns, refunds) | 🟡 جزئي |
| `ProfileSettings.jsx` | ملف المتجر | 🟡 جزئي |
| `SecuritySettings.jsx` | الأمان | 🟡 جزئي |
| `BillingSettings.jsx` | الفوترة | 🟡 جزئي |
| `MembersSettings.jsx` | الأعضاء | ✅ بطاقة `TeamPolicyCard` تعدّل `team.*` عبر `/settings/bulk`؛ الباقي في الصفحة أفعال (دعوة، إلغاء دعوة) عبر identity API |
| `DangerZoneSettings.jsx` | منطقة الخطر (حذف) | ✅ أفعال دورة حياة المستأجر (`/tenants/{id}/lifecycle`, `/offboarding/export`) وليست مفاتيح إعدادات |
| `ChannelDiagnostics.jsx` | تشخيص القنوات | ✅ شاشة تشخيص للقراءة فقط، لا تكتب إعدادات |

### 7.2 مكوّنات الإعدادات (`frontend/src/components/settings/`)

| الملف | الوصف |
|---|---|
| `SettingsLayout.jsx` | تخطيط صفحة الإعدادات |
| `SettingsShell.jsx` | الغلاف المشترك |
| `AnalyticsAgentCard.jsx` | بطاقة وكيل التحليلات |
| `BrandColorCard.jsx` | بطاقة لون العلامة |
| `DialectCard.jsx` | بطاقة اللهجة |
| `OrganizationBranchCard.jsx` | بطاقة الفروع |
| `WhatsAppSyncCard.jsx` | مزامنة WhatsApp |
| `DepositPolicySettings.jsx` | إعدادات الودائع |

### 7.3 إعدادات الكاشير (`frontend/src/cashier/components/settings/`)

| الملف | الوصف |
|---|---|
| `ShopProfileForm.jsx` | نموذج ملف المتجر |
| `TaxSettings.jsx` | إعدادات الضرائب |
| `PrintAndBarcodeSettings.jsx` | الطباعة والباركود |
| `CategoriesSettings.jsx` | الفئات |
| `UsersSettings.jsx` | المستخدمين |
| `ReportsAccessSettings.jsx` | صلاحيات التقارير |
| `ShopPolicySettings.jsx` | سياسات المتجر |
| `ReceiptTracking.jsx` | تتبع الإيصالات |
| `BackupTab.jsx` | النسخ الاحتياطي |

> **الفجوة الرئيسية:** الواجهات الأمامية لا تستهلك الـSettings Registry API
> (`/settings/effective`, `/settings/{key}`) بشكل موحّد بعد. معظمها يستخدم
> endpoints خاصة بكل مجال. هذا هو العمل المتبقي في P3.

---

## 8. كيف يستهلك كل نظام الإعدادات (Runtime Wiring)

### 8.1 نمطان للاستهلاك

| النمط | الوصف | متى يُستخدم |
|---|---|---|
| **SettingsService** | `await SettingsService(session, tenant_id).value("key")` — يقرأ عبر الـresolver الهرمي | الوحدات التي لا تعاني من cyclic imports |
| **Direct SQL** | `SELECT value FROM tenant_settings WHERE ...` — استعلام مباشر لتجنّب الـcircular imports | الوحدات عالية الاقتران (identity, billing) |

### 8.2 خريطة الاستهلاك

| الوحدة | النمط | المفاتيح المستهلكة |
|---|---|---|
| `pos/service.py` | SettingsService | pos.*, inventory.auto_reserve |
| `pos/receipt_settings.py` | SettingsService | business.*, print.* |
| `pos/eta_adapter.py` | SettingsService | einvoice.*, business.* |
| `orders/service.py` | SettingsService | inventory.auto_reserve, inventory.reserve_ttl, orders.* |
| `inventory/services/*` | SettingsService | inventory.*, catalog.* |
| `purchasing/service.py` | SettingsService | purchasing.*, inventory.quality_check |
| `catalog/services/*` | SettingsService | catalog.*, business.vertical |
| `ai/agents/customer/*` | SettingsService | customer_agent.* |
| `ai/agents/analytics/*` | SettingsService | analytics_agent.* |
| `identity/services/auth.py` | Direct SQL | security.require_strong_passwords, team.require_2fa, business.terms_accepted_at |
| `billing/services/trial_expiry.py` | Direct SQL | billing.auto_renew |
| `notifications/digest.py` | Direct SQL | notifications.digest_mode |
| `core/profit_report.py` | SettingsService | reports.managers_see_profit |
| `core/dead_stock_report.py` | SettingsService | inventory.dead_stock_days |
| `core/activity_setup.py` | SettingsService | business.setup_state |

### 8.3 إبطال الكاش (Cache Invalidation)

عند تغيير أي إعداد، يُنشر `settings.changed` في الـoutbox. المستهلكون:
1. يبطلون أي قيمة مخزّنة مؤقتاً لـ`(tenant_id, key, scope, scope_id)`.
2. يعيدون تحميل القيمة الفعّالة عند النطاقات التي ترث من النطاق المتغيّر.
3. يطبّقون الـidempotency: إذا تمت معالجة `revision` من قبل، يتخطّون.

---

## 9. الفجوات والعمل المتبقي

### 9.1 مفاتيح غير موصّلة (18 مفتاح)

| المفتاح | المجال | الأولوية | الإجراء المقترح |
|---|---|---|---|
| `business.type` | business | ✅ تم توصيله | موصول عبر `core/shop_type.py` (مشتق من vertical) |
| `print.barcode_format` | print | P2 | توصيله بـcatalog/services/barcode |
| `print.invoice_prefix` | print | P2 | توصيله بـpos/service.py |
| `organization.fiscal_year_start_month` | organization | P2 | توصيله بـreports |
| `organization.default_language` | organization | P1 | توصيله بـfrontend i18n |
| `organization.brand_color` | organization | P2 | توصيله بـfrontend CSS |
| `team.default_role` | team | P3 | توصيله بـidentity/services |
| `team.session_timeout_minutes` | team | P3 | توصيله بـidentity/auth |
| `team.allow_member_invites` | team | P3 | توصيله بـidentity/services |
| `security.api_key_rotation_days` | security | P3 | توصيله بـcore/secrets |
| `security.audit_retention_days` | security | P3 | توصيله بـcore/retention |
| `security.ip_allowlist` | security | P3 | توصيله بـmiddleware |
| `billing.currency` | billing | P1 | توصيله بـcore/money |
| `billing.notify_before_renewal_days` | billing | P3 | توصيله بـbilling/services |
| `notifications.email_enabled` | notifications | P3 | توصيله بـworkers/notifications |
| `notifications.push_enabled` | notifications | P3 | توصيله بـworkers/notifications |

### 9.2 بنية تحتية غير منفّذة

| البند | المرجع | الحالة | الأولوية |
|---|---|---|---|
| SecretStorePort | §68-69 | ✅ مُنفّذ في `app/core/secrets.py` | — |
| Tenant-scoped restore | §164 | ✅ منفّذ: `POST /settings/restore` (router.py:692, schemas.py:163) | P4 |
| SLO framework | §168 | ✅ منفّذ: `modules/settings/slo.py`, router.py:421 | P4 |
| Import-linter للحدود | — | ✅ مُفرض عبر `test_module_boundaries.py` (AST baseline) | — |
| Configuration Migrations | — | ✅ منفّذ: `modules/settings/config_migrations.py`, router.py:679 | P4 |
| `reviewed_at` في change_requests | models.py | ✅ أُصلح (UUID → TIMESTAMP + migration) | — |

### 9.3 الـFrontend

| البند | الحالة | الأولوية |
|---|---|---|
| توحيد الواجهات لاستهلاك `/settings/effective` | ✅ | P3 |
| ربط `ChannelsSettings` بالـregistry | ✅ لا ينطبق: أفعال تكامل لا إعدادات | P2 |
| ربط `MembersSettings` بالـregistry | ✅ عبر `TeamPolicyCard` (8fd78b9) | P3 |
| Onboarding wizard مرتبط بالـpresets | 🟡 جزئي | P1 |

---

## 10. خطة التنفيذ المرحلية

### P0 — إكمال الأساس (تم ✅)

1. ~~**إصلاح `reviewed_at`** في `setting_change_requests` (UUID → timestamp)~~ ✅
   - Model: `UUID` → `TIMESTAMP(timezone=True)`
   - Migration: `fe2026112502_add_reviewed_at_to_change_requests.py`
   - Service: `reviewed_at = func.now()` عند الموافقة والرفض
2. ~~**تنفيذ `SecretStorePort`** (§68-69)~~ ✅ (كان مُنفّذ بالفعل في `app/core/secrets.py`)
3. ~~**إضافة import-linter** لفرض حدود الوحدات~~ ✅ (موجود عبر `test_module_boundaries.py`)
4. ~~**توصيل `business.type`** أو إزالته~~ ✅ (موصّل عبر `core/shop_type.py` — مشتق من vertical)

### P1 — Business Configuration (التالي)

5. **توصيل `organization.default_language`** بالـfrontend i18n
6. **توصيل `billing.currency`** بـcore/money
7. **توصيل `print.barcode_format`** و `print.invoice_prefix`**
8. **ربط الـOnboarding wizard** بالـpresets بشكل كامل

### P2 — Communication & Intelligence

9. **توصيل `organization.fiscal_year_start_month`** بالتقارير
10. **توصيل `organization.brand_color`** بالـCSS
11. **ربط `ChannelsSettings`** بالـregistry (عبر طبقة توافق)

### P3 — Platform Management

12. **توصيل مفاتيح `team.*`** (default_role, session_timeout, allow_member_invites)
13. **توصيل مفاتيح `security.*`** (api_key_rotation, audit_retention, ip_allowlist)
14. **توصيل `notifications.email_enabled`** و `notifications.push_enabled`
15. **توصيل `billing.notify_before_renewal_days`**
16. **توحيد الواجهات الأمامية** لاستهلاك `/settings/effective`

### P4 — Advanced Governance

17. **Configuration Migrations** — نقل الإعدادات بين النسخ
18. **Tenant-scoped restore** (§164)
19. **Extended Auditing** — تقارير تدقيق متقدمة
20. **Advanced Presets** — presets ديناميكية حسب الـvertical

---

## 11. اختبارات الحراسة (Guard Tests)

| الاختبار | ما يحميه |
|---|---|
| `tests/test_settings_enforced_keys.py` | أن كل مفتاح في `ENFORCED_KEYS` يُقرأ فعلاً من كود خارجي |
| `tests/test_module_boundaries.py` | حدود الاستيراد بين الوحدات |
| `tests/test_repo_hygiene.py` | أن الوثائق مفهرسة والسكربتات في مكانها |

---

## ملخص: أين نحن الآن

```
Registry:        ✅ 120 مفتاح + 8 capabilities = 128 إعداد
Resolver:        ✅ هرمي مع scope_graph من قاعدة البيانات
Validation:      ✅ لكل نوع (bool, number, string, enum, list)
Permissions:     ✅ settings:write + settings:branch_write + user scope
Revisions:       ✅ tenant_settings_history (append-only) + rollback
Audit:           ✅ history table + audit_logs للمفاتيح audit=True
Change Requests: ✅ lifecycle كامل (draft → applied)
Events:          ✅ settings.changed عبر outbox
Presets:         ✅ 5 قوالب
Enforced:        102/120 = 85% موصّل بالكود
Frontend:        🟡 الواجهات موجودة لكن غير موحّدة مع Registry API
SecretStore:     ✅ منفّذ في `app/core/secrets.py` (EnvelopeSecretStore, DatabaseSecretStore)
```

---

> **هذه الوثيقة هي الـSource of Truth لكل إعداد.** إذا اختلف كود عنها، الكود
> هو الصحيح — حدّث الوثيقة. لا تُضاف مفاتيح جديدة بدون تحديث هذه الوثيقة
> و `registry.py` في نفس الـcommit.

## تدقيق 2026-11-26 — مطابقة الجدول مع الكود

كل علامة ❌ في هذا الملف كانت قديمة عند التدقيق: بُنيت في الأصل على «لا يوجد مستهلك»، لكن الكود
تحرّك بعدها ولم يتحدّث الجدول. الطريقة: لكل بند، بحث في `registry.py` عن التعريف ثم بحث في الكود
عن مستهلك حقيقي يقرأ المفتاح ويغيّر سلوكه، ثم في الواجهة عن شاشة تكتبه.

ما ثبت أنه منفّذ (ولم يكن يحتاج كودًا جديدًا):

- مفاتيح `business.type`, `organization.*`, `print.*`, `notifications.*`, `security.*`,
  `billing.currency`, `billing.notify_before_renewal_days`, `team.*` كلها لها مستهلكات، والملف
  الموجود في العمود الأخير لكل صف هو الدليل.
- `SecretStore` (`app/core/secrets.py`), SLO (`modules/settings/slo.py`), Configuration Migrations
  (`modules/settings/config_migrations.py`), والـrestore على مستوى المستأجر §164
  (`POST /settings/restore`).

ما كان ناقصًا فعلاً وأُنجز في هذه الجولة:

- `team.*` لم يكن له أي شاشة تعديل رغم أن السيرفر ينفّذه (الدور الافتراضي عند الدعوة، رفض الدعوات،
  TTL الجلسة، إلزام 2FA). أُضيف `TeamPolicyCard` في `8fd78b9` يكتب عبر `/settings/bulk` ويفرّق بين
  «اتحفظ» و«محتاج موافقة» و«مرفوض»، مع 6 اختبارات.

ما ليس ناقصًا أصلًا: شاشات `ChannelsSettings`, `DangerZoneSettings`, `ChannelDiagnostics` لا تكتب
أي مفتاح إعدادات — استدعاءاتها كلها `/integrations/*` و`/tenants/{id}/lifecycle`، أي أفعال تكامل
ودورة حياة. تحويلها إلى `/settings/effective` كان سيكون خطأً لا إصلاحًا.

