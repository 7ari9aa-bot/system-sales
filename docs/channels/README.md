# قنوات الرسائل — دليل التشغيل لكل قناة

كل قناة في ملف مستقل: الرابط، متغيرات البيئة، خطوات لوحة المزوّد، والاختبار.

| القناة | الـ Callback | الملف |
|---|---|---|
| WhatsApp | `/api/v1/webhooks/whatsapp` | [whatsapp.md](whatsapp.md) |
| Messenger (فيسبوك) | `/api/v1/webhooks/messenger` | [messenger.md](messenger.md) |
| Instagram | `/api/v1/webhooks/instagram` | [instagram.md](instagram.md) |
| Telegram | `/api/v1/webhooks/telegram` | [telegram.md](telegram.md) |
| Webchat | `/api/v1/webchat/{public_key}/messages` | [webchat.md](webchat.md) |

الدومين الإنتاجي: `https://api-production-81629.up.railway.app`

## الخط المشترك لكل الـ webhooks (conversations/router.py)

```
توقيع المزوّد (fail-closed بدون سر)
  → حارس الإعادة (digest الجسم + unique index)
  → حفظ الخام في webhook_events (صف مؤرشف بحدود tenant)
  → طابور المعالجة (§22)
  → ACK سريع للمزوّد
```

## القواعد العامة

- **fail-closed**: من غير السر المظبوط، كل الترافيك بيرفض — مفيش وضع مفتوح.
- **tenant مجهول**: ACK بدون أي تفاصيل (مفيش كشف وجود) — الحفظ بيحصل بس للمستأجرين المسجلين.
- **حسم المستأجر**: كل gateway بيطلع مفتاح (phone_number_id / page id / public_key) والدالة
  `resolve_channel_tenant` (SECURITY DEFINER) بترجع التينانت — المفاتيح المكررة بين مستأجرين
  بيتجاهل، وملكية الحساب بتتأكد عبر Graph API قبل التفعيل (`integration_verifier`).
- **ربط القناة بالتينانت**: من الداشبورد — Settings → Channels — بيسجل
  الـ external id (رقم الهاتف / Page ID / public_key) في `integrations`.
