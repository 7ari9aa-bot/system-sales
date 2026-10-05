# Webchat (الويجت)

## الـ Callback

```
POST https://api-production-81629.up.railway.app/api/v1/webchat/{public_key}/messages
```

`public_key` بييجي من إعدادات الويجت بتاعة التينانت (الداشبورد) — ده حسم
المستأجر، ومن غيره الطلب بيرفض قبل أي معالجة.

## الخصائص

- **مدخل عام بالتصميم** — من غير مصادقة، بس محدود:
  - الـ body size limit (middleware) + الـ rate limit (public tier 120/دقيقة).
  - رسالة الزائر بتفتح/تكمل محادثة webchat لعميل يتعمل تلقائياً.
- الرد بيرجع من نفس الـ AI pipeline (نفس عقود الرسائل).

## الاختبار

POST برسالة JSON على المسار بمفتاح صحيح → 201 ورد من الـ agent.
مفتاح غلط → رفض قبل أي معالجة.
