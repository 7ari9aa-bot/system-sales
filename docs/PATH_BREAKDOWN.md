# تقسيم المسارات لحزم عمل — Path Breakdown (v1، معتمد)

‏‫ده الملف المرجعي لتوزيع الوكلاء: كل حزمة هي وحدة تسليم لأجل وكيل واحد، ‏ولها هدف ونطاق واختبارات ومعايير إقفال. ‏الوكيل اللي هيمسك حزمة يقرأ قسمها هنا + القسم المقابل له في docs/ARCHITECTURE_MAP.md قبل ما يكتب سطر.

‏‫قاعدة إلزامية: ممنوع أي وكيل يعدّل خارج نطاق حزمته — واختبار حدود الموديولات (test_module_boundaries) هو الحكم.

## معايير الإقفال الموحدة — Definition of Done (لكل حزمة)

1. كل الاختبارات المستهدفة للحزمة خضرا محليًا، وأي اختبار جديد بيكتبه الوكيل بيمر كمان.
2. كل ملفات suite الخاصة بالنطاق تتجمع بدون أخطاء (collection clean) حتى لو الـDB مش متاح.
3. صفر استيراد cross-module جديد غير مبرر — لو زاد العدد، يزوّد الbaseline مع تعليق مبرر.
4. مفيش TODO ولا كود ميت — والـdocstrings تتحدث عشان تعكس أي تغيير سلوك.
5. تقرير نهائي يغطي كل بنود: متصلح/كان متصلح (بأدلة file:line)/مؤجّل بسبب، + أي تغيير في عقد الـAPI ظاهر للفرونت + أي env var جديد.
6. التقرير بيتكتب في آخر رسالة للوكيل نفسها — مش في ملف، إلا لو الحزمة طالبت بملف صريح.

---

## المسار 1 — الهوية والتعددية (identity)

### 1.1 نواة المصادقة
- الهدف: مفيش إيميل-enumeration ولا timing oracle ولا جلسة بتتحول لدائمة. ‏الـlockout بيفشل open والـrefresh grace window مش بيلغي جلسات الشرعيين.
- النطاق: app/modules/identity/service.py (دوال register, login, refresh, switch_tenant, password reset, verify-email), cookies.py, email_delivery.py, deps.py (فقط get_current_user).
- الاختبارات: test_auth_flow, test_auth_cookies, test_password_reset, test_mfa_login_flow, test_identity_gaps, test_auth_lockout.
- إقفال خاص: اختبار E2E واحد بيمشي login → MFA → refresh → rotate → grace replay → reuse-after-window = revocation.

### 1.2 دورة حياة الـtenant
- الهدف: آلة الحالة مقفولة — استرجاع أو إيقاف بغير platform admin مستحيل، والـsuspended routes gate بيفشل closed بدون ما يقفل أعضاء نشطين.
- النطاق: service.py (TenantLifecycleService + transition + gates), router.py (lifecycle + admin status), bootstrap.py.
- الاختبارات: test_tenant_lifecycle, test_tenant_suspension, test_tenant_restore, test_tenant_bootstrap.
- إقفال خاص: جدول انتقالات كامل مختبر (كل target × كل actor).

### 1.3 الصلاحيات والهيكل
- الهدف: صفر مسار ترقية صلاحيات — الدعوات بخط سلطوي حادي، وجداول الـRBAC المرجعية SELECT فقط.
- النطاق: router.py (hierarchy, locations, workspaces), service.py (invite + role rank), deps.py (require_permission).
- الاختبارات: test_hierarchy_api, test_tenant_and_fts_schema_debt, test_rls_isolation_hardening, test_app_role_function_grants.
- إقفال خاص: مصفوفة دعوات كاملة (كل دور يدعي كل دور) كاختبار بارامتري.

### 1.4 الـMFA والـbreak-glass
- الهدف: محاولات الـTOTP مقيّدة، والـbreak-glass capability شغالة مرة واحدة وقابلة للتدقيق.
- النطاق: app/core/mfa.py, app/core/break_glass.py, وأجزاء الـMFA في service.py.
- الاختبارات: test_mfa_login_flow (جزئي), test_break_glass_redis, test_security_events (لأحداث break-glass).
- إقفال خاص: اختبار إن 5 محاولات TOTP غلط بتقفل الchallenge والقيـد بيتسجل.

---

## المسار 2 — المنصة والإعدادات (platform)

### 2.1 سطح التكاملات والويبهوكس
- الهدف: كل تكامل بيتحقق من توقيعه fail-closed والربط/الفصل قابل للتدقيق.
- النطاق: platform/router.py (integrations + webhook endpoints), integration_verifier.py.
- الاختبارات: test_integration_connection_routes, test_integration_verifier, test_webhook_dispatcher.
- إقفال خاص: كل قناة بيمشي عليها حالات توقيع صحيح/غلط/ناقص.

### 2.2 الـOutbox والـidempotency والتدقيق
- الهدف: مفيش حدث بيتلم ولا بيتكرر، والسجلات فيها source fields سليمة.
- النطاق: platform/router.py (outbox_events, idempotency_keys, audit_logs, security_events), core/idempotency.py (الواجهة فقط).
- الاختبارات: test_outbox_backoff, test_webhook_retry, test_webhook_dlq, test_audit_source_fields, test_security_events, test_security_event_write_paths.
- إقفال خاص: سيناريو إعادة تشغيل متكرر بيثبت الـat-least-once مع idempotent handlers.

### 2.3 الـflags والـdiagnostics والـDR والاسترجاع
- الهدف: الصحة وقرارات الاسترجاع كلها مبنية على فحوصات فعلية مش حالات مخزنة.
- النطاق: platform/flags*, diagnostics, dr, tenant_restore, metrics, saved views.
- الاختبارات: test_flags_metrics, test_metrics_exposition, test_platform_http_surface, test_boot_reconciler, test_tenant_restore, test_database_secret_store.
- إقفال خاص: محاكاة DR drill كاملة على مستوى الاختبار مع نقاط التحقق.

---

## المسار 3 — الذكاء الاصطناعي (ai)

### 3.1 الـgateway والمزودين
- الهدف: مفيش egress برّه النطاق المصرح، والـbreaker بيحول فشل المزود لتدهور مش كارثة، والـusage bucketing مضبوط.
- النطاق: ai/gateway.py, providers*, egress, usage bucket key.
- الاختبارات: test_ai_gateway, test_ai_providers, test_ai_provider_breaker, test_ai_provider_egress, test_ai_usage_bucket_key.
- إقفال خاص: مفاتيح مزودين وهمية في الاختبار ومفيش اتصال شبكة فعلي.

### 3.2 الـruntime والأدوات والموافقات
- الهدف: أي أداة بتمس فلوس أو بيانات ما تتنفذش غير بdecision معتمد، والأخطاء محصورة جوه غلاف الأداة.
- النطاق: ai/runtime, ai/tools*, ai/approvals.
- الاختبارات: test_ai_runtime, test_ai_tools, test_ai_tools_vision, test_ai_tool_error_containment, test_approval_gate, test_approval_binding.
- إقفال خاص: أداة فلوس بترفض تنفيذ بدون approval session صالح.

### 3.3 المعرفة والرؤية
- الهدف: grounding يمنع الإجابات غير المسنودة، وpipeline الvision بيستوعب كل الصيغ.
- النطاق: ai/knowledge*, ai/hooks_rag, vision*.
- الاختبارات: test_ai_knowledge, test_ai_grounding, test_ai_hooks_rag, test_vision_pipeline, test_vision_indexer, test_vision_retrieval, test_vision_reranker, test_vision_verifier.
- إقفال خاص: سؤال بدون مصدر بيرفض بدل ما يتخترع له جواب.

### 3.4 الحوكمة والميزانيات
- الهدف: ميزانية الذكاء صارمة عبر حدود الـtenant مع تفاصيل التكلفة الصحيحة.
- النطاق: ai/guardrails, ai/policy, ai/usage (totals, partitions), evaluation.
- الاختبارات: test_ai_governance, test_ai_cost_guardrail, test_ai_budget_defaults, test_ai_usage_totals, test_ai_usage_partition_shape, test_ai_history_mapping.
- إقفال خاص: محاولة تجاوز ميزانية tenant بتترفض والحدث بيتسجل.

---

## المسار 4 — قلب التجارة

### 4.1 الكتالوج
- الهدف: رسوم بيانية للخيارات بلا دورات، ومعرفات فريدة مضبوطة، واستيراد CSV صحيح ثنائي اللغة.
- النطاق: catalog كامل ما عدا website_platform.py.
- الاختبارات: test_catalog_service, test_catalog_identifiers*, test_catalog_options*, test_csv_import, test_catalog_admin_surface.
- إقفال خاص: استيراد CSV فيه صفوف مكسورة بيرفض جزئيًا مع تقرير صف بصف.

### 4.2 المخزون
- الهدف: الدفتر append-only بتوازن صارم والحجوزات ما بتضيعش ولا بتتعدى.
- النطاق: inventory كامل.
- الاختبارات: test_inventory_service, test_inventory_ledger_invariant, test_inventory_reservation_ledger, test_inventory_reconciliation*, test_inventory_movement_contract, test_reservation_expiry_sweep_wired.
- إقفال خاص: سباق حجزين متزامنين على آخر وحدة — واحد ينجح وواحد يرفض 409.

### 4.3 الأوردرات والفلوس
- الهدف: كل مسار فلوس مرّ على MoneyPort بنفس قواعد التقريب والعملة، والسلسلة من الـcheckout للـrefund idempotent.
- النطاق: orders كامل (money, returns, refunds, shipping events).
- الاختبارات: test_order_service, test_orders_money_path, test_order_fulfillment, test_order_idempotency, test_order_refund_ledger, test_partial_refund_status, test_return_saga, test_checkout_rules, test_order_shipping_event, test_order_reads.
- إقفال خاص: استرجاع جزئي مرتين بنفس الـidempotency key بيرجع نفس النتيجة مش مضاعفة.

### 4.4 نقاط البيع
- الهدف: جلسات الكاش ما بتقفلش غير متوازنة، وكل حركة مربوطة بالجلسة.
- النطاق: pos كامل.
- الاختبارات: test_pos_flow, test_pos_spec.
- إقفال خاص: محاولة بيع بجلسة مقفولة أو غير متوازنة مرفوضة.

---

## المسار 5 — المحادثات

### 5.1 بوابات القنوات
- الهدف: 6 قنوات (WhatsApp, Messenger, Instagram, Telegram, email, webchat) بتوقيع موثق fail-closed وbreaker خروج لكل قناة.
- النطاق: conversations/gateway كامل + router webhook ingress.
- الاختبارات: test_channel_adapters, test_gateway_security, test_whatsapp_fastapi_contract, test_channel_egress_breaker, test_channel_send_breaker, test_channel_sync, test_channel_account_lifecycle.
- إقفال خاص: payload بتوقيع صحيح لمزود مختلف بيرفض عبر القناة الصح.

### 5.2 الـInbox والـread model والـSSE
- الهدف: الـinbox بيتجمع صحيح من الرسائل، والتعيين آمن، وstream الـSSE مصرّف وبيستكمل من الـcursor.
- النطاق: conversations/service (inbox, assignments, reconcile), conversations/router (stream), app/core/redis streams.
- الاختبارات: test_inbox_read_model, test_conversations_stream_auth, test_customer_turn.
- إقفال خاص: عميلين على نفس الـstream بـcursor مختلفين ما بيسرقوش رسائل بعض.

### 5.3 القوالب والوسائط والصوت
- الهدف: دورة حياة القوالب سليمة، والوسايط على الـS3 مع breaker، والصوت الوارد بيعدي الصحة.
- النطاق: conversations/templates.py, media.py, voice.py + gateway voices.
- الاختبارات: test_template_lifecycle, test_media_pipeline, test_media_and_lead_retention, test_voice_inbound.
- إقفال خاص: رفع وسط فاشل بيرجع للـbreaker مش بيشنج الطلب.

---

## المسار 6 — العملاء والنمو

### 6.1 العملاء
- الهدف: حل الهوية والدمج بيحافظ على referents وبيمنع تكرار الهوية، والـ360 كامل.
- النطاق: customers كامل ما عدا meta_oauth.py.
- الاختبارات: test_customers_service, test_customer_360, test_customer_identity_resolution, test_customer_referents, test_customer_merge/CRUD, test_contact_quarantine_surface, test_contact_backfill, test_customers_if_match, test_customers_http_surface.
- إقفال خاص: دمج عميلين متزامنين بنفس الـif-match واحد ينجح.

### 6.2 التسويق والإسناد
- الهدف: الإسناد بيمشي على wire الفلوس الصحيح والـROAS محسوب من touchpoints حقيقية.
- النطاق: marketing كامل (campaign, journey, attribution).
- الاختبارات: test_marketing_service, test_marketing_conversions_api, test_marketing_read_models, test_attribution_views, test_attribution_money_wire, test_roas, test_campaign_fairness.
- إقفال خاص: conversion مربوطة بأكثر من touchpoint بتحسب attribution weights صح.

### 6.3 الشرائح
- الهدف: الـsegment واحد مشترك بين CRM والتسويق والتحليل والـAI، والتكرار المجدول شغال.
- النطاق: segments كامل.
- الاختبارات: test_segments_contract, test_segments_recurring.
- إقفال خاص: segment بشرط ديناميكي بيتحدث membership عند إعادة التقييم.

---

## المسار 7 — سلسلة الحوكمة المالية

### 7.1 الأدلة والقرارات
- الهدف: الأدلة hash-immutable والقرارات آلة حالة صريحة ما بتتخطاش.
- النطاق: evidence كامل + decisions كامل.
- الاختبارات: test_evidence_hashes, test_evidence_decisions_api, test_decision_state_machine.
- إقفال خاص: محاولة تعديل evidence بعد الكتابة بترفض على مستوى القاعدة.

### 7.2 الصلاحيات والتنفيذ
- الهدف: capability بدون lease زمني صالح ما بينفذش، والـEffectLedger بيسجل كل تنفيذ مع reconciliation.
- النطاق: authority كامل + effects كامل.
- الاختبارات: test_authority_service, test_effects_ledger, test_atomic_execution, test_claim_safety_guardrails.
- إقفال خاص: تنفيذين متزامنين بنفس الlease واحد بيكسب والثاني يرفض.

### 7.3 الفلوس والفوترة
- الهدف: الدفتر المزدوج متوازن دايمًا، والفواتير immutable، والـentitlements بوابة فعليًا على كل مزية.
- النطاق: financial كامل + billing كامل.
- الاختبارات: test_financial_ledger, test_invoice_immutability, test_billing_gates, test_billing_metering, test_entitlements, test_tenant_currency*.
- إقفال خاص: أي مسار فلوس بدون ميزان debit=credit بيرفض.

---

## المسار 8 — مستويات القراءة

### 8.1 التحليلات
- الهدف: المتريكس الكنونية متطابقة بين المحركين وربط النوافذ صارم.
- النطاق: analytics كامل.
- الاختبارات: test_analytics*, test_metric_definitions_seed.
- إقفال خاص: مقياس واحد محسوب بمحركين بيرجع نفس الرقم.

### 8.2 الإشعارات
- الهدف: مركز الإشعارات والـdigest بيمتص أي شكل استيراد.
- النطاق: notifications كامل.
- الاختبارات: test_notifications_centre, test_notifications_contracts, test_notifications_digest_import.
- إقفال خاص: digest مكسور التنسيق بيتأرشف مش بيكسر الجدولة.

### 8.3 الـrealtime (فجوة اختبارات معروفة)
- الهدف: يتعمل أول ملف اختبار مخصص للـSSE: auth لكل اشتراك، cursor resume، and backpressure.
- النطاق: realtime كامل + app/core/redis streams.
- الاختبارات: ملف جديد test_realtime_gateway (مطلوب إنشاؤه).
- إقفال خاص: اشتراك من غير صلاحية بيرفض، والـresume بعد قطع بيرجع من نفس النقطة.

---

## المسار 9 — الويب (فجوة اختبارات معروفة)

### 9.1 جسر الـWebsite Platform
- الهدف: provision وSSO وpublish كلهم بعقود موثقة واختبارات من الصفر، ومفاتيح الـtenant مش بتتسرب للفرونت.
- النطاق: modules/website كامل + catalog/website_platform.py.
- الاختبارات: ملف جديد test_website_bridge.
- إقفال خاص: فشل الـplatform الخارجي بيرجع 502 بهيكل الخطأ الموحد مش 500 خام.

---

## المسار 10 — الـcore المشترك

### 10.1 الأمان والتشفير
- الهدف: password hashing وJWT (kid + rotation) وsecrets at rest كلهم قياسيين.
- النطاق: core/security.py, core/secrets.py, core/cookies.py, app/core/config hardening.
- الاختبارات: test_config_hardening, test_jwt_rotation, test_secrets_at_rest, test_password_reset (جزء hashing).
- إقفال خاص: توكن بكid قديم لسه بيتفك مع السر السابق، وبعد window بيرفض.

### 10.2 قاعدة البيانات والتحديد والحدود
- الهدف: GUC بيتحدد per-request صح ورا الـpooler، والـRLS ما بيتدورش، والـpool والحدود متناسقة.
- النطاق: core/db.py, core/tenancy.py, core/middleware.py (concurrency gate), core/net_guard.py.
- الاختبارات: test_db_pool_invariant, test_tenant_concurrency, test_tenant_scope_nesting, test_scope_binding, test_scope_stamp, test_edge_middleware_hardening.
- إقفال خاص: nested tenant scope بيسترجع الخارجي صح حتى مع exception داخلي.

### 10.3 آلات السير
- الهدف: saga وlease وidempotency وguardrails كلهم عقود مقفولة بفشل آمن.
- النطاق: core/saga.py, core/lease.py, core/idempotency.py, core/guardrails.py, core/field_auth.py, core/transitions.py, core/commands.py, core/pagination.py, core/sql.py, core/search.py.
- الاختبارات: test_claim_safety_guardrails (جزئي), test_lease/idempotency coverage الجديدة، plus test_if_match_wave2, test_command_hash.
- إقفال خاص: أي عملية موجّهة بفشل وسيط بترجع للstate السابق بدون partial writes.

### 10.4 الرصد والانضباط
- الهدف: metrics وaudit وopenapi lock وwiring declarations مقفولة بحوكمة.
- النطاق: core/metrics.py, core/audit.py, core/openapi_lock.py, core/observability.py, workers declaration tests.
- الاختبارات: test_metrics_exposition, test_core_audit, test_openapi_lock, test_worker_deployment_declaration, test_no_dead_modules, test_module_boundaries, test_architecture_boundaries, test_wiring.
- إقفال خاص: أي endpoint جديد من غير توثيق OpenAPI معلق بيرفض الـlock.

---

## المسار 11 — العمال والجدولة

### 11.1 الـscheduler والـpools
- الهدف: كل sweeper مسجل وبيشتغل، والـPOOLS موزعة على start commands معلنة.
- النطاق: app/workers كامل.
- الاختبارات: test_scheduler_bootstrap, test_scheduler_rls, test_job_runner, test_worker_shutdown, test_worker_correlation_logging, test_worker_fairness_charge, test_worker_tenant_deferral, test_worker_metrics_counters, test_worker_deployment_declaration, test_partition_maintenance_wired, test_reservation_expiry_sweep_wired.
- إقفال خاص: أي sweeper جديد بدون تسجيل بيرفض اختبار الحوكمة.

---

## المسار 12 — الفرونت

### 12.1 طبقة الداتا والمصادقة
- الهدف: عقد الـapi.js متطابق مع الـbackend (cookies + CSRF + 401/429/403 handling)، وصفحات المصادقة ماشية على العقد الجديد (202 neutral, verify-email).
- النطاق: frontend/src/lib/api.js, AuthContext, ProtectedRoute/Guardian, صفحات Login/Register/ForgotPassword/ResetPassword/VerifyEmail/AcceptInvitation.
- الاختبارات: e2e اختياري — يعتمد على review يدوي + بناء ناجح؛ مفيش unit harness حالي.
- إقفال خاص: فلو register → verify → login → switch-tenant بيمشي على العقد الجديد بالظبط.

### 12.2 جزر الداشبورد والهياكل
- الهدف: كل صفحة إلها skeleton وerror وempty state حقيقي، ومفيش أي رقم مُختلق.
- النطاق: App.jsx, DashboardLayout, Header/Sidebar, dashboard/sections كامل.
- الاختبارات: بناء ناجح + eslint نظيف + مراجعة يدوية للمخرجات.
- إقفال خاص: grep نهائي anti-fake data بيرجع صفر matches.

### 12.3 صفحات الخصائص
- الهدف: صفحات products وorders وinventory وinbox وmarketing وanalytics وcustomers وusage وsettings كلها بتعامل مع عقود الـAPI الفعلية بدون أي mock.
- النطاق: frontend/src/pages (ما عدا المصادقة) + components المتخصصة.
- الاختبارات: نفس منطق 12.2.
- إقفال خاص: كل صفحة عندها حالة loading/error/empty ملموسة في الـcode.

---

## توزيع الموجات

- ‏‏الموجة 0 (شغالة): مراجعة المنصات الأربعة — Supabase ثم Vercel ثم Railway ثم GitHub (توكنز من ملف آمن خارج الريبو).
- ‏‏الموجة 1: 10.1 → 10.2 → 10.3 → 10.4 (الأساس قبل أي حاجة).
- ‏‏الموجة 2: 1.1 → 1.2 → 1.3 → 1.4.
- ‏‏الموجة 3: 2.1 → 2.2 → 2.3 + 11.1.
- ‏‏الموجة 4: 4.1 → 4.2 → 4.3 → 4.4.
- ‏‏الموجة 5: 5.1 → 5.2 → 5.3 + 9.1.
- ‏‏الموجة 6: 3.1 → 3.2 → 3.3 → 3.4.
- ‏‏الموجة 7: 7.1 → 7.2 → 7.3 + 8.1 → 8.2 → 8.3.
- ‏‏الموجة 8: 6.1 → 6.2 → 6.3 + 12.1 → 12.2 → 12.3.
- ‏‏بعد كل موجة: مراجعة شخصية مني لكل تقرير وكيل قبل اعتماد الحزمة، وأي حزمة مرفوضة بتتقفل في موجة إصلاح صغيرة.

‏‫الإجمالي: 36 حزمة عمل، ‏وكل حزمة بوكيل واحد، ‏والإقفال النهائي بمراجعتي.
