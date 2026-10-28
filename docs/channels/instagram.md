# Instagram (Messaging)

نفس تطبيق Meta — Webhooks → Instagram → تكوين.

## الـ Callback

```
https://api-production-8f51.up.railway.app/api/v1/webhooks/instagram
```

## رمز التحقق (متظبط على Railway ✓)

```
INSTAGRAM_VERIFY_TOKEN = <VERIFY_TOKEN>  (القيمة على Railway فقط)
```

## سر التوقيع (ناقص — من Meta)

| المتغير | الحالة | المصدر |
|---|---|---|
| `INSTAGRAM_APP_SECRET` | ❌ غير متظبط | Meta → App Settings → Basic → App Secret |

## حسم المستأجر

`entry[0].id` = معرّف حساب الـ Instagram الاحترافي المرتبط بالصفحة — سجّله
كقناة instagram في الداشبورد. ملكية الحساب بتتأكد عبر Graph API قبل التفعيل
(`integration_verifier`) — مستأجر يقدر يسجل حساب مش بته يبقى مستحيل عملياً.

## الاختبار

رسالة DM لحسابك → الـ Inbox. ملاحظة: Instagram Messaging بيتطلب
`instagram_messaging` permission + حساب احترافي مربوط بالتطبيق.
