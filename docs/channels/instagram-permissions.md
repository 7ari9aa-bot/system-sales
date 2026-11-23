# جرد صلاحيات Instagram API — النطاقات وما تفتحه وما يطلبه الكود

جردٌ لصلاحيات Instagram Platform كما هي في وثائق Meta الرسمية (مقروءة 2026-11-23)، مقابل
ما يطلبه `system-sales` فعليًا. المصدر الوحيد في الكود لطلب النطاقات هو
`backend/app/modules/customers/meta_oauth.py:63-71` (`_INSTAGRAM_SCOPES`)، والقائمة
المطلوبة للمقارنة في `backend/app/modules/customers/meta_scopes.py:44-48`
(`INSTAGRAM_REQUIRED_SCOPES`).

كل ما لم يُقرأ من الوثيقة الرسمية أو من الكود في هذه الجلسة موسوم **غير مُتحقَّق**.

## 1. أوضاع الوصول الثلاثة (لا تخلط بينها)

| الوضع | المصادقة | المضيف | ملاحظة |
|---|---|---|---|
| **Instagram API with Unified Login** (الحديث) | Facebook Login for Business، نطاقات `instagram_*` | `graph.facebook.com` | الوضع الذي تنتقل إليه Meta؛ نطاقاته هي نفس نطاقات Facebook Login |
| **Instagram API with Instagram Login** | Instagram User access token، نطاقات `instagram_business_*` | `graph.instagram.com` | لا يحتاج صفحة فيسبوك مربوطة؛ لا يصل للإعلانات ولا للوسم |
| **Instagram API with Facebook Login** (القديم، ما يستعمله الكود) | صفحة فيسبوك مربوطة + `pages_*` | `graph.facebook.com` | يحتاج الصفحة مربوطة بحساب Instagram الاحترافي |

القيم القديمة `business_basic` / `business_content_publish` / `business_manage_comments` /
`business_manage_messages` **مُلغاة من 27 يناير 2025** — أي كود ما زال يطلبها لن يستطيع نداء
نقاط Instagram.

مصدر: <https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login>
و<https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-unified-login/permissions>

## 2. النطاقات (`instagram_*`) وما تفتحه

| الصلاحية | ما تفتحه (نص Meta) | مطلوبة في الكود | تحتاج App Review |
|---|---|---|---|
| `instagram_basic` | قراءة بروفايل حساب Instagram ووسائطه | نعم — `meta_oauth.py:66` | نعم للوصول المتقدم (حسابات لا تملكها) |
| `instagram_manage_messages` | إرسال واستقبال رسائل Instagram | نعم — `meta_oauth.py:66`، ومذكورة في `meta_scopes.py:45` | نعم |
| `instagram_manage_comments` | قراءة الردود على التعليقات وإخفاؤها وحذفها، واستقبال الإشارات (mentions) | نعم — `meta_oauth.py:70`، `meta_scopes.py:46` | نعم |
| `instagram_content_publish` | نشر منشورات وريلز وستوريز وكاروسيل | نعم — `meta_oauth.py:70`، `meta_scopes.py:47` | نعم |
| `instagram_manage_insights` | قراءة إحصاءات الحساب والوسائط | **لا — فجوة** (انظر §5) | نعم |
| `instagram_manage_events` | إنشاء وإدارة أحداث Instagram | لا — غير مستعمل | نعم |
| `instagram_shopping_tag_products` | وسم المنتجات داخل الوسائط | لا — غير مستعمل | نعم |
| `business_management` | إدارة أصول محفظة الأعمال | لا — غير مستعمل | نعم |
| `ads_management` / `ads_read` | إدارة وقراءة الإعلانات | لا — غير مستعمل | نعم |

## 3. نطاقات `instagram_business_*` (Instagram Login) ومقابلها

| المستعمل اليوم في Instagram Login | المطلوب في Unified Login |
|---|---|
| `instagram_business_basic` | `instagram_basic` |
| `instagram_business_manage_messages` | `instagram_manage_messages` |
| `instagram_business_manage_comments` | `instagram_manage_comments` |
| `instagram_business_content_publish` | `instagram_content_publish` |
| `instagram_business_manage_insights` | `instagram_manage_insights` |

نطاقات الرسائل في Instagram Login تحتاج أيضًا `instagram_business_basic` مع
`instagram_business_manage_messages` (المستند يذكرهما معًا لكل نداء إرسال).

## 4. نطاقات فيسبوك التي يضيفها مسار Facebook Login

| الصلاحية | لماذا | مطلوبة في الكود |
|---|---|---|
| `pages_show_list` | سرد الصفحات ورموزها (`/me/accounts`) | نعم — `meta_oauth.py:65` |
| `pages_read_engagement` | قراءة محتوى الصفحة وتفاعلها | نعم — `meta_oauth.py:65` |
| `pages_manage_metadata` | اشتراك الصفحة في التطبيق واستقبال الـ webhooks | نعم — `meta_oauth.py:65` |
| `pages_messaging` | قراءة وكتابة محادثات الصفحة (يمرّ منه مسار Instagram في هذا الوضع) | نعم — `meta_oauth.py:65` |
| `ads_management` + `ads_read` | تلزم إضافيًا لو كان للمستخدم دور على الصفحة عبر Business Manager | لا — غير مطلوب |

## 5. الفجوات المقاسة

1. **`instagram_manage_insights` غير مطلوب والكود ينادي الإحصاءات.** الواجهة تقرأ
   `GET /social/posts/{post_id}/insights` (`backend/app/modules/conversations/routers/social.py:195-205`)
   و`InstagramAdapter.get_media_insights` (`backend/app/modules/conversations/gateway/instagram.py:1067-1100`)
   ينادي `/{media_id}/insights`. وثائق Meta تشترط `instagram_manage_insights` لهذا النداء،
   فلا يوجد في `_INSTAGRAM_SCOPES` ولا في `INSTAGRAM_REQUIRED_SCOPES`. النتيجة على حساب حقيقي:
   رفض Meta عند أول فتح لتبويب الإحصاءات.
2. **`instagram_basic` مطلوب لكنه ليس في قائمة التحقق.** `INSTAGRAM_REQUIRED_SCOPES`
   (`meta_scopes.py:44-48`) تتحقق من ثلاث صلاحيات فقط، فلا تُنبّه المالك إذا رفض `instagram_basic`
   (وهو شرط كل قراءة بروفايل ووسائط).
3. **الوضع المطلوب ليس Unified Login.** الكود يطلب نطاقات Facebook Login (`pages_*` + `instagram_*`)
   وهي صحيحة لهذا الوضع، لكن Meta دفعت Unified Login بديلًا؛ لا حاجة لتغيير الآن لأن الوضع
   القديم ما زال مدعومًا، والانتقال يحتاج قرارًا منفصلًا.

## 6. الحدود التي تحكم ما يمكن أن تعرضه الواجهة

| الحد | القيمة | المصدر |
|---|---|---|
| نافذة المراسلة القياسية | 24 ساعة من آخر رسالة من العميل | messaging-api |
| نافذة إعلان Click-to-Direct | حتى 7 أيام من أول رسالة بعد الضغط | messaging-api |
| وسم Human Agent | نافذة منفصلة 7 أيام | messaging-api |
| طول النص | 1000 بايت UTF-8 كحد أقصى | messaging-api |
| مرفقات في رسالة واحدة | حتى 10 مرفقات (صور) | messaging-api |
| صورة | png/jpeg، 8MB | messaging-api |
| صوت | aac/m4a/wav/mp4، 25MB | messaging-api |
| فيديو | mp4/ogg/avi/mov/webm، 25MB | messaging-api |
| ملف | pdf، 25MB | messaging-api |
| رسائل جماعية | غير مدعومة — محادثة واحدة لكل عميل | messaging-api |
| مجلدات الصندوق (Primary/General/Requests) | غير مدعومة عبر الـ API | messaging-api |
| محادثات Requests الخاملة | لا تُعاد عبر الـ API بعد 30 يومًا | messaging-api |
| «تم القراءة» | الرسائل المسلَّمة عبر الـ API لا تُعتبر مقروءة في تطبيق Instagram إلا بعد رد | messaging-api |
| نشر عبر الـ API | 100 منشور في 24 ساعة متحركة (المستند يذكر 50 في موضع آخر — تعارض داخلي، **غير مُتحقَّق** أي الرقمين يُطبَّق) | content-publishing |
| عناصر الكاروسيل | حتى 20 صورة/فيديو | content-publishing |

## 7. حقول الـ Webhook وصلاحياتها

| الحقل | الصلاحية (Instagram Login / Unified) |
|---|---|
| `comments`, `live_comments` | `instagram_manage_comments` (+`instagram_basic`) |
| `mentions` | تأتي داخل إشعار `comments` |
| `messages`, `message_reactions`, `messaging_postbacks`, `messaging_referral`, `messaging_seen` | `instagram_manage_messages` (+`instagram_basic`) |
| `messaging_optins`, `messaging_handover`, `message_echoes` | `instagram_manage_messages` |
| `story_insights` | `instagram_manage_insights` |

مصدر: <https://developers.facebook.com/documentation/instagram-platform/webhooks/fields>

## 8. ما تدعمه الـ API من عناصر واجهة Instagram (لقرارات المطابقة)

مدعوم فعليًا عبر Send API: نص، رابط، صورة، صوت، فيديو، PDF، ستيكر القلب (`like_heart`)،
مشاركة منشور يملكه الحساب (`MEDIA_SHARE`)، **تفاعل بأي إيموجي** (`sender_action: react`
و`unreact`)، رد مقتبس على رسالة محددة (`reply_to.mid`)، قوالب (generic/button)، ردود سريعة،
قائمة ثابتة (persistent menu)، أسئلة Ice Breakers، مؤشر كتابة (`typing_on`/`typing_off`)،
و`mark_seen`. مصدر: <https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/messaging-api>

غير مدعوم عبر الـ API (يُوثَّق ولا يُنفَّذ): المجلدات، الستوريز كرسالة، الرسائل الجماعية،
سحب رسالة أُرسلت، تعديل نص رسالة أُرسلت، وحفظ المحادثة/الأرشفة.
