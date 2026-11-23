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

## ثالثًا: الـWebhooks — ثلاثة إعدادات مستقلة

ميتا تعطي **رابط استقبال واحدًا لكل نوع كائن** داخل التطبيق، وليس لكل قناة. لذلك الإعداد ثلاثة أجزاء منفصلة، كل جزء له كائنه ورابطه وحقوله وتوكنه:

| الكائن في ميتا | القنوات | رابط الاستقبال |
|---|---|---|
| `Page` | ماسنجر + فيسبوك | `https://<api-host>/api/v1/webhooks/meta/page` |
| `Instagram` | إنستجرام | `https://<api-host>/api/v1/webhooks/instagram` |
| `WhatsApp Business Account` | واتساب | `https://<api-host>/api/v1/webhooks/whatsapp` |

**الاشتراك في الحقل يجب أن يحصل في مكانين معًا**، وإلا لن يصل الحدث ولو نجح الربط في صفحة القنوات:

1. **على مستوى التطبيق** (لوحة المطورين ثم Webhooks): الكائن والرابط وتوكن التحقق والحقول. هذه خطوة يدوية للمشغّل، ولا يمكن للخادم قراءتها أو ضبطها.
2. **على مستوى الأصل** (الصفحة أو حساب واتساب للأعمال): يفعله الخادم تلقائيًا عند الربط، ويزيله عند الفصل.

### ١) كائن Page (ماسنجر وفيسبوك)

الرابط: `https://<api-host>/api/v1/webhooks/meta/page`

الحقول: `messages` و`messaging_postbacks` و`messaging_referrals` و`message_deliveries` و`message_reads` و`message_reactions` و`message_echoes` و`messaging_handovers` و`feed` و`mention`.

الخادم يقسّم كل رسالة واردة بنفسه: ما كان تحت `messaging` (محادثات خاصة) يذهب إلى ماسنجر، وما كان تحت `changes` (منشورات وتعليقات وإشارات) يذهب إلى فيسبوك. فلا يهم أي القناتين مربوطة؛ يكفي رابط واحد، ولا يُسجَّل رابط ثانٍ على الكائن نفسه.

التوقيع: `MESSENGER_APP_SECRET` (أو `META_APP_SECRET` إن تُرك فارغًا). التحقق: `MESSENGER_VERIFY_TOKEN`. توكن واتساب لا يُقبل هنا أبدًا.

الروابط القديمة `/api/v1/webhooks/messenger` و`/api/v1/webhooks/facebook` ما زالت تعمل لمن سجّلها سابقًا، لكنها **لا تُسجَّل معًا** على الكائن نفسه: سجّل رابط `meta/page` فقط.

### ٢) كائن Instagram

الرابط: `https://<api-host>/api/v1/webhooks/instagram`

الحقول: `messages` و`messaging_postbacks` و`message_reactions` و`messaging_seen` و`comments` و`mentions` و`live_comments`.

مهم: اشتراك الصفحة المرتبطة (`/{page-id}/subscribed_apps`) **لا يضبط** Webhooks إنستجرام ولا يقبل حقولها. حقول إنستجرام تُختار من لوحة التطبيق على كائن Instagram نفسه، والخادم يشترك فقط في اشتراك الصفحة المرتبطة بالحساب.

متطلبات الإنتاج: `instagram_manage_messages` و`instagram_manage_comments` يحتاجان Advanced Access وموافقة App Review، والحساب يجب أن يكون احترافيًا (Business أو Creator) ومرتبطًا بصفحة فيسبوك. بدون ذلك قد لا تصل الإشعارات رغم نجاح الربط.

التوقيع: `INSTAGRAM_APP_SECRET`. التحقق: `INSTAGRAM_VERIFY_TOKEN`.

### ٣) كائن WhatsApp Business Account

الرابط: `https://<api-host>/api/v1/webhooks/whatsapp`

الحقل: `messages` (ويشمل حالات التسليم والفشل)، ويُستحسن إضافة حقول حالة الحساب والرقم والقوالب.

يُضبط من لوحة التطبيق: WhatsApp ثم Configuration، مرة واحدة للتطبيق كله. اشتراك التطبيق في حساب واتساب للأعمال (`/{waba-id}/subscribed_apps`) يفعله الخادم عند الربط ويزيله عند الفصل، لكنه **لا يغني** عن ضبط الرابط في اللوحة.

التوقيع: `WHATSAPP_APP_SECRET`. التحقق: `WHATSAPP_VERIFY_TOKEN`.

### التأكد من أن كل شيء يعمل

من صفحة القنوات اضغط «تشخيص القناة»: تظهر حالة الاتصال والصلاحيات واشتراك الصفحة (يسأل ميتا مباشرة) وإعداد الخادم وآخر Webhook وصل وآخر خطأ. لو لم يصل أي حدث بعد، فالأرجح أن رابط التطبيق في اللوحة غير مضبوط (لا يمكن فحصه من الخادم). التطبيق يجب أن يكون في وضع **Live** كي تصل أحداث المستخدمين الحقيقيين.

عند فصل قناة يزيل الخادم اشتراكها من ميتا. إن كانت الصفحة مشتركة معها قناة أخرى متصلة (مثل ماسنجر مع فيسبوك) يُبقي الاشتراك ويقتصر على حقول القناة الباقية. وإن تعذّر الوصول إلى ميتا يبقى الفصل محليًا ناجحًا وتُعلَّم الإزالة «معلّقة» لتُعاد من زر إعادة المحاولة.

### صلاحيات كل قناة

كل قناة تطلب ما تحتاجه فقط، ولا تحمل صلاحيات قناة أخرى:

| القناة | الصلاحيات | الصفحات التي تظهر عند الربط |
|---|---|---|
| ماسنجر | `pages_show_list`، `pages_read_engagement`، `pages_manage_metadata`، `pages_messaging` | صفحات لها مهمة `MESSAGING` أو `MANAGE` |
| فيسبوك | `pages_show_list`، `pages_read_engagement`، `pages_manage_metadata`، `pages_manage_posts`، `pages_manage_engagement`، `pages_read_user_content`، `read_insights` | أي صفحة لها مهمة إدارة (`MANAGE` أو `CREATE_CONTENT` أو `MODERATE` أو `ANALYZE` أو `ADVERTISE` أو `MESSAGING`) |
| إنستجرام | صلاحيات الرسائل والتعليقات والنشر الخاصة بإنستجرام مع `pages_messaging` | صفحات لها مهمة `MESSAGING` أو `MANAGE` |

قناة فيسبوك لا تطلب `pages_messaging`: محادثات العملاء من شأن ماسنجر، ومن يربط صفحته للمنشورات والتعليقات والإحصاءات فقط لا يُطلب منه الوصول إلى رسائلها الخاصة. اربط ماسنجر أيضًا إن أردت الرسائل.

## رابعًا: وضع التطوير وحساب المجرّب

ما دام التطبيق في وضع التطوير فلن يُقبل أي حساب إلا إذا كان له دور عليه: Admin أو Developer أو Tester. أضف حساب المشغّل من صفحة Roles ثم Testers واطلب منه قبول الدعوة قبل الضغط على زر الربط، وإلا فسيرجع الخطأ access_denied إلى صفحة القنوات. للإنتاج العام يحتاج التطبيق موافقة App Review على الصلاحيات pages_messaging وinstagram_manage_messages وpages_manage_metadata.

## خامسًا: متغيرات البيئة

```text
META_APP_ID             معرف التطبيق من صفحة الإعدادات الأساسية
META_APP_SECRET         سر التطبيق — لا يغادر الخادم أبدًا
META_OAUTH_REDIRECT_URI رابط العودة المسجل حرفيًا في ميتا، ويُشتق تلقائيًا من المتغير التالي إن تُرك فارغًا
API_PUBLIC_BASE_URL     العنوان العام للـAPI ويُشتق منه رابط العودة والـWebhooks
META_INSTAGRAM_CONFIG_ID    اختياري — معرف إعداد Facebook Login for Business الخاص بإنستجرام فقط (فيسبوك وMessenger لا يستخدمانه)
MESSENGER_APP_SECRET    للتحقق من توقيع Webhooks ماسنجر وفيسبوك (يُستخدم META_APP_SECRET إن تُرك فارغًا)
MESSENGER_VERIFY_TOKEN  توكن التحقق عند تسجيل رابط الاستقبال لماسنجر وفيسبوك
WHATSAPP_APP_SECRET     للتحقق من توقيع Webhooks واتساب (سر التطبيق نفسه من الإعدادات الأساسية)
WHATSAPP_VERIFY_TOKEN   توكن التحقق لواتساب فقط — نص عشوائي تضعه هنا وفي WhatsApp ثم Configuration
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

## ثامنًا: ظهرت عبارة «ليس بإمكان <اسم التطبيق> تأهيل العملاء الآن»

الإنجليزية: "<App name> can't onboard customers right now". تظهر بعد تسجيل الدخول في نافذة فيسبوك، ويظل الزر يدور بلا نهاية، ولا يصل أي رمز تفويض للصفحة. مصدرها ميتا، وليست خطأ في الكود ولا في إعدادات المتجر، فإعادة المحاولة لن تفيد.

معناها أن التطبيق **غير مسجّل Tech Provider بالكامل** في ميتا، فلا يحق له تأهيل عملاء آخرين عبر Embedded Signup. الشروط كلها تُستكمل في لوحة ميتا للتطبيق ولحافظة الأعمال (Business Portfolio) المالكة له، بهذا الترتيب:

1. **Business Verification** للحافظة المالكة للتطبيق (Business settings > Security center).
2. **Access Verification** والتسجيل كـ **Tech Provider** (App Dashboard > WhatsApp > تأهيل مزوّد التقنية).
3. **App Review** وحصول التطبيق على **Advanced Access** للصلاحيتين `whatsapp_business_management` و`whatsapp_business_messaging`.
4. التطبيق في وضع **Live** (وليس Development).
5. `META_APP_ID` و`META_WHATSAPP_CONFIG_ID` على الخادم يخصان هذا التطبيق نفسه (الـ config من Facebook Login for Business > Configurations).

ملاحظات مهمة:

- حساب له دور **Admin أو Developer أو Tester** على التطبيق يُسمح له بتجربة الربط لحسابه هو قبل اكتمال الخطوات أعلاه، فلا تختبر بحساب بلا دور.
- بعض الفرق تُكمل كل الخطوات وتظل الرسالة تظهر أيامًا حتى تُحدَّث حالة التطبيق عند ميتا. إن اكتملت الأربع ولم تزل، افتح تذكرة من Meta Support مع **Session ID** الظاهر أسفل النافذة (مثل `01a1fc32-...`) فهو ما يطلبه الدعم.
- ربط **فيسبوك وماسنجر** لا يتأثر بهذه الرسالة، وهو يعمل بصلاحيات صفحات عادية.

## تاسعًا: استيراد محادثات ماسنجر القديمة

عند ربط ماسنجر لأول مرة يُقرأ تاريخ الصفحة من ميتا تلقائيًا مرة واحدة (آخر ٩٠ يومًا)، ويمكن للمالك تشغيله يدويًا لتعويض فترة انقطع فيها الـwebhook: `POST /api/v1/integrations/messenger/backfill` بالجسم `{"days": 14}` أو `{"since": "2026-11-20T00:00:00Z"}` (يحتاج صلاحية `settings:write`)، والحالة من `GET` على نفس المسار.

- ميتا تُعيد تفاصيل **آخر ٢٠ رسالة فقط** في كل محادثة، والأقدم تُتخطّى وتُحصى؛ فهذه أداة تعويض وليست نسخة كاملة.
- لا يبدأ عدّاد أول رد ولا يُشغَّل الذكاء الاصطناعي ولا تُرسل إشعارات لهذه الرسائل القديمة، ولا يزيد عدّاد غير المقروء.
- التكرار آمن: الرسالة تُعرَّف بمعرّف ميتا، فلا تُكتب مرتين ولو تداخلت الفترات أو سبقها الـwebhook.
- يتوقف التشغيل ويُستأنف لاحقًا إذا طلبت ميتا التمهل، وإذا انفتح قاطع الدائرة `provider.messenger` (نفس قاطع الإرسال، فيتوقف الإرسال نحو ٣٠ ثانية على الأكثر).
- لماسنجر فقط: يحتاج الإذن `pages_messaging`، وهو غير مطلوب في ربط فيسبوك وحده.

---

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

## 3. Webhooks: three independent setups

Meta gives an app **one callback URL per object type**, not one per channel. So there are three separate setups, each with its own object, URL, fields and token:

| Meta object | Channels | Callback URL |
|---|---|---|
| `Page` | Messenger + Facebook | `https://<api-host>/api/v1/webhooks/meta/page` |
| `Instagram` | Instagram | `https://<api-host>/api/v1/webhooks/instagram` |
| `WhatsApp Business Account` | WhatsApp | `https://<api-host>/api/v1/webhooks/whatsapp` |

**A field is delivered only when it is subscribed at both levels.** A connection that shows "connected" in the channels page can still receive nothing if either is missing:

1. **App level** (developer dashboard → Webhooks): the object, the URL, the verify token and the fields. This is a manual operator step; the server can neither read nor set it.
2. **Asset level** (the Page or the WhatsApp Business Account): the server does it on connect and removes it on disconnect.

### 1) The Page object (Messenger and Facebook)

URL: `https://<api-host>/api/v1/webhooks/meta/page`

Fields: `messages`, `messaging_postbacks`, `messaging_referrals`, `message_deliveries`, `message_reads`, `message_reactions`, `message_echoes`, `messaging_handovers`, `feed`, `mention`.

The server sorts each delivery itself: whatever sits under `messaging` (private chat) goes to Messenger, whatever sits under `changes` (posts, comments, mentions) goes to Facebook. It does not matter which of the two channels is connected; one URL covers both and a second URL is never registered on the same object.

Signature: `MESSENGER_APP_SECRET` (or `META_APP_SECRET` when empty). Handshake: `MESSENGER_VERIFY_TOKEN`. The WhatsApp token is never accepted here.

The older `/api/v1/webhooks/messenger` and `/api/v1/webhooks/facebook` URLs still work for anyone who registered them, but they are **not registered together** on the same object: register `meta/page` only.

### 2) The Instagram object

URL: `https://<api-host>/api/v1/webhooks/instagram`

Fields: `messages`, `messaging_postbacks`, `message_reactions`, `messaging_seen`, `comments`, `mentions`, `live_comments`.

Important: subscribing the linked Page (`/{page-id}/subscribed_apps`) does **not** configure Instagram webhooks and does not accept their fields. Instagram's fields are picked in the app dashboard on the Instagram object itself; the server only subscribes the Page that the account is linked to.

Production requirements: `instagram_manage_messages` and `instagram_manage_comments` need Advanced Access and App Review, and the account must be a professional one (Business or Creator) linked to a Facebook Page. Without them notifications may not arrive even though the connect succeeded.

Signature: `INSTAGRAM_APP_SECRET`. Handshake: `INSTAGRAM_VERIFY_TOKEN`.

### 3) The WhatsApp Business Account object

URL: `https://<api-host>/api/v1/webhooks/whatsapp`

Field: `messages` (it carries delivery and failure statuses); adding the account, number and template update fields is recommended.

Set in the app dashboard: WhatsApp → Configuration, once for the whole app. Subscribing the app to the business account (`/{waba-id}/subscribed_apps`) is done by the server on connect and removed on disconnect, but it **does not replace** setting the URL in the dashboard.

Signature: `WHATSAPP_APP_SECRET`. Handshake: `WHATSAPP_VERIFY_TOKEN`.

### Checking that it works

On the channels page press "Diagnose channel": it shows the connection, permissions, the Page subscription (asked of Meta live), the server's webhook readiness, the last webhook received and the last error. If no event has ever arrived, the likeliest cause is the app-level URL missing in the dashboard (it cannot be checked from the server). The app must be **Live** for real users' events to arrive.

Disconnecting a channel removes its subscription from Meta. If another connected channel still shares the Page (Messenger with Facebook) the subscription is kept and narrowed to the remaining channel's fields. If Meta cannot be reached the local disconnect still succeeds and the removal is marked "pending" so it can be retried.

### Permissions per channel

Each channel asks only for what it needs and never carries another channel's permissions:

| Channel | Permissions | Pages offered when connecting |
|---|---|---|
| Messenger | `pages_show_list`, `pages_read_engagement`, `pages_manage_metadata`, `pages_messaging` | Pages with a `MESSAGING` or `MANAGE` task |
| Facebook | `pages_show_list`, `pages_read_engagement`, `pages_manage_metadata`, `pages_manage_posts`, `pages_manage_engagement`, `pages_read_user_content`, `read_insights` | Any Page with a management task (`MANAGE`, `CREATE_CONTENT`, `MODERATE`, `ANALYZE`, `ADVERTISE` or `MESSAGING`) |
| Instagram | Instagram's own message, comment and publish permissions plus `pages_messaging` | Pages with a `MESSAGING` or `MANAGE` task |

The Facebook channel does not ask for `pages_messaging`: customer chat belongs to Messenger, and a store that connects its Page only for posts, comments and insights is not asked for access to the Page's private messages. Connect Messenger as well for chat.

## 4. Development mode and testers

While the app is in development mode only its Admins, Developers, and Testers can complete the dialog. Add the operator account under Roles → Testers and have it accept the invite before connecting, otherwise the callback reports `access_denied`. Going public requires App Review with Advanced Access for `pages_messaging`, `instagram_manage_messages`, and `pages_manage_metadata`.

## 5. Environment variables

```text
META_APP_ID             App ID from Settings → Basic
META_APP_SECRET         App secret — server-side only, never sent to the browser
META_OAUTH_REDIRECT_URI exact callback URL registered in Meta; derived from API_PUBLIC_BASE_URL when empty
API_PUBLIC_BASE_URL     canonical public API origin; also drives the webhook URLs
META_INSTAGRAM_CONFIG_ID    optional — Instagram's own Facebook Login for Business configuration id (Facebook and Messenger never use it)
MESSENGER_APP_SECRET    verifies Messenger and Facebook webhook signatures (META_APP_SECRET is used when empty)
MESSENGER_VERIFY_TOKEN  verify token for the Messenger and Facebook webhook registration
WHATSAPP_APP_SECRET     verifies WhatsApp webhook signatures (the same app secret, from Settings → Basic)
WHATSAPP_VERIFY_TOKEN   verify token for WhatsApp only — any random text, set here and in WhatsApp → Configuration
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

## 8. "<App> can't onboard customers right now" in the Facebook window

This appears after the Facebook login step; the Connect button then spins forever and no authorization code ever reaches the page. It comes from Meta, not from our code or the store's settings, so retrying will not help.

It means the app is **not fully registered as a Tech Provider**, so it may not onboard other businesses through Embedded Signup. Everything is completed in the Meta console for the app and for the Business Portfolio that owns it, in this order:

1. **Business Verification** of the owning portfolio (Business settings > Security center).
2. **Access Verification** and registration as a **Tech Provider** (App Dashboard > WhatsApp > Tech Provider onboarding).
3. **App Review** with **Advanced Access** for `whatsapp_business_management` and `whatsapp_business_messaging`.
4. The app is in **Live** mode, not Development.
5. `META_APP_ID` and `META_WHATSAPP_CONFIG_ID` on the server belong to this same app (the config comes from Facebook Login for Business > Configurations).

Notes:

- An account with an **Admin, Developer or Tester** role on the app may be allowed to try the connect for its own account before the steps above are finished, so do not test with an account that has no role.
- Some teams finish every step and still see the message for days until Meta refreshes the app's status. If all of the above is done and it persists, open a Meta Support ticket with the **Session ID** shown at the bottom of the window (like `01a1fc32-...`); it is what support asks for.
- **Facebook and Messenger** connect are unaffected: they use ordinary Page permissions.

## 9. Importing old Messenger conversations

The first time Messenger is connected, the Page's history is read from Meta once (the last 90 days). The owner can also run it by hand to recover a window in which the webhook was down: `POST /api/v1/integrations/messenger/backfill` with `{"days": 14}` or `{"since": "2026-11-20T00:00:00Z"}` (needs `settings:write`); `GET` on the same path reports where it got to.

- Meta returns details for only the **latest 20 messages** of each conversation. Older ones are skipped and counted, so this is a recovery tool, not a full export.
- These old messages start no first-response clock, run no AI, send no notification and add nothing to the unread count.
- Running it again is safe: a message is keyed by Meta's id, so it is never written twice, even when windows overlap or the webhook already delivered it.
- A run stops and can be resumed when Meta asks to slow down, and when the `provider.messenger` circuit breaker is open. That breaker is shared with sending, so a failing backfill can pause sending for up to 30 seconds.
- Messenger only: it needs `pages_messaging`, which a Facebook-only connection no longer asks for.
