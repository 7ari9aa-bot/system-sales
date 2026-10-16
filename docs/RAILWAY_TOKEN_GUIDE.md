# دليل توكن Railway الجديد — إمكانياته وطريقة استخدامه

التوكن: `1bfbf228-…` (صلاحية على مستوى المشروع — وليس مستوى الحساب)
المشروع: `sales-os` → `6e5ebff6-05d8-4794-a270-1e0e215eac09` · بيئة الإنتاج: `12129ac8-2fcd-4495-a7f7-d18a3b8c919f`
الخدمات: `api` = `5bfe87f8…` · `workers` = `698f7486…` · `redis` = `2c2a7223…` · `clamav` = `506a363b…`

---

## ما الذي يقدّره التوكن (مُثبت بالتجربة)

### 1. قراءة كل شيء
```bash
export RAILWAY_TOKEN='1bfbf228-dbc5-4f3c-8820-e02738beedf6'

# متغيرات أي خدمة (بالقيم كاملة — هذا التوكن يقرأ القيم، القديم كان يحجبها)
curl -s -X POST https://backboard.railway.app/graphql/v2 \
  -H "Authorization: Bearer $RAILWAY_TOKEN" -H "Content-Type: application/json" \
  -d '{"query":"{ variables(projectId: \"6e5ebff6-05d8-4794-a270-1e0e215eac09\", environmentId: \"12129ac8-2fcd-4495-a7f7-d18a3b8c919f\", serviceId: \"5bfe87f8-5cf7-42f8-af69-54394522b192\") }"}'

# قائمة الخدمات / النشرات (deployments) مع حالتها وزمنها
```

### 2. كتابة متغيرات البيئة (Environment Variables)
```graphql
mutation ($input: VariableUpsertInput!) { variableUpsert(input: $input) }
# input = { projectId, environmentId, serviceId, name, value, skipDeploys: false }
```
⚠️ أهم درس: **`projectId` إلزامي داخل الـinput** — نسيه هو سبب رسالة
`Problem processing request` في كل المحاولات الأولى.
`skipDeploys: false` يعني أن Railway يعيد نشر الخدمة تلقائياً بعد التغيير.

### 3. تعديل إعدادات الخدمة (المصدر، أوامر التشغيل، سياسات إعادة التشغيل…)
```graphql
mutation ($input: ServiceInstanceUpdateInput!, $environmentId: String!, $serviceId: String!) {
  serviceInstanceUpdate(environmentId: $environmentId, serviceId: $serviceId, input: $input)
}
# مثال: source: { image: "clamav/clamav:latest" }
```

### 4. إنشاء/حذف خدمة
```graphql
mutation { serviceCreate(input: { projectId: "…", name: "clamav" }) { id name } }
mutation { serviceDelete(id: "…") }
```

### 5. سطر أوامر Railway (CLI)
```bash
railway api '{ deployments(input: { projectId: "…", environmentId: "…" }) { edges { node { status createdAt } } } }'
```
الـ`railway api` يعمل بالتوكن، أوامر الحساب (`whoami`, `add`) لا تعمل — لأن التوكن
محدود بالمشروع وليس بحساب كامل.

---

## ما الذي لا يقدّره التوكن (مُثبت بالتجربة)

| العملية | النتيجة |
|---|---|
| `me` / `whoami` (بيانات الحساب) | مرفوضة — التوكن مشروع-محدود |
| `railway add --image` (إنشاء خدمة صورة من CLI) | مرفوض — يحتاج صلاحية حساب |
| `templateDeployV2` (نشر قالب = إنشاء **نشر/deployment**) | يرجع نجاحاً شكلياً لكنه لا ينتج أي deployment |
| تشغيل deployment جديد لخدمة صورة جاهزة | لا يوجد mutation ينشئ deployment لخدمة صورة — النشر الحقيقي من الداشبورد فقط |

**الخلاصة**: التوكن يقرأ ويكتب الإعدادات، لكن **تشغيل أول deployment لخدمة
صورة (مثل clamav) يبقى خطوة الداشبورد الوحيدة**.

---

## الوضع الحالي بعد الاستخدام الفعلي للتوكن

- خدمة `clamav` أعيد إنشاؤها (الـid القديم `ffd91197…` حُذف أثناء التجارب،
  الجديد `506a363b-5ba1-46cf-8f58-c4c94070509e`) والمصدر محفوظ فعلاً:
  `clamav/clamav:latest` — لكن لا يوجد deployment بعد.
- متغيرات `api` مؤكدة بالقراءة الراجعة: `AI_VOICE_AUDIO_INPUT=true`،
  `MEDIA_SCANNER_HOST=clamav.railway.internal`، `AI_EMBEDDING_VISION_API_KEY` مضبوط.
- الخطوة الوحيدة المتبقية للفحص: افتح خدمة `clamav` في الداشبورد → اضغط
  **Deploy** (المصدر جاهز). أول ما تبني الصورة وتشتغل، بوابة فحص الصور
  والصوت تُفتح تلقائياً في الكود.

## 🔐 أمن التوكن
هذا التوكن قادر على تعديل إعدادات الإنتاج بالكامل — **لا تشاركه في أي محادثة
أو مستودع**، وإن ظهر في أي مكان عام دوّره فوراً من Railway → Account Settings → Tokens.
