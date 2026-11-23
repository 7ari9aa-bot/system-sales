# اختبارات المتصفح (frontend-e2e): الحالة المقاسة

اللي تحت كله من تشغيل حقيقي على الفرع `main` في ٢٣ نوفمبر ٢٠٢٦، مش من التقرير.

## التشغيل

```
npm run build            # نجح: 137 صفحة prerender
npx playwright install chromium
npx playwright test --workers=1
```

## أول سبب مؤكد للإخفاق

`e2e/facebook-messages.spec.js` كان بيفتح `/facebook/messages` وبيتوقع صفحة بريد الصفحة
(`data-testid="facebook-messages"`). الصفحة دي **مش موجودة** خلاص: `src/App.jsx` بيوجّه
`messages` و`messages/:threadId` إلى `FacebookMessagesRedirect`، اللي بيحوّل على
`/inbox?channel=messenger`، لأن ماسنجر بقى قناة مستقلة بصندوقها (وده كان مطلب التقرير نفسه).

يعني الاختبار كان بيختبر صفحة اتشالت بالتصميم، وكان بيفشل ٤ مرات في كل تشغيل (و٣ محاولات لكل
اختبار). **اتصلح**: الاختبارات الأربعة بقت تتأكد من السلوك الحقيقي — الرابط القديم يوصل لصندوق
ماسنجر، وصندوق المحادثات بيعرض المحادثات، والصندوق الفاضي مابيسيبش الصفحة بيضاء. أربعة من أربعة
نجحوا في تشغيل منفصل (`--workers=1`, 4.2s).

## اللي لسه بيفشل، وسببه المقاس

شغّلت الملفات لوحدها ببطء (`--workers=1`) عشان أفصل عطل حقيقي عن ضغط التشغيل المتوازي:

| الملف | النتيجة | السبب |
|---|---|---|
| `facebook-pages.spec.js` | ٨ نجحوا، ٣ فشلوا | التغذية مابتوريش التعليق («how much?»)، ومفيش زرار «Reply» ولا «Message privately» — الاختبار بيفترض إن التعليقات بتيجي مع المنشورات، والواجهة بقت بتجيبها بطريقة تانية |
| `icon-buttons-named.spec.js` | ٢٨ نجحوا، ١ فشل | عدّاد فوق ٩٩ مش متقفّل زي ما الشارة بتقفل |
| `facebook-messages.spec.js` | ٤/٤ بعد الإصلاح | — |

وفي تشغيل كامل بـ`fullyParallel` على ٤٧٤ اختبار في الساندبوكس: ٩٧ نجحوا و٣٥٤ فشلوا و٢٣ اتخطّوا
في ٦.١ دقيقة. الجزء الأكبر من الفشل مش عطل صفحة: الـworker بيخلص وقته مع تشغيل ٤٧٤ متصفح بالتوازي،
وكمان ظهرت أخطاء `browserContext.close: ENOENT ... test-results/.playwright-artifacts` لما اشتغل
تشغيلين في نفس الوقت على نفس المجلد. عشان كده الأرقام الكبيرة مش دليل على ٣٥٤ عطل حقيقي.

## اللي محتاج شغل باقي

١. `facebook-pages.spec.js`: أعرف من الكود إزاي `FbPostCard` بياخد التعليقات النهارده، وأصلح
   الاختبار (أو الواجهة لو التعليقات فعلًا اختفت من التغذية).
٢. `icon-buttons-named.spec.js`: عدّاد «+٩٩».
٣. بعد كده أعيد التشغيل الكامل بـ`--workers=2` (زي runner صغير) وأشوف الأرقام الحقيقية.

## Full-suite run, measured (final)

`npx playwright test --workers=2` against a fresh `npm run build` + `npm run preview`:
**448 passed, 3 failed, 23 skipped in 10.3m** (474 collected). Earlier numbers of 97/354
were worker and `test-results` contention, not broken pages; two workers and no other
Playwright process alive is the only configuration that gives a trustworthy result.

The three failures, each diagnosed and handled:

1. `cashier-smoke.spec.js` — FIXED, and the earlier diagnosis here was wrong. The file was not
   stuck on `useShifts` / `useShiftSales`: the screen renders its table happily with an empty
   array. The real cause, measured: every cashier page is `lazy()`, and `CashierLayout` draws
   `PageSkeleton` (sr-only «جارٍ التحميل…») as the Suspense fallback. `.cashier-root` is visible
   while that fallback is still on screen, so the assertion that read `main.innerText()` right
   after it captured the skeleton: `main content too short: "جارٍ التحميل…"`, 13 chars. It
   surfaced on `/cashier/pos` in the measured runs (the earlier full run blamed
   `/cashier/sales`), i.e. it moves with chunk-load timing, which is why it looked like a mock
   problem. The spec now waits for `cashier-page-loading` to be gone before reading the text.
   Measured: without the wait the test failed 3/3 runs; with it, 4/4 passed in each of 3
   consecutive runs.
2. `inbox-instagram-attachments.spec.js` — FIXED. The test looked for a button titled
   "Attach media" / «إرفاق ملف أو صورة», but Messenger draws its own composer whose paperclip
   is «إرفاق ملف» / "Attach a file". Now scoped to `messenger-composer`. 7/7 in the file.
3. `instagram-pages.spec.js` — FIXED. The channel strip now lands on the channel's own inbox,
   so the URL is `/inbox?channel=whatsapp`, not the bare `/inbox`; the assertion was stale.
