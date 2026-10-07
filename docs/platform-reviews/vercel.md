# Vercel Production-Readiness Review

- ‫التاريخ: 2026-10-06‬
- ‫المنهج: قراءة فقط عبر REST API، أسماء متغيرات البيئة فقط دون أي قيم.‬
- ‫النطاق: فريق واحد slug كما تحت، وثلاثة مشاريع كلها Vite على Node 24.x.‬

| Field | Value |
|-------|-------|
| team | 7ari9aa-8121 (team_Im3XGxzVs9gGT9RcdefXK5WK) |
| projects | sales-os, fihrist-owner-console, fihrist-owner-console-pro |
| framework | vite on all three |
| nodeVersion | 24.x on all three |
| cron jobs | none (`/v1/cron-jobs` → 404 per project) |

## ‫ملخص النتائج‬

| # | Finding | Severity | Evidence | Recommended action |
|---|---------|----------|----------|--------------------|
| V1 | Supabase management token and admin-auth flags live in frontend project envs | critical | env names `SUPABASE_ACCESS_TOKEN`, `ADMIN_AUTH_DISABLED`, `ADMIN_PASSWORD_HASH` on both owner-console projects; `DATABASE_URL` plain on fihrist-owner-console | Remove management token and DB URL from frontend projects; verify ADMIN_AUTH_DISABLED is not enabled in production |
| V2 | No deployment protection on any project | medium | `ssoProtection=null`, `passwordProtection=null` on all three | Enable Vercel Authentication for previews at minimum |
| V3 | Owner-console projects are not git-linked | medium | deployments carry no git metadata; only sales-os linked to `7ari9aa-bot/system-sales` | Link both console projects to git for traceability and rollback |
| V4 | Deployment history healthy on sales-os, two build errors on console | info | see deployment table below | Keep an eye on console build errors |
| V5 | Sensitive-class vars stored as plain type | info | `ADMIN_PASSWORD_HASH`, `DATABASE_URL` type=plain | Switch credentials to sensitive type |

## ‫V1 — أسرار في مشاريع الواجهة‬

‫أخطر ما ظهر في المنصة. مشروعا لوحة المالك يحملان في متغيراتهما اسم token إدارة Supabase كامل الصلاحيات، إضافة إلى مفتاحي ADMIN_AUTH_DISABLED وADMIN_PASSWORD_HASH، ومشروع واحد يحمل DATABASE_URL. لم أطّلع على أي قيمة ولا أستطيع، لكن الوجود نفسه في مشروع frontend نمط خطر: أي إعادة تسمية متغير ليبدأ بـ VITE_ يدمج قيمته في حزمة المتصفح فورا، وأي تسرّب مستقبلي من البيئة يفضي إلى token إدارة لا يخص الواجهة أصلا. الإجراء المطلوب: إزالة كل ما سبق من مشاريع الواجهة، والاحتفاظ بأسرار الإدارة في الخادم فقط، والتأكد أن ADMIN_AUTH_DISABLED ليس مفعلا في بيئة الإنتاج.‬

## ‫V2 — حماية الـ Deployments‬

‫المشاريع الثلاثة بلا حماية ولا كلمة مرور ولا SSO، فكل روابط الـ preview عامة لأي شخص يحصل على الرابط. الإجراء: تفعيل Vercel Authentication على الـ previews على الأقل.‬

## ‫V3 — ربط Git‬

```text
sales-os                link: github 7ari9aa-bot/system-sales, productionBranch main
fihrist-owner-console   link: none, deployments have no commit sha or branch
fihrist-owner-console-pro  link: none, deployments have no commit sha or branch
```

‫مشاريع اللوحة تنشر يدويا عبر CLI أو API، فلا أثر للـ commit ولا قابلية rollback مربوطة بالمصدر. الإجراء: ربطها بنفس المستودع.‬

## ‫V4 — حالة النشر‬

```text
fihrist-owner-console-pro:  2026-10-06 21:43 READY production
                            2026-10-06 21:33 READY production
                            2026-10-06 21:08 READY production
sales-os:                   2026-10-06 21:35 READY production  main 6039f92
                            2026-10-06 21:12 READY preview     seo/static-route-indexability
                            2026-10-06 20:48 READY production  main ae67adb
fihrist-owner-console:      2026-10-06 01:41 READY production
                            2026-10-06 01:34 READY production
                            2026-10-06 01:29 ERROR production
                            2026-10-06 01:24 ERROR production
```

‫الكل يعمل اليوم بنشرات READY، ومشروع sales-os يبني من الفرع main وفروع seo. مشروع اللوحة سجل بناءين فاشلين في الصباح ثم نجح بعدها، فالمتابعة مستحسنة. الدومينات كلها verified:‬

```text
fihrist.world              (production, sales-os)
www.fihrist.world          redirect to fihrist.world
owner.fihrist.world        (fihrist-owner-console)
fihrist-owner-console-pro.vercel.app
```

## ‫V5 — أنواع المتغيرات‬

‫ملاحظة معلومية: ADMIN_PASSWORD_HASH وDATABASE_URL مخزنان بنوع plain، أي قراءتهما نصا لمن يملك توكن بواجهة الـ API، بينما SUPABASE_ACCESS_TOKEN فقط بنوع sensitive. يفضل توحيد كل الأسرار على sensitive. بقية الملاحظات الجيدة: gitForkProtection مفعّل، لا cron jobs، nodeVersion 24.x حديث، وautoExposeSystemEnvs قياسي.‬

## ‫قيود المراجعة‬

- ‫نقطة `/v13/deployments` رفضت الاستدعاء برسالة Invalid API version، فاستخدمت `/v6/deployments` كبديل.‬
- ‫قيم متغيرات البيئة غير مقروءة عمدا، فالتقييم مبني على الأسماء والأنواع والأهداف فقط.‬

---

‫لم أغيّر أي إعداد.‬
