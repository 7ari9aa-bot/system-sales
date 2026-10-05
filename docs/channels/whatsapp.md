# WhatsApp (Cloud API)

## الـ Callback

```
https://api-production-81629.up.railway.app/api/v1/webhooks/whatsapp
```

## متغيرات البيئة (Railway — خدمة api)

| المتغير | الحالة | ملاحظة |
|---|---|---|
| `WHATSAPP_VERIFY_TOKEN` | ❌ غير متظبط | أي نص عشوائي — **نفس القيمة** في Meta (WhatsApp → Configuration → Verify token) |
| `WHATSAPP_APP_SECRET` | ❌ غير متظبط | من Meta App Settings → Basic → App Secret |

من غير الاتنين: الـ handshake والـ signature بيرفضوا كل شيء (fail-closed).

## خطوات الربط

1. Meta for Developers → تطبيقك → WhatsApp → Configuration.
2. حط الـ Callback URL أعلاه + نفس `WHATSAPP_VERIFY_TOKEN` في خانة Verify token.
3. Meta بتبعت GET handshake → السيرفر بيرجع `hub.challenge` لو الرمز مطابق.
4. ظبط `WHATSAPP_APP_SECRET` على Railway (القيمة من Meta) — التوقيع X-Hub-Signature-256
   بيتقارن بمحتوى الجسم الخام بعد شيل البادئة `sha256=`.
5. في الداشبورد: Settings → Channels → سجّل قناة whatsapp بالـ phone_number_id
   بتاع الرقم (بييجي من `metadata.phone_number_id` في كل حدث) — ده حسم المستأجر.

## الاختبار

- أرسل رسالة واتساب للرقم المسجل → لازم تظهر في الـ Inbox.
- عدّل بايت واحد في الجسم (replay بلمسة) → 403 invalid signature.
