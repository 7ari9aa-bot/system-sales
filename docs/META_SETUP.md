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

زر واتساب في صفحة القنوات يفتح **نافذة ميتا نفسها** (Popup وليس تحويلًا): صاحب المتجر يسجّل بحسابه، ينشئ أو يختار حساب WhatsApp Business والرقم، وميتا ترجّع للخادم `code` + `waba_id` + `phone_number_id`. الخادم يبادل الكود برمز أعمال، **يشترك في الـWABA** (بدونها لا تصل أي رسالة واردة)، يتحقق من الرقم، ثم يحفظ القناة.

### الإعداد في Meta Developer Console
1. من قائمة المنتجات أضف **Facebook Login for Business**.
2. من **Configurations** اضغط **Create from template** واختر قالب
   **WhatsApp Embedded Signup Configuration** (المزوّدون يسمونه أحيانًا "With 60 Expiration Token").
3. انسخ **Configuration ID** الناتج → هذا هو `META_WHATSAPP_CONFIG_ID` (وهو **مختلف** عن إعداد ماسنجر).
4. من **Settings** أضف نطاق لوحة التحكم إلى **Allowed Domains for the JavaScript SDK**
   (بدونها يرفض المتصفح فتح النافذة).

### المتغير المطلوب إضافته
```text
META_WHATSAPP_CONFIG_ID   معرف إعداد WhatsApp Embedded Signup (من الخطوة 3)
```

### الصلاحيات المطلوبة
`whatsapp_business_management` و`whatsapp_business_messaging` — ووضع التطوير يكفي للاختبار بحساب له دور عليه.

### ما يحدث تقنيًا (للمرجع)
- الواجهة تحمّل Facebook JS SDK ثم `FB.login` بـ `config_id` و`response_type: "code"` و`override_default_response_type: true` و`extras: { featureType: "", sessionInfoVersion: "3" }`.
- ميتا ترسل حدث `WA_EMBEDDED_SIGNUP` بنوع `FINISH` إلى نافذة الصفحة، ويحتوي `data` على `waba_id` و`phone_number_id` و`business_id`.
- الخادم: `GET /oauth/access_token` (بدون redirect_uri) → `POST /{waba_id}/subscribed_apps` → `GET /{phone_number_id}` → تحقق ثم حفظ.

ملاحظة: القيمتان `META_APP_ID` و`META_APP_SECRET` مشتركتان بين كل قنوات ميتا.

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

The WhatsApp button on the channels page opens **Meta's own popup** (not a redirect): the store owner signs in, creates or selects the WhatsApp Business account and number, and Meta returns `code` + `waba_id` + `phone_number_id`. The server exchanges the code for a business token, **subscribes the app to the WABA** (without it no inbound message ever arrives), verifies the number, and stores the channel.

### Console setup
1. Add the **Facebook Login for Business** product.
2. **Configurations → Create from template → "WhatsApp Embedded Signup Configuration"**.
3. Copy the generated **Configuration ID** → `META_WHATSAPP_CONFIG_ID` (it is NOT the same as the Messenger configuration).
4. Under **Settings**, add the dashboard domain to **Allowed Domains for the JavaScript SDK**.

### Permissions
`whatsapp_business_management` and `whatsapp_business_messaging`; development mode is enough to test with an account that holds a role on the app.

### Technical reference
- The page loads the Facebook JS SDK, then `FB.login` with `config_id`, `response_type: "code"`, `override_default_response_type: true`, `extras: { featureType: "", sessionInfoVersion: "3" }`.
- Meta posts `WA_EMBEDDED_SIGNUP` / `FINISH` to the page window with `data = { waba_id, phone_number_id, business_id }`.
- Server: `GET /oauth/access_token` (no redirect_uri) → `POST /{waba_id}/subscribed_apps` → `GET /{phone_number_id}` → verify → store.

`META_APP_ID` and `META_APP_SECRET` are shared across all Meta channels.
