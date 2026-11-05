import React from "react";
import { Clock, RefreshCw, Wallet } from "lucide-react";
import { Badge, SectionCard } from "@/components/dashboard/ui";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

/** The pending-purchase state: what was ordered, how to pay, and the
 *  payment-reference bookkeeping — the merchant records their transfer
 *  reference so the platform admin can match it when confirming. */

function formatPrice(value, currency, isAr) {
  const amount = Number(value ?? 0).toLocaleString(isAr ? "ar-EG" : "en-EG", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return isAr ? `${amount} ${currency === "EGP" ? "ج.م" : currency}` : `${currency} ${amount}`;
}

export default function PendingPurchase({ overview, onMutate }) {
  const { lang } = useI18n();
  const isAr = lang === "ar";
  const L = (ar, en) => (isAr ? ar : en);
  const purchase = overview?.pending_purchase;
  const instructions = overview?.payment_instructions;

  const [reference, setReference] = React.useState(purchase?.payment_reference ?? "");
  const [busy, setBusy] = React.useState("");
  const [message, setMessage] = React.useState(null);

  if (!purchase) return null;

  const saveReference = async () => {
    setBusy("ref");
    setMessage(null);
    try {
      await api("/website/purchase/payment-reference", {
        method: "POST",
        body: JSON.stringify({ reference }),
      });
      setMessage({ kind: "ok", text: L("تم حفظ رقم العملية", "Payment reference saved") });
      onMutate();
    } catch (err) {
      setMessage({ kind: "err", text: err?.message || L("تعذر الحفظ", "Could not save") });
    } finally {
      setBusy("");
    }
  };

  const cancel = async () => {
    setBusy("cancel");
    setMessage(null);
    try {
      await api("/website/purchase/cancel", { method: "POST" });
      onMutate();
    } catch (err) {
      setMessage({ kind: "err", text: err?.message || L("تعذر الإلغاء", "Could not cancel") });
    } finally {
      setBusy("");
    }
  };

  return (
    <SectionCard
      title={L("طلب الموقع قيد المراجعة", "Website purchase pending")}
      action={
        <Badge tone="warning">
          {L("بانتظار الدفع", "Awaiting payment")}
        </Badge>
      }
    >
      <div className="grid gap-4 sm:grid-cols-3">
        <div className="flex items-center gap-3">
          <Clock className="h-5 w-5 text-muted-foreground" />
          <div>
            <div className="text-sm font-medium">{purchase.site_name}</div>
            <div className="text-xs text-muted-foreground" dir="ltr">
              /{purchase.slug}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Wallet className="h-5 w-5 text-muted-foreground" />
          <div>
            <div className="text-sm font-medium">{formatPrice(purchase.price, purchase.currency, isAr)}</div>
            <div className="text-xs text-muted-foreground">{L("المبلغ المطلوب", "Amount due")}</div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <RefreshCw className="h-5 w-5 text-muted-foreground" />
          <div>
            <div className="text-sm font-medium">{purchase.template_id}</div>
            <div className="text-xs text-muted-foreground">{L("التصميم المختار", "Chosen design")}</div>
          </div>
        </div>
      </div>

      <div className="mt-4 rounded-lg border bg-muted/30 p-4">
        <div className="text-sm font-semibold">{L("تعليمات الدفع", "Payment instructions")}</div>
        <p className="mt-1 whitespace-pre-line text-sm text-muted-foreground">
          {instructions ||
            L(
              "حوّل المبلغ على حساب الشركة، وبعدين اكتب رقم عملية التحويل في الخانة تحت. فريقنا بيراجع المدفوعات ويوافق على الطلب، وساعتها موقعك بيتبني ويتنشر تلقائيًا.",
              "Transfer the amount to the company account, then record the transfer reference below. Our team reviews payments and confirms the order — your website is then built and published automatically.",
            )}
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <input
            value={reference}
            onChange={(e) => setReference(e.target.value)}
            placeholder={L("رقم عملية التحويل", "Transfer reference")}
            maxLength={200}
            className="w-full max-w-xs rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-primary/30"
          />
          <button
            type="button"
            onClick={saveReference}
            disabled={!reference.trim() || busy === "ref"}
            className="rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {busy === "ref" ? L("جارٍ الحفظ…", "Saving…") : L("حفظ رقم العملية", "Save reference")}
          </button>
          <button
            type="button"
            onClick={cancel}
            disabled={busy === "cancel"}
            className="rounded-md border px-3 py-2 text-sm font-medium hover:bg-accent disabled:opacity-50"
          >
            {busy === "cancel" ? L("جارٍ الإلغاء…", "Cancelling…") : L("إلغاء الطلب", "Cancel order")}
          </button>
        </div>
        {message ? (
          <div className={`mt-2 text-sm ${message.kind === "ok" ? "text-emerald-700" : "text-red-600"}`}>
            {message.text}
          </div>
        ) : null}
      </div>
    </SectionCard>
  );
}
