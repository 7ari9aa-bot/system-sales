# Railway Production-Readiness Review

- ‫التاريخ: 2026-10-06‬
- ‫المنهج: قراءة فقط عبر GraphQL v2، أسماء المتغيرات فقط دون أي قيم.‬
- ‫النطاق: مشروع sales-os ببيئة إنتاج واحدة، عبر `https://backboard.railway.app/graphql/v2`.‬

| Field | Value |
|-------|-------|
| project | sales-os (6e5ebff6-05d8-4794-a270-1e0e215eac09) |
| environment | production (12129ac8-2fcd-4495-a7f7-d18a3b8c919f) |
| services | redis, api, workers |
| builder | RAILPACK on all three |
| source repo | 7ari9aa-bot/system-sales on api and workers |
| domain | api-production-81629.up.railway.app → port 8080 (api only) |

## ‫ملخص النتائج‬

| # | Finding | Severity | Evidence | Recommended action |
|---|---------|----------|----------|--------------------|
| R1 | No volumes while redis runs with appendonly yes | medium | project volumes list empty; redis startCommand uses `--appendonly yes` | Attach a volume to redis or accept cache-only semantics explicitly |
| R2 | Single replica per service, region unset, no worker healthcheck | medium | `numReplicas=null`, `region=null`, workers has no `healthcheckPath` | Pin a region, evaluate 2 replicas for api, add worker health checks |
| R3 | Restart policy ON_FAILURE with max 10 retries everywhere | info | `restartPolicyType=ON_FAILURE`, `restartPolicyMaxRetries=10` | Good default, keep |
| R4 | api preDeploy runs migrations, healthcheck on /healthz | info | `preDeployCommand=["alembic upgrade head"]` | Good pattern, keep |
| R5 | Credential-class variables present by name only, DEBUG flag exists | info | names `JWT_SECRET`, `SECRETS_MASTER_KEY`, `SERVICE_TOKEN_INTERNAL`, `S3_SECRET_ACCESS_KEY`, `DEBUG` | Verify DEBUG=false and CORS_ORIGINS production values |

## ‫R1 — Redis بلا تخزين دائم‬

‫قائمة volumes للمشروع كلها فارغة، وفي نفس الوقت أمر تشغيل redis يفعّل appendonly، وهذه إشارة نية حفظ البيانات تقود إلى تناقض عملي: أي إعادة نشر أو إعادة تشغيل تمسح ما كتبه redis لأن الـ AOF على قرص مؤقت. لو redis مجرد cache فالأمر مقبول لكن يفضل إسقاط appendonly لتوثيق السلوك، ولو فيه صفوف انتظار أو حالة حية فلازم ربط volume فورا.‬

```text
serviceInstance redis:
startCommand: sh -c 'redis-server --requirepass "$REDIS_PASSWORD" --appendonly yes'
project volumes: (none)
```

## ‫R2 — التوبولوجيا والتشغيل‬

```text
api:      startCommand: sh -c 'uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 2'
          preDeployCommand: alembic upgrade head
          healthcheckPath: /healthz
          numReplicas: not set (1), region: not set
workers:  startCommand: python -m app.workers.run
          healthcheckPath: (none)
          numReplicas: not set (1), region: not set
redis:    no healthcheck, numReplicas: not set (1), region: not set
```

‫كل خدمة تعمل بنسخة واحدة وبدون منطقة مثبتة صراحة، والـ workers بلا أي فحص صحة. للإنتاج الحقيقي يفضل تثبيت المنطقة، وتقديم عدد النسخ للـ api إلى اثنين على الأقل مع فحص صحة للـ workers.‬

## ‫R3 و R4 — سياسة الإعادة والترحيلات‬

‫سياسة ON_FAILURE بحد 10 محاولات إعادة تشغيل مطبقة على الخدمات الثلاث، وهذا افتراضي سليم. نمط preDeploy على api ينفذ ترحيلات alembic قبل تشغيل الإصدار الجديد، وهذا هو الشكل الصحيح، مع ملاحظة أن الـ workers تشترك في نفس الكود فلا بد أن الترحيلات متوافقة مع الإصدارين أثناء النشر.‬

## ‫R5 — أسماء المتغيرات‬

‫لم أقرأ أي قيمة، الأسماء فقط. لا يوجد متغيرات مشتركة على مستوى البيئة، كل شيء على مستوى الخدمة.‬

```text
redis:    REDIS_PASSWORD, REDIS_URL
api:      DATABASE_URL, DATABASE_URL_ADMIN, DATABASE_URL_APP, DATABASE_URL_APP_ADMIN,
          JWT_SECRET, SECRETS_MASTER_KEY, SERVICE_TOKEN_INTERNAL, S3_ACCESS_KEY_ID,
          S3_BUCKET, S3_ENDPOINT, S3_REGION, S3_SECRET_ACCESS_KEY, S3_SIGNED_URL_TTL_SECONDS,
          CORS_ORIGINS, DEBUG, EMAIL_DELIVERY_ENABLED, EMAIL_DELIVERY_STRICT, ENVIRONMENT,
          FRONTEND_PUBLIC_URL, INSTAGRAM_APP_SECRET, INSTAGRAM_VERIFY_TOKEN,
          MESSENGER_APP_SECRET, MESSENGER_VERIFY_TOKEN, META_APP_ID, META_APP_SECRET,
          META_OAUTH_REDIRECT_URI, REDIS_URL, WEBSITE_PLATFORM_API_URL,
          WEBSITE_PLATFORM_STUDIO_URL
workers:  نفس مجموعة api بدون متغيرات META وINSTAGRAM وMESSENGER وWEBSITE_PLATFORM
```

‫نمط مفصولة DATABASE_URL_ADMIN عن DATABASE_URL_APP إيجابي ويوحي بفصل صلاحيات قاعدة البيانات. المطلوب تأكيد قيمتي DEBUG وCORS_ORIGINS في الإنتاج فقط عبر الواجهة، فهما خارج نطاق هذه المراجعة.‬

## ‫حالة النشر‬

```text
2026-10-06 21:35  api + workers  SUCCESS   Merge pull request #2
2026-10-06 20:48  api + workers  REMOVED   superseded
2026-10-06 17:48  api + workers  REMOVED   superseded
```

‫آخر نشر ناجح على مستوى الخدمتين، والإصدارات الأقدم superseded كالمعتاد. redis لا تظهر له عمليات نشر لأنه يعتمد صورة جاهزة.‬

## ‫قيود المراجعة‬

- ‫قيم المتغيرات مقصودة من غير القراءة، فالتقييم على الأسماء.‬
- ‫حقلي state وsizeBytes غير متاحين على نوع Volume في المخطط الحالي، لكن غياب أي volumes مؤكد من قائمة المشروع.‬

---

‫لم أغيّر أي إعداد.‬
