# Supabase Production-Readiness Review

- ‫التاريخ: 2026-10-06‬
- ‫المنهج: قراءة فقط عبر Management API واستعلامات كتالوج SELECT، بدون أي كتابة أو تعديل.‬
- ‫النطاق: مشروع واحد باسم sales، ref كما في الجدول تحت، عبر `https://api.supabase.com`.‬

| Field | Value |
|-------|-------|
| ref | iixxqitfopsgvaheedlg |
| name | sales |
| region | eu-west-1 |
| status | ACTIVE_HEALTHY |
| database.version | 17.6.1.166 |
| postgres_engine | 17 |
| created_at | 2026-09-17 |

## ‫ملخص النتائج‬

| # | Finding | Severity | Evidence | Recommended action |
|---|---------|----------|----------|--------------------|
| S1 | No scheduled backups and PITR disabled | critical | `GET /v1/projects/{ref}/database/backups` → `pitr_enabled=false`, `backups=[]`, `physical_backup_data={}` | Enable daily backups plus PITR and schedule restore drills |
| S2 | Auth site_url points to localhost, redirect allowlist empty | critical | `config/auth.site_url=http://localhost:3000`, `uri_allow_list=""` | Set the production URL and the redirect allowlist |
| S3 | DB SSL enforcement off and network open to all IPs | medium | `ssl-enforcement.currentConfig.database=false`, `dbAllowedCidrs=["0.0.0.0/0","::/0"]` | Enable SSL enforcement and restrict source CIDRs |
| S4 | No custom SMTP, built-in email rate limit 2 per hour | medium | `smtp_host=null`, `smtp_port=null`, `rate_limit_email_sent=2` | Configure custom SMTP and raise email limits |
| S5 | Weak password policy, no HIBP, no captcha | medium | `password_min_length=6`, `password_hibp_enabled=false`, `security_captcha_enabled=false` | Raise min length to 8 or more, enable HIBP, evaluate captcha |
| S6 | 10 public tables without RLS | info | list below, no tenant_id on them, no anon or authenticated grants | Enable RLS anyway as defense in depth |
| S7 | Tenant RLS enabled and forced on all tenant tables | info | all tenant_id tables have `relrowsecurity=true` and `relforcerowsecurity=true` with at least 1 policy | Keep, and add a CI guard against regressions |
| S8 | Custom login role owner_console bypasses RLS | info | `pg_roles`: `owner_console` with `rolbypassrls=true`, `rolcanlogin=true` | Verify it is really needed, otherwise drop bypassrls |
| S9 | idle_in_transaction_session_timeout is 0 | info | `current_setting('idle_in_transaction_session_timeout')='0'` | Set an explicit timeout value |

## ‫S1 — لا توجد نسخ احتياطية ولا PITR‬

‫هذا أخطر ما في المراجعة. الواجهة رجّعت قائمة نسخ احتياطية فارغة وPITR مقفل، يعني أي حادثة بيانات يعني فقدان كامل من آخر لحظة.‬

```text
GET /v1/projects/iixxqitfopsgvaheedlg/database/backups
{
  "region": "eu-west-1",
  "walg_enabled": true,
  "pitr_enabled": false,
  "backups": [],
  "physical_backup_data": {}
}
```

‫الإجراء المطلوب: تشغيل الجدول اليومي وPITR، ثم تنفيذ اختبار استعادة موثّق، خصوصا أن القاعدة تحتوي جدول restore_test_runs جاهز لهذا الغرض.‬

## ‫S2 — إعدادات البريد والإنتاج‬

‫قيمة site_url لا تزال localhost، وuri_allow_list فارغة. روابط تأكيد البريد واستعادة كلمة المرور ستعمل لكن ستشير إلى جهاز التطوير، فالاستعادة الفعلية للحسابات مكسورة في الإنتاج حاليا.‬

```text
GET /v1/projects/{ref}/config/auth
site_url = http://localhost:3000
uri_allow_list = (empty)
disable_signup = true
external_anonymous_users_enabled = false
mailer_autoconfirm = false
mailer_allow_unverified_email_sign_ins = false
jwt_exp = 3600
refresh_token_rotation_enabled = true
mfa_totp_enroll_enabled = true
```

‫الجوانب الإيجابية هنا جيدة: التسجيل مقفل، تأكيد البريد مطلوب، دوران refresh tokens مفعّل، وTOTP متاح. الإجراء المطلوب: ضبط site_url على دومين الإنتاج وإضافة دومينات الروابط المسموحة.‬

## ‫S3 — TLS وقيود الشبكة‬

```text
GET /v1/projects/{ref}/ssl-enforcement
{"currentConfig":{"database":false},"appliedSuccessfully":true}

GET /v1/projects/{ref}/network-restrictions
{"entitlement":"allowed","config":{"dbAllowedCidrs":["0.0.0.0/0"],"dbAllowedCidrsV6":["::/0"]},"status":"applied"}
```

‫اتصالات PostgREST دائما مؤمنة، لكن الاتصال المباشر بـ Postgres عبر Railway ليس مُلزمًا بـ TLS، والقاعدة مسموعة لكل عناوين الإنترنت. الإجراء المطلوب: تفعيل فرض TLS وتقييد CIDRs على مخارج Railway وVercel.‬

## ‫S4 — SMTP وحدود الإرسال‬

‫لا يوجد SMTP مخصص، فنظام المصادقة يستخدم SMTP المدمج بحد إرسال يبدأ من رسالتين في الساعة كما يظهر في rate_limit_email_sent. هذا يعني عمليا اختناق لعمليات استعادة كلمة المرور في أول يوم حقيقي من الاستخدام. الإجراء: SMTP مخصص مع هوية دومين موثقة.‬

## ‫S5 — سياسة كلمات المرور‬

‫الحد الأدنى 6 محارف فقط بدون قائمة محارف مطلوبة وبدون فحص تسريبات. الإجراء: رفع الحد إلى 8 على الأقل مع تفعيل HIBP، والتقييم اللاحق لـ captcha على نقاط الدخول الحساسة.‬

## ‫S6 — جداول بلا RLS‬

‫استعلام الكتالوج رجّع 10 جداول في public بدون تفعيل RLS، وكلها جداول مرجعية أو تشغيلية:‬

```text
alembic_version, dr_policy, idempotency_keys, outbox_events, permissions,
plans, processed_events, restore_test_runs, role_permissions, roles
```

‫فحص إضافي أخف أنه لا واحد منها فيه عمود tenant_id، وأن صلاحياتها محصورة في أدوار sales_app وowner_console وservice_role، فلا وصول لها عبر anon أو authenticated من الـ Data API. فيبقى الخطر نظري أكثر منه عملي، لكن تمكين RLS عليها يبقى خط دفاع إضافي رخيص.‬

## ‫S7 — تغطية RLS لبيانات المستأجرين‬

‫النتيجة الإيجابية الأهم: كل جداول tenant_id حوالي 150 جدول مفعل عليها RLS ومفروض force مع سياسة واحدة على الأقل لكل جدول، ولا يوجد جدول مفعل بلا سياسات. هذا وضع ممتاز ويستحق حماية بـ CI guard يمنع تراجعها.‬

## ‫S8 و S9 — الأدوار والاتصالات‬

```text
roles with rolbypassrls or rolsuper:
owner_console        bypassrls=true  canlogin=true   (custom)
postgres             bypassrls=true  canlogin=true   (supabase default)
service_role         bypassrls=true  canlogin=false  (supabase default)
supabase_admin       super=true      canlogin=true   (supabase default)
supabase_etl_admin   bypassrls=true  canlogin=true   (supabase default)
supabase_read_only_user  bypassrls=true  canlogin=true  (supabase default)

extensions: pg_stat_statements 1.11, pgcrypto 1.3, plpgsql 1.0,
supabase_vault 0.3.1, uuid-ossp 1.1, vector 0.8.2

max_connections=60, sessions_total=16, sessions_active=1,
statement_timeout=2min, idle_in_transaction_session_timeout=0
```

‫دور owner_console يتجاوز RLS ويمكنه تسجيل الدخول، وهو الدور المخصص الوحيد غير القياسي بهذا الوصف، فيستحق مراجعة تبريره. أما باقي الأدوار فقياسية في Supabase. إعداد idle_in_transaction_session_timeout صفر يعني جلسة معلقة تستطيع حبس أقفال إلى ما لا نهاية، فيفضل ضبطها. الملاحظة المعلومية الأخيرة: audit_log_disable_postgres قيمته true، أي سجل تدقيق GoTrue لا يكتب في Postgres.‬

## ‫قيود المراجعة‬

- ‫رمز الوصول أعطى صلاحية كافية لكل نقاط القراءة المستخدمة، ما عدا عدم وجود نقطة تقرير عن مستخدمين قدماء آخر دخول لهم، فهذه غير متاحة عبر الـ API.‬

---

‫لم أغيّر أي إعداد.‬
