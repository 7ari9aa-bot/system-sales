# جرد واجهة Messenger — الصلاحيات والنطاقات

هذا المستند جردٌ لصلاحيات Meta (Permissions/Scopes) ذات الصلة بـ Messenger وصفحات فيسبوك، مقابل ما يطلبه كود `system-sales` فعليًا وما مُنح فعليًا لصفحة **Fidsas** (`1504830666036731`). المصدر الوحيد المقروء في الكود هو ملفان: `backend/app/modules/customers/meta_scopes.py` و`backend/app/modules/customers/meta_oauth.py`. كل ما لم يُتحقَّق منه من هذين الملفين أو من قائمة الصلاحيات الممنوحة الحالية موسوم بـ **غير مُتحقَّق**.

ملاحظات منهجية:

- «مطلوبة في الكود» تعني أن النطاق يظهر في قائمة `scope` التي تُرسل إلى نافذة Meta، أو أن الكود يقرأ نتيجة منحه. النطاقات التي لا تظهر في هذين الملفين لا يعني بالضرورة أن باقي الكود لا يستعملها — فقط أنه لا يُطلب منحها.
- قوائم النطاقات الثلاث في الكود: `MESSENGER_SCOPES` (`meta_scopes.py:10`)، و`FACEBOOK_PAGE_SCOPES` (`meta_scopes.py:18-23`) المضافة إلى قائمة Messenger في `FACEBOOK_SCOPES` (`meta_scopes.py:24`)، و`_INSTAGRAM_SCOPES` (`meta_oauth.py:63-70`). الاختيار حسب القناة يحدث في `_build_authorize_url` (`meta_oauth.py:152`, `:154`, `:156`).
- بعد عودة Meta يقرأ الكود `/me/permissions` (`meta_oauth.py:487`) ويستخرج منها الممنوح فقط عبر `granted_scopes_from_permissions` (`meta_scopes.py:39-51`)، ثم يرفض ربط قناة Facebook إذا نقص أي نطاق من `FACEBOOK_PAGE_SCOPES` عبر `missing_facebook_scopes` (`meta_scopes.py:27-36`) ويرسل العلم `link.scopes_missing` (`meta_oauth.py:495`).
- عمود «ممنوحة لصفحة Fidsas» مبني على قائمة الصلاحيات الممنوحة المسجَّلة للصفحة كما وردت في الطلب: `pages_manage_engagement, pages_manage_metadata, pages_manage_posts, pages_messaging, pages_read_engagement, pages_read_user_content, pages_show_list, public_profile, read_insights`. لم يُتحقَّق في هذه الجلسة من قراءة `/me/permissions` مباشرةً — **غير مُتحقَّق** إن كانت هذه القائمة لا تزال مطابقة لحظة القراءة.

## الصلاحيات والنطاقات (Permissions / Scopes)

| الصلاحية | ما تفتحه (What it unlocks) | مطلوبة في الكود (file:line) | ممنوحة لصفحة Fidsas | تحتاج App Review |
|---|---|---|---|---|
| `pages_messaging` | قراءة وكتابة محادثات Messenger على الصفحة: استقبال أحداث الرسائل عبر الـ webhook وإرسال رسائل عبر Send API، والحصول على PSID والـ conversation id. هي النطاق الأساسي لأي قناة Messenger. | نعم — `meta_scopes.py:10` (ضمن `MESSENGER_SCOPES`، ومنها تُشتق `_MESSENGER_SCOPES` في `meta_oauth.py:62` وتُرسل في `:156`)، وكذلك `meta_oauth.py:64` لقناة Instagram | نعم | نعم — تحتاج Advanced Access + مراجعة ميزة Messenger (App Review) لتعمل مع مستخدمين خارج أدوار التطبيق. التفاصيل الحالية للمراجعة **غير مُتحقَّقة** |
| `pages_utility_messaging` | إرسال رسائل Utility (غير ترويجية) وقوالبها إلى المستخدم خارج نافذة المراسلة القياسية، بحسب مستندات Meta لـ Utility Messages. | لا — لا يظهر في أي من الملفين المقروءين | لا | نعم — Advanced Access. **غير مُتحقَّق** إن كانت مراجعة Utility Templates منفصلة عن `pages_messaging` |
| `pages_show_list` | سرد الصفحات التي يديرها المستخدم (`/me/accounts`) مع رمز الوصول الخاص بكل صفحة — وهو ما يعتمد عليه الربط كله لاختيار الصفحة ورمزها. | نعم — `meta_scopes.py:10`، و`meta_oauth.py:64` | نعم | نعم (Advanced Access). **غير مُتحقَّق** من الحالة الحالية لمراجعة هذا النطاق تحديدًا |
| `pages_read_engagement` | قراءة تفاعل الجمهور مع الصفحة ومحتواها (بما في ذلك قراءة منشورات الصفحة وتعليقات الزوّار) عبر Pages API؛ تمهيد لقراءة ما يكتبه الناس على الصفحة. | نعم — `meta_scopes.py:10`، و`meta_oauth.py:64` | نعم | نعم (Advanced Access). **غير مُتحقَّق** من تفاصيل المراجعة الحالية |
| `pages_manage_metadata` | إدارة بيانات الصفحة الوصفية، وأهم ما يعنيه عمليًا هنا: اشتراك الصفحة في تطبيقك واستقبال أحداث الـ webhook — الكود ينادي `/{page-id}/subscribed_apps` بـ POST (`meta_oauth.py:274`) ويقرأ الاشتراك الحالي (`meta_oauth.py:244`)؛ بدون هذا النطاق يرفض Meta الاشتراك. | نعم — `meta_scopes.py:10`، و`meta_oauth.py:64` | نعم | نعم (Advanced Access). **غير مُتحقَّق** من تفاصيل المراجعة الحالية |
| `pages_manage_engagement` | الرد على تعليقات الزوّار وإدارتها (إخفاء/حذف/إعجاب) على منشورات الصفحة، وليس على الرسائل الخاصة. | نعم — لكن لقناة Facebook فقط: `meta_scopes.py:20` ضمن `FACEBOOK_PAGE_SCOPES`، وتُضاف في `meta_scopes.py:24` وتُرسل في `meta_oauth.py:154`؛ لا تُطلب لقناة Messenger وحدها | نعم | نعم (Advanced Access). **غير مُتحقَّق** من تفاصيل المراجعة الحالية |
| `pages_manage_posts` | نشر منشورات على الصفحة والجدولة/التعديل/الحذف. | نعم — لقناة Facebook فقط: `meta_scopes.py:19`، `meta_scopes.py:24`، `meta_oauth.py:154` | نعم | نعم (Advanced Access). **غير مُتحقَّق** من تفاصيل المراجعة الحالية |
| `pages_read_user_content` | قراءة المحتوى الذي أنشأه المستخدمون على الصفحة: التعليقات والمنشورات التي كتبها الزوّار (مصدر قائمة تعليقات الـ inbox عبر حقل `feed`). | نعم — لقناة Facebook فقط: `meta_scopes.py:21`، `meta_scopes.py:24`، `meta_oauth.py:154` | نعم | نعم (Advanced Access). **غير مُتحقَّق** من تفاصيل المراجعة الحالية |
| `read_insights` | قراءة إحصاءات الصفحة (Insights): الوصول والتفاعل وأرقام الجمهور. لا علاقة له بإرسال أو استقبال الرسائل. | نعم — لقناة Facebook فقط: `meta_scopes.py:22`، `meta_scopes.py:24`، `meta_oauth.py:154` | نعم | نعم (Advanced Access). **غير مُتحقَّق** من تفاصيل المراجعة الحالية |
| `business_management` | إدارة أصول Business Manager (الصفحات، الحسابات الإعلانية، المستخدمون) وقراءة بنية الأعمال. غير لازم لمسار Messenger الحالي لأنه يعمل برمز الصفحة من `/me/accounts`. | لا — لا يظهر في أي من الملفين المقروءين | لا | نعم (Advanced Access). **غير مُتحقَّق** من التفاصيل الحالية |
| `public_profile` | الاسم والصورة العامة للمستخدم الذي منح الصلاحية؛ يمنحه Meta افتراضيًا لكل تطبيق. | لا — لا يظهر في قائمتي النطاقات في الكود؛ يبدو أنه يُمنح تلقائيًا. **غير مُتحقَّق** إن كان يظهر في `/me/permissions` بوصفه مطلوبًا صريحًا | نعم (ضمن القائمة المسجَّلة) | لا — يُمنح افتراضيًا ولا يخضع لمراجعة |
| Human Agent (ميزة/وسم `HUMAN_AGENT`) | ليست صلاحية مستقلة، بل وسم رسالة (message tag) يتيح ردًّا بشريًا يدويًا خلال نافذة 7 أيام منفصلة عن نافذة الـ 24 ساعة القياسية، بحسب سياسة Messenger Platform. يشترط عمليًا امتلاك `pages_messaging` بـ Advanced Access واجتياز مراجعة الميزة. | لا — لا يظهر أي ذكر لـ `HUMAN_AGENT` أو `human_agent` في الملفين المقروءين؛ ولا يمكن الجزم بأن طبقة الإرسال لا تستعمله لأنها خارج نطاق القراءة — **غير مُتحقَّق** | لا ينطبق (ليست صلاحية قابلة للمنح)؛ الاعتماد على `pages_messaging` وهي ممنوحة | نعم — يتطلب مراجعة ميزة/وصول متقدم لـ `pages_messaging` ووسم Human Agent. التفاصيل الحالية **غير مُتحقَّقة** |

### خلاصة الفجوات

- **مطلوب في الكود وغير ممنوح:** لا شيء. كل نطاق يطلبه الكود (`pages_show_list`, `pages_read_engagement`, `pages_manage_metadata`, `pages_messaging`, `pages_manage_posts`, `pages_manage_engagement`, `pages_read_user_content`, `read_insights`) موجود في قائمة الممنوح لصفحة Fidsas. (مبني على القائمة المسجَّلة؛ التحقق المباشر من `/me/permissions` **غير مُتحقَّق**.)
- **ممنوح وغير مطلوب في الكود:** `public_profile` — ممنوح لكنه لا يُطلب صراحةً في أي من الملفين.
- **ممنوح لكن لا تستعمله قناة Messenger وحدها:** `pages_manage_posts`, `pages_manage_engagement`, `pages_read_user_content`, `read_insights` تُطلب لقناة Facebook فقط (`meta_scopes.py:18-24`)، فاتصال Messenger وحده يحملها بلا استعمال.
- **غير مطلوب وغير ممنوح لكنه مطلوب وظيفيًا لميزات ناقصة:** `pages_utility_messaging` (رسائل Utility خارج نافذة الـ 24 ساعة) و`business_management` (إدارة أصول Business Manager)، ووسم `HUMAN_AGENT` (رد بشري خلال 7 أيام). غيابها يعني أن الرد خارج نافذة المراسلة القياسية غير متاح من المنتج اليوم.

## Send API

ما يستطيعه Messenger Send API مقابل ما يُرسله كود `system-sales` فعليًا. المصادر المقروءة لهذا القسم
فقط: `backend/app/modules/conversations/gateway/messenger.py` (280 سطرًا)،
`gateway/messenger_media.py` (136)، `conversations/policy.py` (260).
كل المسارات تخرج من نقطة واحدة: `POST {graph}/{v27.0}/me/messages` — `messenger.py:201`.
الحالة: **used** = يُبنى الحقل فعليًا على السلك، **partial** = المسار موجود لكن ناقص (لا تحقّق، لا fallback،
أو لا يُرسل الحقل المطلوب)، **missing** = لا ذكر له في الملفات الثلاثة.

| Capability | Meta allows | Used in code (file:line) | Status | UI effect |
|---|---|---|---|---|
| Text | `message.text` حتى 2000 حرف؛ داخل النافذة حر، خارجها يحتاج tag | `messenger.py:242` (فرع النص)، و`:239-240` (التعليق كرسالة نصية ثانية بعد المرفق) | used | فقاعة نص في محادثة العميل الحقيقية؛ لا شيء يُقصّ لأن الحد الأقصى 2000 حرف غير مُتحقَّق منه |
| Image attachment | `type: image`، رابط https عام، ≤ 8 MB | `messenger_media.py:14` (الحد)، `:37-43` (التحويل)، `messenger.py:226-235` | used | صورة داخل الفقاعة تُفتح بملء الشاشة |
| Video attachment | `type: video`، ≤ 25 MB | `messenger_media.py:14`، `messenger.py:226-235` | used | مشغّل فيديو داخل المحادثة |
| Audio attachment | `type: audio`، ≤ 25 MB | `messenger_media.py:14`، `messenger.py:226-235` | used | مشغّل صوت/رسالة صوتية |
| File attachment | `type: file`، ≤ 25 MB؛ أي نوع غير معروف يصبح `file` | `messenger_media.py:43` (fallback إلى `file`)، `:46-55`، `messenger.py:235` | used | بطاقة تنزيل باسم الملف |
| Quick replies | حتى 13 زرًا، `title` ≤ 20 حرفًا، `quick_replies[]` على الرسالة | لا وجود لـ `quick_replies` في `messenger.py` (لا مسار يبنيه) | missing | أزرار فوق لوحة الكتابة عند العميل بضغطة واحدة (تأكيد طلب، اختيار فرع، تقييم) |
| Generic template | حتى 10 عناصر (carousel) مع أزرار | `messenger.py:210-224` يمرّر `template_name`+`template_vars` كما هي إلى `template_type` | partial | كاروسيل بطاقات منتجات؛ يعمل فقط إن كان `template_vars` مبنيًا بشكل صحيح من الخارج، ولا تحقّق من عدد العناصر |
| Button template | حتى 3 أزرار + نص | نفس المسار `messenger.py:210-224` | partial | رسالة بخيارات (تأكيد/إلغاء) |
| Media template | عنصر واحد (صورة/فيديو) + زر واحد | نفس المسار `messenger.py:210-224` | partial | صورة كبيرة بزر تحته |
| Receipt template | `template_type: receipt` مع order/summary/elements | نفس المسار `messenger.py:210-224` (لا بناء لـ order/summary) | partial | إيصال طلب منسّق بالأسعار والمجموع؛ حاليًا لا يُبنى الإيصال نفسه |
| sender_action: `typing_on` | `POST` بـ `sender_action` بدل `message` | لا ذكر لـ `sender_action` في الملفات الثلاثة | missing | «يكتب الآن…» عند العميل أثناء رد الموظف |
| sender_action: `typing_off` | كما أعلاه | لا ذكر | missing | إيقاف مؤشر الكتابة |
| sender_action: `mark_seen` | `sender_action: mark_seen` | لا ذكر؛ و`parse_status_updates` تُرجع `[]` (`messenger.py:121-124`) فحالة القراءة لا تُنقل للاتجاهين | missing | «تمت الرؤية/Seen» تحت آخر رسالة للموظف في Messenger العميل |
| Reactions | `sender_action: react`/`unreact` (دعم متغيّر؛ **unverified** بعد تعديلات 2026) | لا ذكر لـ `react`/`unreact` | missing | قلب/إيموجي على رسالة — عنصر أساسي في Messenger |
| `reply_to` (quote) | `message.reply_to.mid` يقتبس رسالة سابقة | لا ذكر لـ `reply_to` | missing | اقتباس الرسالة داخل الفقاعة (شكل Messenger المعتاد للرد على رسالة محددة) |
| Persistent menu | Messenger Profile API `POST /me/messenger_profile` `persistent_menu` | لا ذكر لـ `messenger_profile` | missing | قائمة ☰ ثابتة أسفل المحادثة عند العميل |
| Get started button | `messenger_profile` → `get_started` | لا ذكر | missing | زر «ابدأ» في أول محادثة |
| Greeting | `messenger_profile` → `greeting` | لا ذكر | missing | رسالة ترحيب تلقائية قبل أي رسالة |
| Ice breakers | `messenger_profile` → `ice_breakers` | لا ذكر | missing | 4 أسئلة جاهزة تظهر عند فتح المحادثة أول مرة |
| Message tags (`HUMAN_AGENT`, 7 أيام) | `messaging_type: MESSAGE_TAG` + `tag: HUMAN_AGENT`، رد بشري فقط، 7 أيام من آخر رسالة للعميل | السياسة تحسبه: `policy.py:51-53`، `:60`، `:88-89`، `:133-149` — لكن `messenger.py` لا يضع `tag` ولا `messaging_type` على السلك | partial | بدون الحقل: أي رد بعد 24 ساعة يفشل بـ error من Meta رغم أن السياسة سمحت به |
| 24h standard window | حر داخل 24 ساعة من آخر رسالة للعميل؛ خارجها template/tag فقط | `policy.py:47`، `:58-66`، `:120-128` (السماح)، `:162-196` (الرفض/القالب) | used | الكومبوزر يمنع/يحذّر بعد 24 ساعة، ورسالة الخطأ تشرح السبب |
| One-time notification | `notification_messages` token، رسالة واحدة، صالح سنة | لا ذكر لـ `notification_messages` | missing | «ذكّرني عندما يتوفر» — إشعار واحد بعد إغلاق النافذة |
| Recurring notification | `notification_messages_frequency` (daily/weekly/…) بموافقة العميل | لا ذكر | missing | إشعارات متكررة للعروض/التذكيرات |
| Private replies to comments | `recipient: {post_id|comment_id}` على `/PAGE-ID/messages`، رسالة واحدة، ≤ 7 أيام | الاستقبال موجود `messenger.py:126-130` (`parse_comments`)؛ لا مسار إرسال بـ `post_id`/`comment_id` | partial | «رد خاص» على تعليق يحوّله لمحادثة Messenger |
| User profile fields (`name`, `profile_pic`) | `GET /{psid}?fields=first_name,last_name,profile_pic` + Business Asset User Profile Access (App Review) | `messenger.py:178` يضع `customer_name=None` صراحةً؛ لا طلب HTTP للملف الشخصي | missing | اسم وصورة العميل الحقيقيان في قائمة المحادثات ورأسها بدل PSID رقمي |

### ملاحظات تنفيذية

1. **أعلى أولوية تقنية**: `tag`/`messaging_type` غير موجودين في `messenger.py` — أي أن نافذة الـ 7 أيام
   في `policy.py:133-149` قرار محلي فقط لا يعرفه Meta؛ الردّ البشري بعد 24 ساعة سيُرفض من الـ API.
2. **`mark_seen` + `typing_on`** أرخص مكسب: طلبان صغيران يعطيان إحساس «الموظف موجود الآن».
3. **`reply_to`** مطلوب لأن واجهة Fihrist ترسل `replyTo` أصلًا من `ChannelChat.jsx:235,268` — لكن
   الـ adapter يتجاهله بصمت، فيُفقد الاقتباس دون أي خطأ.
4. **`quick_replies`**: زر «أزرار» في الواجهة يعمل لإنستجرام فقط (`ChannelChat.jsx:233-235`) — مرشّح
   لنسخه إلى Messenger لأن Meta تدعم 13 زرًا.
5. **الملف الشخصي**: بدون `name`/`profile_pic` ستبدو محادثات Messenger أرقامًا، وهو أكبر فرق بصري عن
   Messenger الحقيقي.
6. ما لم يُتحقَّق منه من الكود أو من docs.meta (وسم `unverified` أعلاه): دعم `react`/`unreact` الحالي،
   وأي حدود رقمية لم أذكرها صراحة (عدد أزرار quick replies، 2000 حرف، حدود القوالب) مصدرها صفحات
   Send API في developers.facebook.com ولم تُقرأ سطرًا بسطر في هذا القسم.

## Webhook fields

نطاق هذا القسم: حقول الـ webhook الخاصة بـ Messenger وصفحة فيسبوك. عمود «مشترك على الصفحة الحيّة»
يعكس قائمة الحقول المفروضة على صفحة **Fidsas** (`1504830666036731`) بتاريخ 2026-11-22، وعمود
«مقروء في الكود» يعني أن `MessengerAdapter` في
`backend/app/modules/conversations/gateway/messenger.py` (أو دالة يستدعيها) تقرأ محتوى هذا الحقل
فعليًا. الفرق بين العمودين هو بيت القصيد: حقل مشترك وغير مقروء يعني حجم أحداث ندفعه بلا مقابل.

ما يطلبه الكود عند الربط — `subscribed_fields(provider)` في
`backend/app/modules/customers/meta_oauth.py:83` والثوابت في `:74-80`:

| القناة (provider) | الحقول المكتوبة عند الربط |
|---|---|
| `messenger` (الافتراضي) | `messages,messaging_postbacks,messaging_referrals,message_deliveries` |
| `facebook` | ما سبق + `feed` |
| `instagram` | ما سبق + `comments,message_reactions,messaging_seen` |

حقلان على الصفحة الحيّة — `message_echoes` و`message_reads` — لا يظهران في أي من القوائم الثلاث،
أي أن الاشتراك الحيّ أوسع مما يكتبه هذا الكود: إمّا عُدّل يدويًا من App Dashboard أو كتبته نسخة
أقدم. إعادة الربط عبر مسار OAuth لا تحذفهما لأن `meta_oauth.py:265-271` يجمع المطلوب مع الموجود
في الصفحة بدل استبداله، فيبقيان مشتركين سواء قرأهما أحد أم لا.

### كل حقول webhook في Messenger

| الحقل | مشترك على الصفحة الحيّة | مقروء في الكود (file:line) | ماذا يعطي الواجهة |
|---|---|---|---|
| `messages` | نعم | **نعم** — `gateway/messenger.py:131` (`parse_inbound`) ثم `:145` (`_parse_message_event`)؛ نص + أول مرفق فقط (`image` / `audio`→voice / `video` / `file`، وأي نوع آخر يصبح `unsupported`) | المحادثة نفسها: فقاعات النص والوسائط الواردة في الـ inbox، وإنشاء صف العميل، وعدّاد غير المقروء. |
| `messaging_postbacks` | نعم | **لا** — لا يوجد فرع `postback` في `messenger.py` (الموجود لإنستجرام فقط: `gateway/instagram.py:220` و`:349`) | لا شيء. العميل الذي يضغط زرًّا أو قائمة أو Get-Started لا يحصل على أي رد ولا يُنشأ له أي أثر: الحدث يُترجَم إلى صفر رسائل. |
| `message_deliveries` | نعم | **لا** — `messenger.py:121` الدالة `parse_status_updates` ترجع `[]` عن قصد («inbound-only for now») | لا شيء. لا علامة ✓✓ على فقاعات Messenger الصادرة؛ رسالة لم تصل للعميل تبدو مطابقة لرسالة قُرئت. |
| `message_reads` | نعم | **لا** — نفس الدالة الفارغة، `messenger.py:121-124` | لا شيء. لا إشعار قراءة، فحالة «شوهد» وخدمة إشارة القراءة تظلان عمياء لقناة Messenger. |
| `message_reactions` | لا | **لا** — لا فرع `reaction` في `messenger.py` (لإنستجرام فرع في `gateway/instagram.py:225`) | لا شيء. تفاعلات العميل على رسائل المتجر لا تظهر، ولا يستطيع الموظف التفاعل من الـ inbox. |
| `message_echoes` | نعم | **لا** — لا شيء يقرأ `is_echo` لقناة Messenger (الفحص الوحيد في الشجرة عند `gateway/instagram.py:233`) | المقصود ألّا يعطي شيئًا، لكن انظر ملاحظة الخطر: echo يصل على حقل `messages` يُحتسب رسالة عميل واردة. |
| `messaging_referrals` | نعم | **لا** — لا معالجة لـ `referral` في أي ملف تحت `modules/conversations` | لا شيء. مصدر وصول العميل (إعلان أو رابط `m.me` وحمولة `ref`) يُفقد، فلا إسناد للإعلانات ولا سؤال «أي حملة بدأت هذه المحادثة» له جواب في الواجهة. |
| `messaging_optins` | لا | **لا** | لا شيء. لا حالة موافقة تسويقية؛ الموافقة يجب جمعها بطريق آخر. |
| `messaging_handovers` | لا | **لا** | لا شيء. انتقال التحكم في المحادثة من/إلى تطبيق آخر غير مرئي — فيظل الـ inbox يتصرّف في محادثة لم يعد يملكها. |
| `messaging_policy_enforcement` | لا | **لا** | لا شيء. صفحة محظورة أو مقيّدة بسياسة Meta لا تظهر للمالك كتحذير. |
| `messaging_feedback` | لا | **لا** | لا شيء. استبيانات تقييم العميل التي ترسلها Meta تُهمل. |
| `standby` | لا | **لا** | لا شيء. الرسائل التي لا يراها التطبيق إلا في وضع standby (تطبيق آخر يملك المحادثة) لا تصل للـ inbox. |
| `inbox_labels` | لا | **لا** | لا شيء. لا مزامنة وسوم؛ الوسوم المعروضة في الـ inbox محلية فقط وتنحرف عن وسوم Meta. |
| `feed` | نعم | **نعم** — `gateway/messenger.py:126` (`parse_comments`) ثم `gateway/base.py:117` (`parse_meta_comment_changes`، الفلترة عند `base.py:114` و`:137`) | تعليقات المنشورات العامة (إضافة/تعديل/حذف، الكاتب، الرابط الدائم، عدد الإعجابات) في شاشة التعليقات الاجتماعية — بيانات تفاعل، ولا تُمرَّر إلى الذكاء الاصطناعي ولا إلى المحادثة عن قصد. |

### غير مشترك وغير مقروء

`messaging_optins`, `messaging_handovers`, `messaging_policy_enforcement`, `messaging_feedback`,
`standby`, `inbox_labels`, `message_reactions` — الكود لا يطلبها ولا يوجد لها أي محلّل، فلا سلوك
جزئي يُشرح: القدرة غائبة من الطرفين.

### مشترك وغير مقروء

`message_deliveries`, `message_reads`, `message_echoes`, `messaging_postbacks`,
`messaging_referrals`. خمسة من سبعة حقول حيّة تُدفع كحجم أحداث ثم تُهمل. مرتّبة بما يلاحظه المالك:

1. `message_deliveries` / `message_reads` — لا حالة تسليم ولا قراءة على رسائل Messenger الصادرة،
   وسؤال «هل وصلت رسالتي للعميل؟» بلا جواب.
2. `messaging_postbacks` — ضغطة زر هي فعل من العميل لا يحصل على أي رد إطلاقًا.
3. `messaging_referrals` — مصدر click-to-Messenger لا يمكن استرجاعه لاحقًا؛ الحمولة الخام لا
   تُحفظ أصلًا، فلا يمكن تعبئتها بأثر رجعي.
4. `message_echoes` — لا يوجد محلّل echo، و`MessengerAdapter.parse_inbound` (`messenger.py:131`)
   لا يفحص `is_echo`: أي echo يصل على حقل `messages` يتحوّل إلى رسالة **واردة** من معرّف الصفحة
   نفسها، أي أن رد المتجر على عميله قد يظهر في المحادثة كرسالة عميل. هذا البند الوحيد هنا خطأ
   صحّة لا ميزة ناقصة، ويجب إصلاحه قبل توصيل الحقل.

الحقلان الوحيدان من الحقول الحيّة اللذان تصل حمولتهما إلى قاعدة البيانات هما `feed` و`messages`.
