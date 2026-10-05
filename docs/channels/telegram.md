# Telegram

## الـ Callback (setWebhook)

```
https://api-production-81629.up.railway.app/api/v1/webhooks/telegram?tenant_key=<مفتاح-التينانت>
```

التينانت بيتحدد من الـ query — والدالة `resolve_channel_tenant`
(SECURITY DEFINER) بترجع التينانت الصحيح وتتجاهل أي مفتاح مكرر بين مستأجرين.

## المتغيرات

| المتغير | الحالة | ملاحظة |
|---|---|---|
| `TELEGRAM_WEBHOOK_SECRET` | ❌ غير متظبط | نص عشوائي — **نفس القيمة** في `setWebhook` باراميتر `secret_token` |

التوقيع: هيدر `X-Telegram-Bot-Api-Secret-Token` بيتقارن constant-time —
من غير السر كل الترافيك بيرفض (fail-closed).

## خطوات الربط

1. BotFather → أنشئ البوت → خد الـ token.
2. الداشبورد: Settings → Channels → سجّل قناة telegram بالتوكن
   (التحقق: `getMe` + حسم التينانت عبر `resolve_channel_tenant`).
3. اضبط الـ webhook بالأمر (بعد ما تحط `TELEGRAM_WEBHOOK_SECRET` على Railway):
   ```
   curl "https://api.telegram.org/bot<TOKEN>/setWebhook" \
     -d "url=https://api-production-81629.up.railway.app/api/v1/webhooks/telegram?tenant_key=<KEY>" \
     -d "secret_token=<نفس قيمة المتغير>"
   ```

## الاختبار

رسالة للبوت → الـ Inbox. وملاحظة §176: البوت بيتحط مرة لكل هوية عامة —
التينانت بيتحسم من الدالة مش من التكرار.
