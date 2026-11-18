# Instagram (Messaging)

نفس تطبيق Meta — Webhooks → Instagram → تكوين.

## الـ Callback

```
https://fihrist.world/api/v1/webhooks/instagram
```

## رمز التحقق (متظبط على Northflank ✓)

```
INSTAGRAM_VERIFY_TOKEN = <VERIFY_TOKEN>  (القيمة على Northflank فقط)
```

## سر التوقيع (متظبط ✓)

| المتغير | الحالة | المصدر |
|---|---|---|
| `INSTAGRAM_APP_SECRET` | ✅ متظبط على Northflank (تحقق 2026-11-18: توقيع غلط بيرجع 403) | Meta → App Settings → Basic → App Secret |

## حسم المستأجر

`entry[0].id` = معرّف حساب الـ Instagram الاحترافي المرتبط بالصفحة — سجّله
كقناة instagram في الداشبورد. ملكية الحساب بتتأكد عبر Graph API قبل التفعيل
(`integration_verifier`) — مستأجر يقدر يسجل حساب مش بته يبقى مستحيل عملياً.

## الاختبار

رسالة DM لحسابك → الـ Inbox. ملاحظة: Instagram Messaging بيتطلب
`instagram_messaging` permission + حساب احترافي مربوط بالتطبيق.

## Seen و"بيكتب…" عند العميل

لما موظف يفتح محادثة إنستجرام يتبعت `mark_seen`، ولما يكتب رد يتبعت `typing_on` (مرة كل 20 ثانية).
المسار نفسه بتاع واتساب: `POST /conversations/{id}/read-signal`، وبيتحجب برا نافذة الرد.
الفشل مش بيوقف الموظف (`sent: false`).

## لما التوكن يموت (خطأ 190)

الرسالة بتفشل بجملة عربي واضحة، والقناة بتتحوّل لـ `reauth_required` فتظهر في لوحة الصحة كمحتاجة
إعادة ربط. توكن الصفحة المأخوذ من توكن مستخدم طويل المدى مبينتهيش، فمفيش تجديد تلقائي مطلوب.
