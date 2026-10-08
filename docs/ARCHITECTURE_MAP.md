# خريطة المعمارية — Architecture Map

‏‫توليد آلي من قراءة الشيفرة بتاريخ 2026-10-06. ‏كل سطر هنا مقروء من المصدر، مش مستنتج. ‏الجداول مكتوبة بالإنجليزية عشان تفضل قابلة للنسخ من غير ما يلخبط اتجاه السطر، والعربي حوالينها.

## 1 نظرة عامة — System Overview

‫النظام عبارة عن Modular Monolith مكتوب بـ FastAPI، ‏مش microservices. ‏كل الدومينات حية جوه عملية واحدة تحت ‏`/api/v1`‏، ‏والعمال الثقيلين شغالين في عملية منفصلة بنفس الشيفرة.

‫التعددية multi-tenant حقيقية ومقفولة على طبقتين: ‏طبقة التطبيق بتقيّد كل استعلام بـ tenant_id من سياق الطلب، ‏وطبقة Postgres RLS مفعّلة بـ ENABLE و FORCE على كل جدول يحمل tenant_id، ‏وتنفيذها بـ GUC اسمه ‏`app.tenant_id`‏ بيتحدد بـ ‏`SET LOCAL`‏ في كل transaction عشان يشتغل ورا الـ pooler. ‏الـ Boot Reconciler بيفحص ده عند الإقلاع وبيفشل الإقلاع لو ناقص.

‫الحساسية بتعدّي من plane منفصل: ‏الـ Evidence Platform بيخزن الحقائق hash-immutable، ‏والـ Decision Plane بيوثّق كل mutation حساس كصف decision بحالة machine صريحة، ‏والـ Authority Plane بيمنح capability وlease زمنية، ‏والـ Effect Ledger بيسجل التنفيذ الفعلي، ‏والـ Financial Module دفتر مزدوج بمعادلة توازن صارمة.

‫الفعاليات بتخرج من كل دومين كـ outbox rows في نفس الـ transaction، ‏وrelay بيضخها على Redis Streams، ‏ومنها بياخد العمال وطبقة الـ SSE الحية.

‫المصادقة session-based بكوكيز HttpOnly مع CSRF double-submit، ‏والـ JWT بيتدور على refresh، ‏فيه MFA بـ TOTP، ‏وlockout تدريجي على Redis، ‏وbreak-glass مسنود.

‫الفرونت React SPA بـ Vite، ‏بينادي مباشرة على عقود ‏`/api/v1`‏ بنفس شكل الـ error envelope، ‏والفلوس بتنزل Decimal نصوص وممنوع floats.

‫البنية الاجتماعية: ‏backend و frontend و infra و desktop و website-builder في نفس المستودع، ‏والنشر Railway للـ API والـ worker مع Supabase Postgres و Redis.

‫الحجم الحالي: ‏24 موديول دومين، ‏321 endpoint، ‏42 ملف core، ‏83 migration في سلسلة واحدة، ‏249 ملف اختبار.

## 2 خريطة الموديولات — Module Map

‫جدول الموديولات كلها. ‏عمود Endpoints بيشمل الـ routers الثانوية، ‏والـ prefixes كاملة تحت ‏`/api/v1`. ‏ملفات الاختبار أسماء رئيسية مش قائمة كاملة.

| Module | Purpose | Router prefixes | Endpoints | Key services | Tests (main files) |
|---|---|---|---|---|---|
| identity | tenants, users, roles, permissions, auth, MFA, invitations, hierarchy, workspaces, offboarding | /auth, /users, /tenants, /hierarchy, /me, /workspaces, /locations | 36 | IdentityService, bootstrap, deps (require_permission/TenantContext), cookies, email_delivery | test_auth_flow, test_mfa_login_flow, test_jwt_rotation, test_password_reset, test_hierarchy_api, test_tenant_lifecycle, test_identity_gaps |
| platform | integrations, webhooks, notifications, outbox_events, idempotency_keys, audit_logs, feature flags, saved views, metrics, DR, security events, tenant restore | /platform | 31 | PlatformService, flags, diagnostics, dr, integration_verifier, security_events, tenant_restore, metrics | test_platform_http_surface, test_flags_metrics, test_webhook_dispatcher, test_webhook_retry, test_webhook_dlq, test_outbox_backoff, test_integration_verifier, test_security_events |
| ai | agents, tools, prompts, model_configs, knowledge, memories, agent_runs, tool_calls, usage; LLM never touches SQL | /ai | 30 | gateway, runtime, tools, guardrails, policy, approvals, handover, hooks, providers, usage, evaluation, knowledge | test_ai_gateway, test_ai_runtime, test_ai_tools, test_ai_governance, test_ai_budget_defaults, test_ai_cost_guardrail, test_si_agent, test_si_deep, test_vision_pipeline |
| catalog | products, variants, categories, brands, images, prices, identifiers, options graph, CSV imports, website-platform catalog read | /products, /variants, /categories, /brands, /warehouses, /imports, /website-platform | 26 | CatalogService, external imports, website_platform router | test_catalog_service, test_catalog_identifiers, test_catalog_options, test_csv_import, test_catalog_admin_surface |
| customers | customers, identities, addresses, tags, notes, events, contact-data issues, merge, Meta OAuth connect | /customers, /invitations, /integrations | 23 | CustomerService, timeline, meta_oauth | test_customers_service, test_customer_360, test_customer_identity_resolution, test_crm_crud, test_meta_oauth, test_contact_backfill |
| conversations | conversations, messages, inbox read model, assignments, ai_sessions, channel gateway (WhatsApp, Messenger, Instagram, Telegram, email, webchat), templates, voice | /conversations, /inbox, /webchat, /webhooks, /message-templates | 22 | ConversationService, gateway (base/ingest/registry + adapters), templates, policy, media, voice | test_messaging, test_messaging_policy, test_inbox_read_model, test_channel_adapters, test_gateway_security, test_whatsapp_fastapi_contract, test_template_lifecycle, test_voice_inbound, test_media_pipeline |
| orders | orders, order_items, status_history, shipments, payments, refunds, returns, money rules | /orders, /shipments | 15 | OrderService, money, returns, errors | test_order_service, test_order_fulfillment, test_orders_money_path, test_order_refund_ledger, test_checkout_rules, test_return_saga, test_partial_refund_status |
| marketing | campaigns, ad_sets, ads, touchpoints, leads, conversions, attribution, journeys | /marketing, /analytics, /campaigns, /journeys | 17 | MarketingService, campaign, journey, attribution_service, analytics | test_marketing_service, test_marketing_conversions_api, test_attribution_views, test_attribution_money_wire, test_roas, test_campaign_fairness |
| operations | tasks, SLA policies, business calendars, jobs control surface, fairness, SLOs, scheduled jobs, global search | /tasks, /search, /sla, /jobs, /fairness, /slos, /scheduled-jobs | 20 | task_service, sla, slo_service, search | test_sla_clock, test_jobs_views_health, test_job_runner, test_slo_outbox_lag, test_operations_contracts, test_scheduler_bootstrap |
| decisions | Decision Plane: every sensitive mutation mints a durable decision with an explicit state machine | /decisions | 12 | DecisionService (propose, verify, approve, deny, mark_stale) | test_decision_state_machine, test_evidence_decisions_api, test_approval_gate |
| authority | Capability Grants and Authority Leases; proposal/decision/capability/authority/execution boundary | /authority | 11 | AuthorityService, executor | test_authority_service |
| analytics | canonical metric queries, read models, retention, anomalies, maturity, semantic layer | /analytics | 8 | AnalyticsService, compiler, engines, persistence, validators | test_analytics, test_analytics_correctness, test_analytics_guarantees, test_analytics_metric_parity, test_analytics_window_binding |
| financial | double-entry ledger, chart of accounts, strict balance invariant, PaymentPort | /financial | 7 | FinancialService, ports (PaymentPort) | test_financial_ledger |
| notifications | in-app notification centre, unread counts, digest | /notifications | 7 | NotificationService, digest | test_notifications_centre, test_notifications_contracts, test_notifications_digest_import |
| billing | plans, subscriptions, entitlements, usage metering, invoices, webhook endpoints; Stripe dormant until keys | /billing, /webhook-endpoints | 6 | BillingService (require_entitlement gating) | test_billing_gates, test_billing_metering, test_entitlements, test_invoice_immutability |
| evidence | facts hashed at write, deterministic sets, immutable supersession | /evidence | 6 | EvidenceService | test_evidence_hashes, test_evidence_decisions_api |
| segments | one shared entity for CRM/Marketing/Analytics/AI | /segments | 6 | SegmentService | test_segments_contract, test_segments_recurring |
| pos | point-of-sale adapter: registers, sessions, cash movements, sell | /pos | 7 | PosService | test_pos_flow, test_pos_spec |
| privacy | consent, data-subject requests, retention policies | /privacy | 7 | PrivacyService | test_privacy_erasure, test_consent_enforcement, test_retention, test_row_retention_policy |
| realtime | SSE gateway over Redis Streams, read-only, cursor resume | /realtime | 2 | (router only, no service) | none dedicated — SSE auth covered by test_conversations_stream_auth |
| inventory | warehouses, balances, movements, transfers, reservations, reconciliation | /inventory | 5 | InventoryService, reconciliation | test_inventory_service, test_inventory_ledger_invariant, test_inventory_reconciliation, test_inventory_reservation_ledger |
| website | bridge to external Website Platform: provision, SSO session, publish | /website | 5 | client (WebsitePlatformError contract) | none dedicated |
| effects | EffectLedger, ambiguous state, external dispatch, reconciliation | /effects | 4 | EffectLedger | test_effects_ledger, test_atomic_execution |
| automation | tenant-owned versioned workflows and executions | /workflows | 8 | AutomationService (versions, publish, executions) | test_automation_service, test_automation_routes |

‫ملاحظات على الجدول: ‏موديول ‏`automation`‏ بيتعرض تحت prefix ‏`/workflows`‏ مش باسمه. ‏موديول ‏`catalog`‏ فيه router تاني اسمه ‏`website_platform.py`‏ بيبعت GET واحد تحت ‏`/website-platform/catalog/products`‏، ‏وموديول ‏`customers`‏ فيه ‏`meta_oauth.py`‏ بـ endpoints ‏`/integrations/meta/oauth/start`‏ و ‏`/integrations/meta/oauth/callback`‏ — ‏الاتنين محسوبين فوق. ‏الإجمالي 321 endpoint.

## 3 الطبقة المشتركة — core

‫جدول مختصر بكل ملف ودوره في سطر، ‏زي ما الـ docstrings بتقول بالحرف.

| File | Role |
|---|---|
| audit.py | audit writer shared by every module (audit source, request and correlation ids) |
| auth_lockout.py | progressive per-account login lockout, Redis-backed |
| boot.py | Boot Reconciler — fail-closed RLS ENABLE + FORCE verification at startup |
| break_glass.py | break-glass support access with time-boxed grants |
| circuit_breaker.py | async circuit breaker, closed / open / half-open |
| commands.py | command hashing binding decisions to exact payloads |
| config.py | settings (no module docstring; pydantic settings file) |
| consent.py | outbound marketing-consent gate |
| contact_norm.py | canonical contact handles for identity resolution |
| context.py | request-scoped observability contextvars (request_id, correlation_id, actor_kind) |
| currency.py | ISO 4217 facts and quantization |
| db.py | async engine, sessions, tenant GUC binding via SET LOCAL |
| errors.py | domain exception hierarchy and the unified error envelope |
| events/ | event envelope, outbox writer, stream routing |
| fairness.py | tenant fairness budgets against shared pools |
| field_auth.py | field-level authorization |
| guardrails.py | AI guardrails: outbound chain and inbound screen |
| idempotency.py | idempotent writes middleware and If-Match conditional requests |
| ids.py | UUIDv7 generation |
| lease.py | conversation serialization lease |
| metrics.py | Prometheus text exposition |
| mfa.py | TOTP MFA with durable state |
| middleware.py | layered rate limiting, security headers, body size limit |
| model_kit.py | shared ORM building blocks (VersionMixin and friends) |
| model_registry.py | imports every module's models so Base.metadata is complete |
| net_guard.py | SSRF guard for outbound HTTP |
| observability.py | structlog config and request logging middleware |
| openapi_lock.py | published schema drift gate |
| pagination.py | cursor keyset pagination |
| partitioning.py | monthly partitioning of append-only series |
| ratelimit.py | Redis rate limiters |
| redis.py | Redis client factory |
| risk.py | LLM-free risk classifier sizing approvals |
| saga.py | saga / process manager for long-running processes |
| search.py | SearchPort with PostgreSQL FTS implementation |
| search_indexer.py | EventLog consumer for external search engines |
| secrets.py | SecretStorePort, envelope encryption, rotation |
| security.py | JWT and password primitives |
| sql.py | shared SQL fragments |
| storage.py | S3-compatible object storage for channel media |
| tenancy.py | request-scoped tenant context |
| transitions.py | one transition guard for every state machine |

## 4 العمال والجدولة — Workers and Scheduling

‫نقطة الدخول ‏`app/workers/run.py`‏ بتشغّل relay الـ outbox مع البكولات المختارة، ‏والافتراضي كلها في عملية واحدة:

- messages — MessageWorker على stream الرسائل
- notifications — NotificationWorker للتسليم داخل التطبيق
- webhooks — WebhookWorker مع retry بخطوة §24 و DLQ
- campaigns — ‏بكول منفصل لهدف §144 عشان حملة 100k متاخدش بكول الرسائل التفاعلي
- scheduler — SchedulerWorker الـ poller الدائم
- jobs — JobRunner منفّذ سطح تحكم الـ Jobs

‫‏`RetentionWorker`‏ مقصود إنه مش بكول: ‏مفيش producer يوجه له event، ‏وبيتنفّذ بس لما الـ scheduler يعمل sweep اسمه ‏`retention.run`‏ لكل tenant نشط. ‏‏`replay_outbox.py`‏ أمر أوبريتور لاستعادة الـ streams من الـ outbox، ‏‏`inspector.py`‏ أداة فحص وإصلاح الـ DLQ، ‏‏`correlation.py`‏ بيدخل correlation id في لوجات العمال.

‏‫الـ GLOBAL_SWEEPERS في ‏`scheduler_worker.py`‏ — ‏مهام عالمية مش ممكن تمثل كصفوف ScheduledJob لأن الجدول tenant-scoped:

- password_reset_email — ‏كل 5 ثواني
- email_verification_email — ‏كل 5 ثواني
- offboarding.purge — ‏كل ساعة

‫وفوقهم RECURRING_JOBS بتتزرع لكل tenant نشط: ‏إعادة مطابقة الرسائل العالقة، ‏إعادة مطابقة الدفعات العالقة، ‏انتهاء حجوزات المخزون، ‏و ‏`retention.run`.

## 5 الفرونت — Frontend

‫شجرة التوجيه في ‏`frontend/src/App.jsx`‏ مقسومة لثلاث جزر بـ PathRouter حسب المسار. ‏الإجمالي 38 مسار مسمى + ‏catch-all ‏في كل جزيرة:

‫الجزيرة العامة للزوار — ‏كلها ترسم صفحة ‏`Fihrist`‏ الموحدة:

- / و /product و /conversations و /context و /assistant و /automation و /pricing و /security و /privacy و /terms و /contact-sales و /support

‫جزيرة المصادقة:

- /login و /register و /forgot-password و /reset-password و /verify-email و /accept-invitation

‫جزيرة الداشبورد المحمية بـ ProtectedRoute و DashboardLayout:

- /dashboard و /inbox و /customers و /orders و /products و /inventory
- /marketing كـ layout بتحت /marketing (index) و /marketing/audience و /marketing/automation
- /ai و /analytics و /usage و /website
- الإعدادات تحت SettingsLayout: ‏/settings و /settings/channels و /settings/billing و /settings/members و /settings/security و /settings/danger

‫ملفات الصفحات: ‏24 صفحة أعلى مستوى في ‏`src/pages`‏ + ‏11 صفحة تسويقية في ‏`src/pages/fhrist`‏ + ‏3 في ‏`src/pages/marketing`‏ + ‏6 إعدادات في ‏`src/pages/settings`‏ = ‏44 ملف صفحة.

‫طبقة الداتا في ‏`src/lib/api.js`‏ — ‏358 سطر: ‏الجلسة كوكيز HttpOnly والـ JavaScript مش شايفة غير ‏`csrf_token`‏ وبيتردد كـ ‏`X-CSRF-Token`‏ على كل طلب تعديل. ‏فيه auto-refresh واحد مشترك عند 401، ‏خريطة ضيقة لرسائل 403 اللي معناها فعلاً مصادقة ناقصة، ‏كاش in-memory بـ TTL ‏20 ثانية مع ‏`apiCached`‏ و ‏`prefetchDashboard`‏، ‏و ApiError بتحمل code و retryable من الـ error envelope الموحد. ‏الفلوس بتوصل نصوص Decimal وبتتطبع زي ما هي.

‫الـ hooks في ‏`src/hooks`‏: ‏useCustomers و useOrders و useApprovals و useRealData و useSalesStats و useUsageSummary فوق TanStack Query، ‏مع use-mobile و use-size للأدوات.

‫الترجمة: ‏`src/lib/i18n`‏ فيه ‏`ar.js`‏ و ‏`en.js`‏ بـ 626 سطر لكل واحد و ‏I18nProvider ‏في ‏index.jsx‏، ‏وفوقهم ‏`marketing-i18n.jsx`‏ لصفحات الماركتنج و ‏`regional.jsx`‏ للتنسيق الإقليمي.

## 6 التكاملات الخارجية — External Integrations

‫لكل تكامل ملفاته ومتغيراته. ‏القيم بتضبط من ‏`.env.example`‏ في جذر المستودع و core/config.py:

‫‏Meta و Facebook:

- OAuth لتوصيل الصفحة: ‏`app/modules/customers/meta_oauth.py`‏ — ‏متغيرات ‏`META_APP_ID`‏ و ‏`META_APP_SECRET`‏ و ‏`META_OAUTH_REDIRECT_URI`‏ و ‏`META_OAUTH_CONFIG_ID`
- بوابات الرسائل: ‏`app/modules/conversations/gateway/`‏ — ‏adapters لـ whatsapp و messenger و instagram و telegram و email و webchat
- متغيرات القنوات: ‏`WHATSAPP_APP_SECRET`‏ و ‏`WHATSAPP_VERIFY_TOKEN`‏ و ‏`MESSENGER_APP_SECRET`‏ و ‏`MESSENGER_VERIFY_TOKEN`‏ و ‏`INSTAGRAM_APP_SECRET`‏ و ‏`INSTAGRAM_VERIFY_TOKEN`‏ و ‏`TELEGRAM_BOT_TOKEN`‏ و ‏`TELEGRAM_WEBHOOK_SECRET`‏ و ‏`API_PUBLIC_BASE_URL`
- ملاحظة مهمة: ‏متغيرات Meta دي مش موجودة أصلاً في ‏`.env.example`‏ — ‏فجوة موثقة في القسم 8

‫‏Stripe:

- ‏`app/modules/billing/service.py`‏ — ‏قاعدة التهيئة موثقة: ‏التكامل بيتفعّل أول ما المفاتيح تظهر، ‏ولحد ما يحدث الاشتراكات شغالة trial/manual من غير ما تقفل الكور
- متغيرات: ‏`STRIPE_SECRET_KEY`‏ و ‏`STRIPE_WEBHOOK_SECRET`

‫‏Resend للبريد الأمني:

- ‏`app/modules/identity/email_delivery.py`‏ — ‏تسليم دائم بـ retry لحد الانتهاء أو فشل نهائي، ‏التوكن بيتحقق من الـ hash في Postgres
- متغيرات: ‏`RESEND_API_KEY`‏ و ‏`EMAIL_FROM`‏ و ‏`EMAIL_DELIVERY_ENABLED`

‫‏Supabase Postgres:

- التوفير: ‏`backend/scripts/provision.py`‏ — ‏سياسات RLS بـ ENABLE + FORCE ‏على كل جدول يحمل tenant_id، ‏و ‏tenant_users ‏force-exempt، ‏و app role من غير bypassrls
- الفحص عند الإقلاع: ‏`app/core/boot.py`‏ — ‏الـ Boot Reconciler بيمنع الإقلاع لو RLS ناقصة
- الربط per-transaction: ‏`app/core/db.py`‏ bind_tenant بـ ‏`SET LOCAL app.tenant_id`‏
- متغيرات: ‏`DATABASE_URL`‏ و ‏`DATABASE_URL_ADMIN`‏ و ‏`DATABASE_URL_APP`‏ و ‏`DATABASE_URL_APP_ADMIN`

‫‏Redis:

- المصنع: ‏`app/core/redis.py`‏، ‏الحدود: ‏`app/core/ratelimit.py`‏ و ‏`app/core/auth_lockout.py`‏، ‏الـ breaker: ‏`app/core/circuit_breaker.py`‏
- الـ streams هي عصب النظام: ‏relay الـ outbox بيضخ عليها، ‏و ‏`app/modules/realtime/router.py`‏ بيقرأ منها للـ SSE‏، ‏والـ workers كلها consumers
- متغيرات: ‏`REDIS_URL`‏ و ‏`STREAM_MAXLEN`‏ و ‏`CONSUMER_BLOCK_MS`

‫‏تخزين الوسائط S3-compatible: ‏`app/core/storage.py`‏ — ‏متغيرات ‏`S3_ENDPOINT`‏ و ‏`S3_REGION`‏ و ‏`S3_BUCKET`‏ و ‏`S3_ACCESS_KEY_ID`‏ و ‏`S3_SECRET_ACCESS_KEY`

‫‏مزودي الذكاء الاصطناعي: ‏`app/modules/ai/providers.py`‏ و ‏`gateway.py`‏ — ‏مسار OpenAI-compatible عبر Vercel AI Gateway بموديل Qwen للـ Customer Agent، ‏مع embedding بصري من DashScope و reranker من Jina. ‏متغيرات ‏`AI_PROVIDER_PRIMARY`‏ (لهجة الـ API، مش اسم الموديل) و ‏`AI_MODEL_PRIMARY`‏ (اسم الموديل نفسه) و ‏`AI_API_KEY_PRIMARY`‏ و ‏`AI_BASE_URL_PRIMARY`‏ و ‏`EMBEDDINGS_API_KEY`‏ و ‏`AI_EMBEDDING_VISION_*`‏ و ‏`AI_RERANKER_*`. ‏`AI_MODEL_PRIMARY`‏ مطلوب لأي تينانت ملوش صف ‏`model_configs`‏ للـ alias: ‏gateway بيرفض الطلب بصريح العبارة بدل ما يبعت اسم البروفايدر كأنه معرف موديل.


‫‏منصة المواقع الخارجية: ‏`app/modules/website/client.py`‏ — ‏مفتاح الشريك بسيفرك بس مش بيوصل للفرونت. ‏متغير ‏`WEBSITE_PLATFORM_API_KEY`‏ — ‏مش موجود في ‏`.env.example`‏ زي Meta

‫‏قنوات التنبيه: ‏`SMTP_URL`‏ و ‏`SMS_PROVIDER_KEY`‏ و ‏`PUSH_SERVICE_KEY`

‫‏داخلية: ‏`SERVICE_TOKEN_INTERNAL`‏ لوسم automation في التدقيق و admission ‏لـ /metrics، ‏و ‏`SECRETS_MASTER_KEY`‏ و ‏`SECRETS_PREVIOUS_MASTER_KEYS`‏ للتشفير المغلف و الدوران

## 7 تدفّق أمر واحد من أول لآخر — One Command End to End

‫المثال: ‏طلب إنشاء أوردر من الداشبورد. ‏الملفات بالترتيب:

1. ‏الصفحة ‏`frontend/src/pages/Orders.jsx`‏ بتستدعي hook ‏`frontend/src/hooks/useOrders.js`‏ فوق TanStack Query
2. ‏الـ hook بينادي ‏`api`‏ من ‏`frontend/src/lib/api.js`‏: ‏fetch بـ credentials include، ‏عنوان ‏`X-CSRF-Token`‏ من الكوكي غير HttpOnly، ‏ومسار ‏`POST /api/v1/orders`
3. ‏الطلب بيعدي على سلسلة الـ middleware في ‏`backend/app/main.py`‏ من الخارج للداخل: ‏SecurityHeaders ثم CORS ثم RequestID ثم BodySize ثم RateLimit ثم RequestLogging ثم Idempotency — ‏الترتيب ده موثق بتعليق صريح في الملف
4. ‏الـ router في ‏`backend/app/modules/orders/router.py`‏ — ‏الدالة create_order على ‏`POST /orders`‏ مع ‏`Depends(require_permission("orders:write"))`‏ من ‏`backend/app/modules/identity/deps.py`‏ اللي بيبني TenantContext
5. ‏الجلسة على الداتابيز بتتربط بالتينانت: ‏`backend/app/core/db.py`‏ bind_tenant بـ ‏`SET LOCAL app.tenant_id`‏ — ‏من هنا RLS في Supabase بتطبق FORCE على كل استعلام في الـ transaction، ‏والسياسات الأصلية من ‏`backend/scripts/provision.py`‏ ومفحوصة عند الإقلاع بـ ‏`backend/app/core/boot.py`
6. ‏الخدمة ‏`backend/app/modules/orders/service.py`‏ — ‏OrderService.create_order داخل transaction المستدعي والخدمة مش بتـ commit أبدا: ‏تحقق عملة التينانت من ‏`backend/app/core/tenancy.py`‏ و resolve_tenant_currency، ‏رفض عميل blocked عبر CustomerService.get، ‏اختيار المخزن الافتراضي من InventoryService
7. ‏التسعير: ‏قراءة batch للـ variants وسلّم الأسعار من ‏`backend/app/modules/catalog/service.py`‏ — ‏السعر بيتلقط مرة واحدة snapshot ومفيش حاجة بتعيد حسابه من سعر المتغير المتغير
8. ‏الحجز: ‏InventoryService.reserve لكل سطر بترتيب variant_id مش ترتيب السلة عشان قفل ثابت يمنع الـ deadlock، ‏وبعدها صفوف حجز دائمة بـ TTL 15 دقيقة
9. ‏الإدراج: ‏_insert_order بحالة process_state تساوي stock_reserved لأن الحجز فعلًا اتحجز، ‏ومعاه صفوف OrderItem بـ snapshot العنوان والـ SKU، ‏وصف OrderStatusHistory، ‏وقاعدة الفلوس من ‏`backend/app/modules/orders/money.py`‏ — ‏compute_totals بترفض لو المكونات مش مظبوطة
10. ‏الفعالية: ‏add_outbox_event بنوع ‏`order.created`‏ من ‏`backend/app/core/events/`‏ في نفس الـ transaction مع aggregate_version الحقيقي من VersionMixin — ‏لولو ده الـ relay كان بيبعت حاجة متكتبتش
11. ‏الرد للفرونت: ‏مبالغ نصوص Decimal ‏مش floats، ‏بشكل order.id و number و status و grand_total
12. ‏بعد الـ commit: ‏relay الـ outbox بيضخ الحدث على stream ‏`order.events`‏ في Redis، ‏فياخده ‏`realtime/router.py`‏ للـ SSE للداشبورد الحية، ‏وياخده العمال للتسلسلات اللي بعدها زي المخزون والتحليلات

## 8 فجوات الملفات الوثائقية — Documentation Gaps

‫اللي اتكتشف بالقراءة الفعلية، ‏مش تخمين:

‫موديولات من غير package docstring:

- ‏`analytics/__init__.py`‏ — ‏لكن ‏`service.py`‏ موثق كويس جداً بمرجع spec §55-57، ‏فالفجوة شكلية
- ‏`notifications/__init__.py`‏ — ‏والـ service.py موثق
- ‏`realtime/__init__.py`‏ — ‏لكن الـ router.py نفسه موثق توثيق ممتاز بقواعد معمارية صريحة

‫ملفات من غير docstring:

- ‏`backend/app/core/config.py`‏ — ‏أكبر ملف إعدادات في النظام ومن غير سطر توثيق

‫موديولات من غير اختبارات مخصصة:

- realtime — ‏مفيش test_realtime، ‏تغطية المصادقة الوحيدة بتيجي من ‏test_conversations_stream_auth
- website — ‏مفيش أي test_website؛ ‏التغطية غير موجودة على الـ surface الخمسة بتاعته

‫اختبارات رقيقة بالنسبة لأهمية الموديول:

- authority — ‏11 endpoint على حدود الصحة في V12 واختبار واحد فقط ‏test_authority_service
- financial — ‏دفتر القيد المزدوج بمعادلة توازن صارمة واختبار واحد ‏test_financial_ledger
- effects — ‏4 endpoints واختبار واحد ‏test_effects_ledger

‫فجوات في ‏`.env.example`:

- متغيرات Meta الأربعة (‏`META_APP_ID`‏ و `META_APP_SECRET` و `META_OAUTH_REDIRECT_URI` و `META_OAUTH_CONFIG_ID`‏) مش موجودة فيه رغم إن موديول meta_oauth بيقراها من الإعدادات
- ‏`WEBSITE_PLATFORM_API_KEY`‏ مش موجود فيه رغم إن ‏`website/client.py`‏ بيقراه

‫ملاحظات أخرى:

- ‏`docs/BUILD_PLAN.md`‏ مش موجود — ‏خطة البناء عايشة كملفات spec و ADR في ‏`docs/spec`‏ و ‏`docs/adr`
- ‏مجلدات ‏`desktop`‏ و ‏`website-builder`‏ على جذر المستودع بره نطاق الخريطة دي ومش موثقة هنا
- ملفات اختبار تكشف وعي ذاتي بالفجوات: ‏test_no_dead_modules و test_no_dead_core_modules و test_dead_module_wiring و test_module_boundaries و test_architecture_boundaries — ‏المستودع بيفحص نفسه ضد الكود الميت وكسر الحدود
