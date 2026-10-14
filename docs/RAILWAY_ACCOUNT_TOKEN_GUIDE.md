# دليل توكن Railway — الحساب الكامل

التاريخ: 2026-10-15
النطاق: توكن وصول بمستوى الحساب الكامل (كل المشاريع). هذا الملف يوثق طريقة الاستخدام الصحيحة والدروس المستخلصة من الاستخدام الفعلي. **قيمة التوكن لا تُكتب هنا أبدًا.**

## 1) الصيغة العامة

كل النداءات إلى الـ GraphQL API على العنوان:

```
https://backboard.railway.app/graphql/v2
```

مع ترويسة الحمل:

```
Authorization: Bearer <TOKEN>
Content-Type: application/json
```

الجسم دائمًا JSON فيه حقلين: query و variables.

## 2) غرائب هذا التوكن (مؤكدة بالتجربة)

- `me` (بيانات صاحب الحساب) يرفضه بـ Not Authorized — التوكن يعمل على الاستعلامات المُسندة بالمعرّفات، لا على اكتشاف الهوية.
- `deploymentCreate` غير موجودة في المخطط الحالي. النشر يتم بـ `serviceInstanceDeploy` وهي ترجع Boolean فقط.
- `variables` استعلام على الجذر (ليست حقلًا داخل ServiceInstance) ويتطلب projectId مع serviceId و environmentId.
- `serviceInstanceLimitsUpdate` و `variableUpsert` و `variableDelete` كلها تأخذ كائن input واحد، لا وسيطات مباشرة.
- حقول الشبكة القديمة (tcpProxies) أُزيلت من ServiceInstance — الشبكة الداخلية تلقائية عبر المنفذ المستمع، والاسم الداخلي هو `<service>.railway.internal`.

## 3) تسلسل الاستخدام العملي (كما نفّذ بالحرف)

الاستكشاف:

```
query($p: String!) { project(id: $p) { id name
  environments { edges { node { id name } } }
  services { edges { node { id name } } } } }
```

قراءة خدمة:

```
query($s: String!, $e: String!) {
  serviceInstance(serviceId: $s, environmentId: $e) {
    hasEverDeployed
    latestDeployment { id status createdAt }
    source { image }
    startCommand
  }
}
```

قراءة متغيرات خدمة:

```
query($s: String!, $e: String!, $p: String!) {
  variables(serviceId: $s, environmentId: $e, projectId: $p)
}
```

النشر:

```
mutation($s: String!, $e: String!) {
  serviceInstanceDeploy(serviceId: $s, environmentId: $e)
}
```

رفع الذاكرة:

```
mutation($i: ServiceInstanceLimitsUpdateInput!) {
  serviceInstanceLimitsUpdate(input: $i)
}
# i = { serviceId, environmentId, memoryGB, vCPUs }
```

كتابة/حذف متغير:

```
mutation($i: VariableUpsertInput!) { variableUpsert(input: $i) }
mutation($i: VariableDeleteInput!) { variableDelete(input: $i) }
# i = { projectId, environmentId, serviceId, name, value }
```

لوجات نشر:

```
query($d: String!) { deploymentLogs(deploymentId: $d, limit: 200) { message } }
```

إيقاف نشر:

```
mutation($d: String!) { deploymentStop(id: $d) }
```

## 4) ما نُفّذ بهذا التوكن يوم 2026-10-15

1. تحقق التوكن واكتشاف مشروع sales-os وخدمته الخمس (redis, clamav, api, workers, والبقية).
2. خدمة clamav كانت معرفة بصورة `clamav/clamav:latest` ولم تُنشر قط (hasEverDeployed=false) — نُشرت بـ serviceInstanceDeploy ووصلت SUCCESS.
3. اكتُشف أن clamd لا يبدأ إطلاقًا. التشخيص على ثلاث مراحل:
   - المرحلة أ: صفر سطور من clamd. أُضيفت متغيرات إعدادات الصورة الرسمية لفرض اللوج على stdout.
   - المرحلة ب: ظهر الخطأ الحقيقي — الصورة تنقل لاحقة المتغير حرفيًا، فأسماء بأحرف كبيرة كلها مثل `CLAMD_CONF_LOGFILE` تكتب خيار `LOGFILE` المجهول وتكسر الملف. الصواب الأسماء بنفس حالة الخيار: `CLAMD_CONF_LogFile` و `CLAMD_CONF_LogTime` و `CLAMD_CONF_Foreground`.
   - المرحلة ج: بعد صلاح الإعداد، clamd ما زال يُقتل صامتًا قبل أي سطر. السبب: سقف ذاكرة الخطة HOBBY هو 1GB لكل خدمة، وتحميل قاعدة البصمات الكاملة (~3.6 مليون بصمة) يحتاج ~1.5GB — القتل حاصل داخل الحاوية الحية بلا أي سجل.
4. أُوقفت النشرة بـ deploymentStop لإيقاف حرق رصيد الاستخدام، والخدمة باقية معرفة ومضبوطة.

## 5) الخلاصة التشغيلية لخدمة الفحص

- الحاجز الوحيد الآن هو سقف ذاكرة الخطة، ليس إعدادًا ولا كودًا.
- عند ترقية الخطة إلى Pro (سقف 8GB): رفع الخدمة إلى 2GB/1vCPU ثم serviceInstanceDeploy — ستعمل مباشرة لأن كل الإعدادات جاهزة.
- حتى ذلك الحين يبقى مسار صور العملاء في الـ AI مغلقًا fail-closed — سلوك مقصود وآمن، وليس عطلًا.

## 6) الأمان

- هذا التوكن بمستوى الحساب: يقرأ ويكتب وينشر ويوقف كل المشاريع. ممنوع كتابته في أي ملف أو كود أو زر موعد.
- استُخدم من الطرفية مباشرة فقط في جلسة واحدة موثقة أعلاه.
- **يجب تدويره فورًا بعد انتهاء الحاجة** من لوحة Railway (Account Settings → Tokens)، ومعه التوكن القديم المُحدد النطاق المذكور في سجل المخاطر.

المراجع: docs/RISK_REGISTER.md (سجل التوكنات)، docs/RUNBOOK.md.
