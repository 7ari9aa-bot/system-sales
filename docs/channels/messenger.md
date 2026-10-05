# Messenger — فيسبوك (Messenger API)

صفحة Meta: Messenger API → Webhooks → تكوين.

## الـ Callback

```
https://api-production-81629.up.railway.app/api/v1/webhooks/messenger
```

## رمز التحقق (متظبط على Railway ✓)

```
MESSENGER_VERIFY_TOKEN = y49NirBEhqcZw73wCUxmcU9GPBXu6ttK
```
الصق **نفس القيمة** في خانة "تحقق من الرمز" — الـ GET handshake بيرجع `hub.challenge` عند التطابق.

## سر التوقيع (ناقص — من Meta)

| المتغير | الحالة | المصدر |
|---|---|---|
| `MESSENGER_APP_SECRET` | ❌ غير متظبط | Meta → App Settings → Basic → App Secret |

من غيره كل الـ webhooks بترجع 403 (التوقيع X-Hub-Signature-256 fail-closed).
الإصلاح النهاري (tوقيع القنوات) اتأكد باختبارات لكل قناة: توقيع صحيح = قبول،
لمسة واحدة على الجسم = رفض، سر غلط = رفض.

## الاشتراكات

فعّل: `messages` + `messaging_postbacks` + `messaging_referrals` + `message_deliveries`.

## حسم المستأجر والربط

- كل حدث بيحمل Page ID في `entry[0].id` — ده اللي بيتطابق مع قناة messenger
  مسجلة في الداشبورد للتينانت.
- **رمز الوصول (الخطوة 2 في Meta)** — توكن صفحة Fihrist بيتحط في إعدادات
  القناة جوه الداشبورد (رصيد الإرسال)، مش في متغيرات البيئة.

## الاختبار

- رسالة من ماسنجر للصفحة → تظهر في الـ Inbox وتفتح محادثة.
- نفس الرسالة تاني بعد ثانية → حارس الإعادة (digest) بيمسكها.
