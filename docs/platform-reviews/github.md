# GitHub Production-Readiness Review

- ‫التاريخ: 2026-10-06‬
- ‫المنهج: قراءة فقط عبر REST API مع Accept من نوع application/vnd.github+json، أسماء الأسرار فقط دون أي قيم.‬
- ‫النطاق: المستودع المرتبط فعليا بـ Vercel وRailway، وهو 7ari9aa-bot/system-sales، عبر حساب 7ari9aa-bot.‬

| Field | Value |
|-------|-------|
| repo | 7ari9aa-bot/system-sales |
| visibility | public (confirmed unauthenticated HTTP 200) |
| default_branch | main |
| created | 2026-09-17 |
| last push | 2026-10-06T21:35:26Z |
| language / size | Python / ~8.3 MB |
| collaborators | 1 (7ari9aa-bot) |
| open PRs | 0 |
| workflows | ci, desktop-ci, docker-publish (all active) |
| Actions secrets / variables | 0 / 0 |
| CODEOWNERS | absent (404 on all three locations) |

## ‫ملخص النتائج‬

| # | Finding | Severity | Evidence | Recommended action |
|---|---------|----------|----------|--------------------|
| G1 | Repo is public | critical | unauthenticated `GET /repos/7ari9aa-bot/system-sales` → HTTP 200; `visibility=public` | Switch to private unless an open-source decision is documented |
| G2 | Branch protection off on main | critical | `GET /branches/main/protection` → 404 Branch not protected | Enable protection: required status checks, review rule, no force push |
| G3 | CI failing on main and on recent PR branches | medium | runs list: ci failure on main at 20:48 and 17:48, failures on two seo branches | Fix failing CI before enabling required checks |
| G4 | No CODEOWNERS, single maintainer | info | no CODEOWNERS file anywhere, collaborators count 1 | Add CODEOWNERS and at least one second maintainer |
| G5 | Secret scanning and Dependabot state unverifiable via API | info | `/security-and-analysis` → 404 | Verify both features in repo Settings and enable them |

## ‫G1 — المستودع عام‬

‫أخطر ملاحظة في المراجعة كلها. كود باكند منصة SaaS متعددة المستأجرين متاح للعامة، وتأكدت بذلك بدون أي توكن فأعاد الطلب المجهول 200. التالي مباشرة منه: كل أسماء الوحدات والنقاط ومنطق الأعمال مكشوف، وهو ما يرفع قيمة أي ثغرة لاحقة. لو لا قرار موثق بجعله مفتوح المصدر فالتحويل إلى private هو الإجراء الصحيح فورا.‬

## ‫G2 — حماية الفرع الرئيسي‬

```text
GET /repos/7ari9aa-bot/system-sales/branches/main/protection
404 {"message": "Branch not protected"}
```

‫لا حماية على main إطلاقا: لا فحوصات مطلوبة ولا مراجعات إلزامية ولا منع force push. والدليل العملي أنه سبق دمج PR رقم 2 وهو CI عليه إخفاقات في نفس اليوم. الإجراء: تفعيل الحماية مع الفحوصات المطلوبة backend وfrontend وfrontend-e2e، وقاعدة مراجعة واحدة على الأقل، ومنع الحذف وforce push.‬

## ‫G3 — صحة الـ CI‬

```text
actions/workflows: ci, desktop-ci, docker-publish (active)
total workflow runs: 610
2026-10-06T21:35  ci             (in progress)  main, push
2026-10-06T21:12  ci             failure        seo/static-route-indexability  pull_request
2026-10-06T21:10  docker-publish skipped        main, workflow_run
2026-10-06T20:48  ci             failure        main, push
2026-10-06T19:35  ci             failure        seo/fihrist-search-indexing
2026-10-06T17:48  ci             failure        main, push
2026-10-06T05:49  docker-publish success        main
```

‫الإخفاقات متكررة على main وفروع الـ PR خلال اليوم، وdocker-publish يتخطى تشغيله لأنه مرهون بإنجاز ci. آخر commit على main وهو 6039f92 نتائجه الحالية: frontend ناجح وfrontend-e2e ناجح وbackend قيد التشغيل، وحالة الـ deploy المجمعة ناجحة عبر تكاملات Vercel وRailway. أي أن المشكلة إخفاقات متقطعة في مسار backend وليست تعطلا كاملا. الإجراء: تثبيت الاختبارات قبل فرضها كفحوصات إلزامية في G2.‬

## ‫G4 و G5 — ملكية الكود والميزات الأمنية‬

‫لا يوجد ملف CODEOWNERS في أي من المواقع الثلاثة المعتمدة، والصيانة لشخص واحد، فلا مراجعة مستقلة ولا مالك معلن للأجزاء الحرجة. من ناحية الأسرار: لا يوجد أي Actions secrets أو variables على مستوى المستودع، وهذا إيجابي يعني أن النشر يتم عبر تكاملات المنصات بلا توكنات مخزنة. نقطة security-and-analysis أعادت 404 فتعذر التحقق برمجيا من حالة secret scanning وDependabot، والتحقق اليدوي من صفحة الإعدادات مطلوب مع تفعيلهما إن كانا مطفيين.‬

## ‫قيود المراجعة‬

- ‫رمز الوصول كفى لكل نقاط القراءة، والقيود الوحيدة هي 404 على branch protection لحالة عدم التفعيل نفسها، و404 على security-and-analysis كما هو مشروح.‬

---

‫لم أغيّر أي إعداد.‬
