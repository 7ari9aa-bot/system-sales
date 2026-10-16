import { useEffect, useState } from "react";
import { Loader2, Mail, Printer } from "lucide-react";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { money, mul } from "./money";

/** الإيصال الحراري — payload كامل من /pos/receipts/{id} وطباعة بـ window.print.
 *
 * الطباعة: الـ style بلوك بيخفي كل حاجة في الصفحة ما عدا .pos-receipt-print،
 * وعرض الإيصال 80mm — نفس منطق قوالب ERPNext الحرارية. والإيميل بيتجهز على
 * الخادم (outbox) ويبعته الـ worker — طلب الإيميل مابيبعتش حاجة بنفسه. */
export default function ReceiptView({ receiptId, onNotice }) {
  const t = useT();
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);
  const [emailError, setEmailError] = useState(null);
  const [email, setEmail] = useState("");
  const [emailBusy, setEmailBusy] = useState(false);
  const [emailSent, setEmailSent] = useState(false);

  useEffect(() => {
    let alive = true;
    setDetail(null);
    setError(null);
    setEmailSent(false);
    (async () => {
      try {
        const data = await api(`/pos/receipts/${receiptId}`);
        if (alive) setDetail(data);
      } catch (e) {
        if (alive) setError(e?.message || t("pos.err.receipt", "Could not load that receipt."));
      }
    })();
    return () => {
      alive = false;
    };
  }, [receiptId, t]);

  async function sendEmail() {
    const target = email.trim();
    if (!target || emailBusy) return;
    setEmailBusy(true);
    setEmailError(null);
    try {
      await api(`/pos/receipts/${receiptId}/email`, {
        method: "POST",
        body: { email: target },
      });
      setEmailSent(true);
      onNotice?.(t("pos.emailQueued", "Receipt queued to {e}.", { e: target }));
    } catch (e) {
      setEmailError(e?.message || t("pos.err.email", "Could not queue the email."));
    } finally {
      setEmailBusy(false);
    }
  }

  if (error) return <p className="text-[12.5px] text-destructive">{error}</p>;
  if (!detail) return null;

  const { receipt, order, lines, tenders } = detail;
  const isReturn = receipt.kind === "return";

  return (
    <div>
      <style>{`
        @media print {
          body * { visibility: hidden; }
          .pos-receipt-print, .pos-receipt-print * { visibility: visible; }
          .pos-receipt-print {
            position: absolute; inset-inline-start: 0; top: 0;
            width: 80mm; color: #000; background: #fff;
          }
        }
      `}</style>

      <div className="pos-receipt-print mx-auto w-full max-w-[320px] rounded-xl border border-border bg-surface p-4 text-[12px]">
        <div className="text-center font-display text-[14px] font-semibold mb-1">
          {isReturn ? t("pos.kind.return", "Return") : t("pos.receipt", "Receipt")}
        </div>
        <div className="text-center text-[11px] text-muted-foreground tabular-nums mb-3" dir="ltr">
          {receipt.number}
        </div>
        <table className="w-full text-[11.5px] mb-2">
          <thead>
            <tr className="text-muted-foreground">
              <th className="text-start font-medium">{t("pos.lines", "Items")}</th>
              <th className="text-end font-medium">{t("pos.total", "Total")}</th>
            </tr>
          </thead>
          <tbody>
            {(lines || []).map((l) => (
              <tr key={l.variant_id}>
                <td className="py-0.5" dir="auto">
                  {l.title || l.sku} ×{l.quantity}
                  <span className="block text-[10px] text-muted-foreground tabular-nums" dir="ltr">
                    {money(l.unit_price)} = {mul(l.unit_price, l.quantity)}
                  </span>
                </td>
                <td className="py-0.5 text-end tabular-nums" dir="ltr">
                  {money(l.total)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="border-t border-border pt-2 space-y-1 text-[11.5px]">
          {order.discount_total && order.discount_total !== "0.00" && (
            <div className="flex justify-between">
              <span>{t("pos.discountLabel", "Discount")}</span>
              <span className="tabular-nums" dir="ltr">{money(order.discount_total)}</span>
            </div>
          )}
          <div className="flex justify-between font-semibold">
            <span>{t("pos.grandTotal", "Total due")}</span>
            <span className="tabular-nums" dir="ltr">{money(order.grand_total)}</span>
          </div>
          {(tenders || []).map((tender, i) => (
            <div key={i} className="flex justify-between text-muted-foreground">
              <span>{t(`pos.method.${tender.method}`)}</span>
              <span className="tabular-nums" dir="ltr">{money(tender.amount)}</span>
            </div>
          ))}
          {receipt.tendered_amount != null && (
            <div className="flex justify-between">
              <span>{t("pos.cashGiven", "Cash received")}</span>
              <span className="tabular-nums" dir="ltr">{money(receipt.tendered_amount)}</span>
            </div>
          )}
          {receipt.change_amount != null && (
            <div className="flex justify-between font-semibold">
              <span>{t("pos.change", "Change due")}</span>
              <span className="tabular-nums" dir="ltr">{money(receipt.change_amount)}</span>
            </div>
          )}
        </div>
        <div className="mt-2 text-[10px] text-muted-foreground tabular-nums" dir="ltr">
          {t("pos.orderNo", "Order {n}", { n: order.number })}
        </div>
      </div>

      <div className="mt-2 flex items-center gap-1.5">
        <button
          type="button"
          onClick={() => window.print()}
          className="h-9 px-4 rounded-xl border border-border text-[12.5px] font-medium inline-flex items-center gap-1.5"
        >
          <Printer className="h-4 w-4" />
          {t("pos.print", "Print")}
        </button>
        {!emailSent ? (
          <>
            <input
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder={t("pos.emailPlaceholder", "Email address")}
              dir="ltr"
              type="email"
              className="h-9 flex-1 rounded-xl border border-border bg-surface px-3 text-[12px]"
            />
            <button
              type="button"
              onClick={() => void sendEmail()}
              disabled={emailBusy || !email.trim()}
              className="h-9 px-3 rounded-xl border border-border text-[12.5px] font-medium disabled:opacity-50 inline-flex items-center gap-1.5"
            >
              {emailBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Mail className="h-4 w-4" />}
              {t("pos.emailSend", "Send")}
            </button>
          </>
        ) : (
          <span className="text-[12px] text-success inline-flex items-center gap-1.5">
            <Mail className="h-4 w-4" />
            {t("pos.emailSent", "Queued — arriving shortly.")}
          </span>
        )}
      </div>
      {emailError && (
        <p className="mt-1.5 text-[12px] text-destructive">{emailError}</p>
      )}
    </div>
  );
}
