# دليل إعداد قنوات ميتا — ماسنجر وإنستجرام

هذا الدليل يشرح الإعداد المطلوب في Meta Developer Console عشان زر الربط في صفحة القنوات يشتغل من أول مرة. الزر يفتح شاشة تسجيل الدخول الخاصة بفيسبوك نفسها، والمستخدم يوافق على الصلاحيات بحسابه على ميتا، ولا يُلصق أي App ID أو توكن يدويًا.

## أولًا: إعداد التطبيق في ميتا

1. افتح الموقع المطوّرين وأنشئ تطبيقًا جديدًا.

```text
https://developers.facebook.com/apps
```

2. من قائمة المنتجات أضف المنتج المسمى Facebook Login.
3. من صفحة الإعدادات الأساسية خذ القيمتين App ID وApp Secret وضعهما في متغيرات البيئة كما بالأسفل.

## ثانيًا: روابط العودة المسموحة

سجّل رابط العودة التالي حرفيًا في صفحة Facebook Login ثم Settings في خانة Valid OAuth Redirect URIs. الخادم يبني الرابط من متغيرات البيئة بالأولويات التالية: قيمة META_OAUTH_REDIRECT_URI إن وُجدت، وإلا مشتق من API_PUBLIC_BASE_URL.

```text
https://<api-host>/api/v1/integrations/meta/oauth/callback
```

استبدل ما بين علامتي أصغر وأكبر بعنوان الـAPI العام الفعلي. أي اختلاف ولو حرفًا واحدًا بين المسجل والمُرسل يجعل فيسبوك يرفض العملية، وسيعود المتصفح بشرح الخطأ إلى صفحة القنوات.

## ثالثًا: الـWebhooks

سجّل نفس الرابط التالي في منتج Webhooks على كائن Page، وحدد الحقول المطلوبة: messages وmessaging_postbacks وmessaging_referrals وmessage_deliveries. وقيمة Verify Token تطابق MESSENGER_VERIFY_TOKEN أو INSTAGRAM_VERIFY_TOKEN حسب القناة.

```text
https://<api-host>/api/v1/webhooks/messenger
https://<api-host>/api/v1/webhooks/instagram
```

الخادم يشترك في حقول الصفحة تلقائيًا بعد نجاح الربط، لكن اشتراك التطبيق نفسه في منتج Webhooks مع رابط الاستقبال يبقى مسؤولية الإعداد.

## رابعًا: وضع التطوير وحساب المجرّب

ما دام التطبيق في وضع التطوير فلن يُقبل أي حساب إلا إذا كان له دور عليه: Admin أو Developer أو Tester. أضف حساب المشغّل من صفحة Roles ثم Testers واطلب منه قبول الدعوة قبل الضغط على زر الربط، وإلا فسيرجع الخطأ access_denied إلى صفحة القنوات. للإنتاج العام يحتاج التطبيق موافقة App Review على الصلاحيات pages_messaging وinstagram_manage_messages وpages_manage_metadata.

## خامسًا: متغيرات البيئة

```text
META_APP_ID             معرف التطبيق من صفحة الإعدادات الأساسية
META_APP_SECRET         سر التطبيق — لا يغادر الخادم أبدًا
META_OAUTH_REDIRECT_URI رابط العودة المسجل حرفيًا في ميتا، ويُشتق تلقائيًا من المتغير التالي إن تُرك فارغًا
API_PUBLIC_BASE_URL     العنوان العام للـAPI ويُشتق منه رابط العودة والـWebhooks
META_OAUTH_CONFIG_ID    اختياري لتطبيقات نوع Business فقط — معرف إعداد Facebook Login for Business
MESSENGER_APP_SECRET    للتحقق من توقيع Webhooks ماسنجر
MESSENGER_VERIFY_TOKEN  توكن التحقق عند تسجيل رابط الاستقبال
INSTAGRAM_APP_SECRET    للتحقق من توقيع Webhooks إنستجرام
INSTAGRAM_VERIFY_TOKEN  توكن التحقق لإنستجرام
FRONTEND_PUBLIC_URL     عنوان لوحة التحكم، وعليه يهبط المتصفح بعد الربط
```

## سادسًا: واتساب — زر الربط بنقرة واحدة (Embedded Signup)

زر واتساب في صفحة القنوات يفتح **نافذة ميتا نفسها** (Popup وليس تحويلًا): صاحب المتجر يسجّل بحسابه، ينشئ أو يختار حساب WhatsApp Business والرقم، وميتا ترجّع للخادم `code` + `messaging_account_ids` + `phone_number_id` في Embedded Signup v5. الخادم يبادل الكود برمز أعمال، **يشترك في حساب المراسلة** (بدونها لا تصل أي رسالة واردة)، يتحقق من الرقم، ثم يحفظ القناة.

### الإعداد في Meta Developer Console
1. من قائمة المنتجات أضف **Facebook Login for Business**.
2. من **Configurations** أنشئ إعداد **Facebook Login for Business** جديدًا، واختر **Embedded Signup** ثم منتج **Cloud API**. لا تستخدم إعداد Embedded Signup v2/v3 القديم؛ دعم الإصدارين انتهى في 15 أكتوبر 2026. الإعداد الجديد يستخدم تجربة v4 أو أحدث، ويختار التطبيق v5 عبر قيمة `extras.version`.
3. انسخ **Configuration ID** الناتج → هذا هو `META_WHATSAPP_CONFIG_ID` (وهو **مختلف** عن إعداد ماسنجر).
4. من **Settings** أضف نطاق لوحة التحكم إلى **Allowed Domains for the JavaScript SDK**
   (بدونها يرفض المتصفح فتح النافذة).

### المتغير المطلوب إضافته
```text
META_WHATSAPP_CONFIG_ID   معرف إعداد WhatsApp Embedded Signup (من الخطوة 3)
```

عند اختيار **System User Access Token** بصلاحية 60 يوم في إعداد Business Login، يجدد الخادم
التوكن تلقائيًا قبل انتهائه بسبعة أيام عبر مهمة مجدولة كل 6 ساعات. احرص على تشغيل عامل
`scheduler` في بيئة الإنتاج؛ بدون العامل لن تعمل عملية التجديد. الاتصالات القديمة بواتساب
تحاول تسجيل نفسها للتجديد في أول دورة مجدولة، أما اتصالات Facebook/Instagram/Messenger القديمة
التي لا تحتوي على التوكن الأساسي فتحتاج إعادة ربط واحدة لحفظ بيانات التجديد.

### الصلاحيات المطلوبة
`whatsapp_business_management` و`whatsapp_business_messaging` — ووضع التطوير يكفي للاختبار بحساب له دور عليه.

### تسجيل الرقم (ضروري ليستقبل الرقم رسائل)
نافذة ميتا تضيف الرقم وتتحقق منه بكود OTP، لكن الرقم لا يرسل ولا يستقبل إلا بعد **تسجيله** بنداء API (لا يمكن من WhatsApp Manager ولا من لوحة التطبيق). الخادم يفعل ذلك تلقائيًا بعد الاشتراك في الـWABA: يقرأ حالة الرقم، فإن كانت `CONNECTED` تركه كما هو، وإلا سجّله برقم سري من 6 أرقام يولّده بنفسه ويحفظه **مشفّرًا** (للتحقق الثنائي، ويلزم لتغيير الرقم السري أو حذف الرقم لاحقًا). ميتا تسمح بـ10 محاولات تسجيل كل 72 ساعة ثم تقفل الرقم (الخطأ `133016`)، لذلك لا يعيد الخادم المحاولة.

### ما يحدث تقنيًا (للمرجع)
- الواجهة تحمّل Facebook JS SDK قبل النقرة، ثم `FB.login` بـ `config_id` و`response_type: "code"` و`override_default_response_type: true` و`extras: { version: "v5" }`. يُعطّل مسار ترحيل أرقام تطبيق WhatsApp Business في الإعداد الحالي لأن المنتج يدعم Cloud API.
- ميتا ترسل حدث `WA_EMBEDDED_SIGNUP` بنوع `FINISH` إلى نافذة الصفحة، ويحتوي `data` على `messaging_account_ids` و`phone_number_id` و`business_id`. يمرر التطبيق أول Messaging Account إلى الخادم على أنه `waba_id` للتوافق مع واجهاته الحالية.
- الخادم: `GET /oauth/access_token` (بدون redirect_uri) → `POST /{waba_id}/subscribed_apps` → `GET /{phone_number_id}` → تحقق ثم حفظ.

ملاحظة: القيمتان `META_APP_ID` و`META_APP_SECRET` مشتركتان بين كل قنوات ميتا.

## سابعًا: ظهرت عبارة «App not active» في نافذة فيسبوك

هذه الرسالة تأتي من ميتا نفسها، قبل أي رمز تفويض، وتعني أن **التطبيق** (App ID) غير مفعّل. لا علاقة لها بالكود ولا بحساب صاحب المتجر، فلن تُحل بإعادة المحاولة ولا بتغيير الإعدادات في لوحتنا. الصفحة تعرض بعدها «لم يُرجع فيسبوك رمز التفويض» لأن النافذة أُغلقت بلا رمز.

الأسباب المعتادة، وكلها تُفحص في لوحة مطوّري ميتا للتطبيق نفسه:

1. التطبيق في وضع **Development** وصاحب الحساب ليس عليه دور (Admin/Developer/Tester). أضف الحساب من App roles.
2. التطبيق **معطّل أو مقيّد** من ميتا (تنبيه في أعلى لوحة التطبيق، أو رسالة في Alerts / App Review). أكمل ما تطلبه ثم أعد التفعيل.
3. نقص في **التحقق من النشاط التجاري** أو الاستخدام المسموح (Data Use Checkup) أو سياسة الخصوصية. ميتا توقف التطبيق حتى تُستكمل.
4. التطبيق **محذوف أو يخص حسابًا آخر** وأن `META_APP_ID` على الخادم يشير إلى تطبيق غير هذا. قارن القيمة بما في صفحة Settings > Basic.

تأكد أخيرًا أن `META_APP_ID` على الخادم هو نفسه تطبيق الـ Live الذي تعمل عليه.

---

# Meta channels setup guide — Messenger and Instagram

This guide covers the Meta Developer Console setup required by the connect button on the channels page. The button opens Meta's own login dialog; the operator consents with their Meta account and no app id or token is pasted anywhere.

## 1. App basics

1. Create an app at `https://developers.facebook.com/apps`.
2. Add the `Facebook Login` product.
3. Copy `App ID` and `App Secret` from Settings → Basic into the env vars below.

## 2. Valid OAuth Redirect URIs

Register the callback URL verbatim under Facebook Login → Settings. The server builds it from `META_OAUTH_REDIRECT_URI` when set, otherwise it derives it from `API_PUBLIC_BASE_URL`:

```text
https://<api-host>/api/v1/integrations/meta/oauth/callback
```

Any mismatch between the registered URL and the one sent makes Meta refuse the flow; the browser returns to the channels page with the reason.

## 3. Webhooks

In the `Webhooks` product, subscribe to the `Page` object with the fields `messages`, `messaging_postbacks`, `messaging_referrals`, `message_deliveries`, and the callback URLs:

```text
https://<api-host>/api/v1/webhooks/messenger
https://<api-host>/api/v1/webhooks/instagram
```

The verify token must match `MESSENGER_VERIFY_TOKEN` or `INSTAGRAM_VERIFY_TOKEN`. The server subscribes the page itself after a successful connect; the app-level webhook subscription above is still operator setup.

## 4. Development mode and testers

While the app is in development mode only its Admins, Developers, and Testers can complete the dialog. Add the operator account under Roles → Testers and have it accept the invite before connecting, otherwise the callback reports `access_denied`. Going public requires App Review with Advanced Access for `pages_messaging`, `instagram_manage_messages`, and `pages_manage_metadata`.

## 5. Environment variables

```text
META_APP_ID             App ID from Settings → Basic
META_APP_SECRET         App secret — server-side only, never sent to the browser
META_OAUTH_REDIRECT_URI exact callback URL registered in Meta; derived from API_PUBLIC_BASE_URL when empty
API_PUBLIC_BASE_URL     canonical public API origin; also drives the webhook URLs
META_OAUTH_CONFIG_ID    optional — Business-type apps only: Facebook Login for Business configuration id
MESSENGER_APP_SECRET    verifies Messenger webhook signatures
MESSENGER_VERIFY_TOKEN  verify token for the Messenger webhook registration
INSTAGRAM_APP_SECRET    verifies Instagram webhook signatures
INSTAGRAM_VERIFY_TOKEN  verify token for the Instagram webhook registration
FRONTEND_PUBLIC_URL     dashboard origin the callback redirects back to
```

## 6. WhatsApp — one-click connect (Embedded Signup)

The WhatsApp button on the channels page opens **Meta's own popup** (not a redirect): the store owner signs in, creates or selects the WhatsApp Business account and number, and Embedded Signup v5 returns `code` + `messaging_account_ids` + `phone_number_id`. The server exchanges the code for a business token, **subscribes the app to the messaging account** (without it no inbound message ever arrives), verifies the number, and stores the channel.

### Console setup
1. Add the **Facebook Login for Business** product.
2. Create a new **Facebook Login for Business** configuration, choose **Embedded Signup**, and select **Cloud API**. Do not use the old Embedded Signup v2/v3 configuration; Meta deprecated those versions on October 15, 2026. The new configuration uses the v4-or-later flow, while the app selects v5 through `extras.version`.
3. Copy the generated **Configuration ID** → `META_WHATSAPP_CONFIG_ID` (it is NOT the same as the Messenger configuration).
4. Under **Settings**, add the dashboard domain to **Allowed Domains for the JavaScript SDK**.

### Permissions
`whatsapp_business_management` and `whatsapp_business_messaging`; development mode is enough to test with an account that holds a role on the app.

For **System User Access Token** with a 60-day expiry, the scheduler renews the token seven days
before expiry via Meta's refresh endpoint every six hours. Keep the production `scheduler` worker
running. Existing WhatsApp connections are enrolled on the next sweep; older Facebook, Instagram,
and Messenger connections need one reconnect because their original user/system token was not
stored.

### Technical reference
- The page preloads the Facebook JS SDK, then calls `FB.login` with `config_id`, `response_type: "code"`, `override_default_response_type: true`, and `extras: { version: "v5" }`. WhatsApp Business app onboarding is explicitly disabled because the product currently connects Cloud API numbers.
- Meta posts `WA_EMBEDDED_SIGNUP` / `FINISH` to the page window with `data = { messaging_account_ids, phone_number_id, business_id }`. The first messaging account ID is passed to the existing backend `waba_id` field.
- Server: `GET /oauth/access_token` (no redirect_uri) → `POST /{messaging_account_id}/subscribed_apps` → verify phone number → store.

`META_APP_ID` and `META_APP_SECRET` are shared across all Meta channels.

### Registering the number (required before it can receive)
Meta's window adds and verifies the number with an OTP, but a number only sends and receives once it is **registered**, and that is an API call (not possible from WhatsApp Manager or the App Dashboard). After subscribing to the WABA the server does it automatically: it reads the number's status, leaves a `CONNECTED` number alone, and otherwise registers it with a 6-digit two-step PIN it generates and keeps **encrypted** (needed later to change the PIN or delete the number). Meta allows 10 registration attempts per 72 hours and then locks the number (error `133016`), so the server never retries.

## 7. "App not active" appears in the Facebook window

This message comes from Meta itself, before any authorization code, and means the **app** (App ID) is switched off. It is not a code bug and not the store owner's account, so retrying will not help and nothing in our settings page can fix it. The page then shows "Facebook returned no authorization code" because the window closed without a code.

Common causes, all checked in the Meta developer console for that app:

1. The app is in **Development** mode and the account has no role on it (Admin/Developer/Tester). Add it under App roles.
2. Meta **disabled or restricted** the app (a banner on the app dashboard, or in Alerts / App Review). Complete what it asks, then reactivate.
3. A missing **business verification**, Data Use Checkup or privacy policy. Meta pauses the app until they are done.
4. The app is **deleted or belongs to another account**, or `META_APP_ID` on the server points at a different app. Compare it with Settings > Basic.

Finally, make sure `META_APP_ID` on the server is the same live app you are working in.
