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

ملاحظة: القيمتان للواتساب embedded signup هما اختياريتان وغير مطلوبتين لزر الربط الحالي.

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

WhatsApp Embedded Signup (FB.login with config_id and the WHATSAPP_EMBEDDED_SIGNUP window events) is a documented follow-up; the current connect flow covers Messenger and Instagram only.
