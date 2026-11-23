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

1. `cashier-smoke.spec.js` — STILL FAILING, and outside the channels layer. `/cashier/sales`
   renders «جارٍ التحميل…» under the spec's mock, which answers every endpoint it does not
   know with `[]`; that screen reads its data through `useShifts` / `useShiftSales` and never
   leaves the loading state with an empty array. The fix belongs in the spec's mock (answer
   the shift endpoints with the shape those hooks read), not in the screen.
2. `inbox-instagram-attachments.spec.js` — FIXED. The test looked for a button titled
   "Attach media" / «إرفاق ملف أو صورة», but Messenger draws its own composer whose paperclip
   is «إرفاق ملف» / "Attach a file". Now scoped to `messenger-composer`. 7/7 in the file.
3. `instagram-pages.spec.js` — FIXED. The channel strip now lands on the channel's own inbox,
   so the URL is `/inbox?channel=whatsapp`, not the bare `/inbox`; the assertion was stale.
