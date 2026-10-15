# القنوات — دليل الربط والتشغيل

الطبقة مقسّمة بحيث **كل قناة في ملفها**، والقناة الجديدة = ملف واحد + سطر في السجل.

## البنية (أين يعيش كل شيء)

| الطبقة | المكان | المسؤولية |
|---|---|---|
| مواصفات الربط (لكل قناة) | `backend/app/modules/platform/channel_specs/<channel>.py` | الحقول المطلوبة، التحقق الحي من المزوّد، مفتاح هوية القناة، شرح الويبهوك |
| سجل القنوات | `platform/channel_specs/registry.py` | `CONNECTION_SPECS` — المصدر الوحيد لشاشة الإعدادات |
| واجهة التحقق | `platform/integration_verifier.py` | واجهة رقيقة فوق السجل (تُبقي كل المستدعين الحاليين كما هم) |
| إرسال/استقبال الرسائل | `conversations/gateway/<channel>.py` | تحليل الويبهوك، الإرسال، التوقيع |
| سجل محولات الرسائل | `conversations/gateway/registry.py` | `ADAPTERS` — يُخدّم `/webhooks/{channel}` تلقائياً |
| سياسة الإرسال | `conversations/policy.py` | نافذة 24 ساعة + القوالب لكل قناة |

## القنوات المدعومة

| القناة | المفتاح | الحقول المطلوبة | هوية الربط | الويبهوك |
|---|---|---|---|---|
| واتساب | `whatsapp` | `access_token` + `phone_number_id` | `phone_number_id` | `/webhooks/whatsapp` |
| فيسبوك | `facebook` | `page_access_token` + `page_id` | `account_id` | `/webhooks/facebook` |
| ماسنجر | `messenger` | `api_key` (توكن الصفحة) | `account_id` | `/webhooks/messenger` |
| انستجرام | `instagram` | `api_key` + `account_id` | `account_id` | `/webhooks/instagram` |
| تيليجرام | `telegram` | `bot_token` | `bot_id` | يُسجَّل تلقائياً على الخادم |
| شات الموقع | `webchat` | — (يولّد مفتاحاً عاماً) | `public_key` | داخلي |

## مسار الربط

1. **ربط يدوي**: `POST /api/v1/integrations/connect` بالحقول أعلاه → يتحقق الخادم حياً من المزوّد → تُخزَّن الأسرار **مشفّرة** (`integrations.credentials`) ويُسجَّل التدقيق.
2. **ربط فيسبوك/ماسنجر/انستجرام عبر OAuth**: `GET /api/v1/integrations/meta/oauth/start?provider=…` ثم الكولباك — نفس التحقق ونفس التخزين.
3. **إعادة التحقق**: `POST /integrations/{id}/verify` · **الفصل**: `POST /integrations/{id}/disconnect` (يتطلب `confirm: true`).

## ملاحظات تشغيلية

- **التحقق يفشل مغلقاً**: أي توكن لا يطابق المعرّف (رقم واتساب / صفحة فيسبوك / حساب انستجرام) يُرفض قبل التخزين.
- **أعطال المزوّد ≠ توكن غلط**: 429/5xx تُعاد كخطأ مؤقت قابل لإعادة المحاولة، لا كرفض بيانات.
- **فيسبوك وماسنجر يتشاركان نفس بروتوكول Meta** (توكن الصفحة + توقيع `X-Hub-Signature-256` + `/me/messages`)، ومحول فيسبوك يعيد استخدام منطق ماسنجر حرفياً — الاختلاف فقط قيمة `provider` في الصف.
- **تيليجرام**: الويبهوك يُسجَّل من الخادم بسر محفوظ على الخادم فقط (لا يصل للمتصفح أبداً).
- `resolve_channel_tenant` دالة SQL **عمومية الهوية** (تطابق `account_id`/`bot_id`/`phone_number_id`/`public_key` لأي مزوّد) — لذلك إضافة قناة جديدة لا تحتاج أي migration.

## إضافة قناة جديدة (قائمة التحقق)

1. ملف جديد `platform/channel_specs/<name>.py` (اسم، وصف عربي، الحقول، `identity_field`، `verify()`، `setup_notes`).
2. سطر في `channel_specs/registry.py`.
3. محول رسائل في `conversations/gateway/<name>.py` + سطر في سجل المحولات.
4. سطر في `conversations/policy.py` (نافذة + قوالب).
5. أضف الاسم إلى `_WEBHOOK_CHANNELS` في `conversations/router.py` (وإلى `Literal` في `customers/schemas.py` — اختبار التطابق في `tests/test_channel_connections.py` هيمسكه لو نسيته).
