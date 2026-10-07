# خطوات يدوية مطلوبة على المنصات — Manual Platform Steps

‏‫دي الخطوات اللي الـManagement API بتاعتها ما سمحتش بيها أو بتحتاج قرار تكلفة، ‏مرتبة بالأولوية. ‏تاريخ المراجعة: 2026-10-07.

## 1. Supabase — النسخ الاحتياطي وPITR ‏(حرج، قرار تكلفة)

‏‫المراجعة لاقت قايمة الbackups فاضية تمامًا. ‏من الDashboard:

- ‏‏افتح المشروع sales (‏ref ‏`iixxqitfopsgvaheedlg`) → ‏Database → ‏Backups.
- ‏‏فعّل الخطة اللي بتوفر ‏daily backups ‏+ ‏Point-in-Time Recovery، ‏وضيف retention 7 أيام على الأقل (‏30 أفضل لبيانات مبيعات).
- ‏‏بعد التفعيل: نفّذ استرجاع تجريبي على فرع مشروع (‏branch) أو مشروع مؤقت للتأكد إن النسخ فعلًا بتترجع — ‏backup من غير استرجاع مجرب مش backup.

## 2. Supabase — ‏site_url ‏‏(حرج، مجاني، دقيقتين)

‏‫الـAPI بيرفض تغييره (‏بتجربتين بصيغ مختلفة، ‏الباتش بيرجع 200 بس القيمة بتفضل localhost) — ‏يتعمل من الداشبورد:

- ‏‏Authentication → ‏URL Configuration → ‏Site URL ‏= ‏`https://fihrist.world`
- ‏‏في ‏Redirect URLs ‏ضيف: ‏`https://fihrist.world` ‏و‏`https://www.fihrist.world`
- ‏‏ده اللي هيخلي روابط تأكيد الإيميل واستعادة الحساب تشاور على الدومين الصحيح بدل localhost.

## 3. Vercel — مشروع fihrist-owner-console ‏(تحذير، اختصاصك أنت)

‏‫ممتلكاتك الشخصية للوحة المالك فمُنيعت عنها. ‏المراجعة لاقت عليها: ‏SUPABASE_ACCESS_TOKEN ‏(‏sensitive‏) + ‏ADMIN_AUTH_DISABLED + ‏ADMIN_PASSWORD_HASH + ‏SUPABASE_PROJECT_REF. ‏المطلوب منك:

- ‏‏تتأكد إن ‏ADMIN_AUTH_DISABLED ‏مش قيمته true ‏في production ‏(‏لو true ‏فاللوحة مفتوحة بدون كلمة مرور).
- ‏‏متغير السوبرابيز access token ‏على مشروع فرونت معناه إنه ممكن يظهر في الbundle — ‏لو اللوحة بتبنيه في الكود، ‏انقله لسيرفر/إعدادات API ‏مش VITE_ env.
- ‏‏لو متأكد إن المتغيرات دي مكتبة قديمة غير مستخدمة، ‏امسحها من الdashboard.

## 4. GitHub — branch protection ‏(مؤجل بوعي لحد ما الCI يخضر)

‏‫مستنيين السويت الكامل يبقى أخضر من أول مرة، ‏وساعتها:

- ‏‏Settings → ‏Branches → ‏Add rule ‏على ‏main: ‏Require status checks (‏حط شيكات مسارات الـCI الحالية)، ‏Require a pull request قبل الدمج.
- ‏‏فعّل ‏secret scanning ‏وDependabot ‏من ‏Settings → ‏Code security (‏الـAPI رفض التحقق منها برمجيًا).

## 5. Railway — قرارات تشغيل ‏(متوسط)

- ‏‏Redis من غير volume: ‏يا إما تربط volume وتفعّل appendonly، ‏يا إما نتوثق صراحة إنه cache ‏قابل للفقد — ‏فيه فارق تشغيلي في الـSSE resume والrate limits بعد إعادة نشر.
- ‏‏ضيف healthcheck ‏لمخدمات الworkers، ‏والمثالي تعليق النسخ لـ2 بعد أول إسبوع إنتاج مستقر.
- ‏‏تأكد إن ‏DEBUG=false ‏وCORS_ORIGINS ‏مضبوطين على دومين الإنتاج فقط.
