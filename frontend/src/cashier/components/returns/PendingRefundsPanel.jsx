import { useState } from "react";
import { toast } from "sonner";
import { posApi } from "@/cashier/api/posApi";
import { fmtMoney } from "@/cashier/lib/format";

const METHOD_LABEL = { cash: "نقدي", card: "بطاقة", transfer: "تحويل", wallet: "محفظة" };

/**
 * رد البطاقة أو المحفظة بيحصل على ماكينة المحل، مش هنا.
 *
 * الخادم بيسجّل الجزء ده `pending` وبيقول للمتصفح إنه مستني تأكيد. الشاشة لازم تعرضه وتاخد رقم
 * المرجع من الماكينة، وإلا كان النظام بيدّعي إن الفلوس رجعت والعميل لسه مستنيها.
 */
export default function PendingRefundsPanel({ pending = [], sessionId, onConfirmed, onRejected }) {
  const [references, setReferences] = useState({});
  const [busyId, setBusyId] = useState(null);
  const [done, setDone] = useState({});
  const [rejectingId, setRejectingId] = useState(null);
  const [rejectReason, setRejectReason] = useState("");
  const [replacementMethod, setReplacementMethod] = useState("");

  if (!pending.length) return null;

  const reference = (row) => String(references[row.refund_id] ?? "").trim();
  const remaining = pending.filter((row) => !done[row.refund_id]);

  async function confirm(row) {
    const value = reference(row);
    if (!value) return toast.error("اكتب رقم مرجع الماكينة (RRN أو كود الموافقة) قبل التأكيد");
    setBusyId(row.refund_id);
    try {
      const res = await posApi.confirmRefund(row.refund_id, value);
      setDone((prev) => ({ ...prev, [row.refund_id]: res }));
      toast.success(
        `تم تأكيد رد ${fmtMoney(res.amount)} على ${METHOD_LABEL[res.method] ?? res.method} بالمرجع ${res.external_reference}`,
        { duration: 10000 },
      );
      onConfirmed?.(res);
    } catch (e) {
      toast.error(e?.message || "تعذّر تأكيد الرد، أعد المحاولة أو راجع الماكينة");
    } finally {
      setBusyId(null);
    }
  }

  /**
   * الماكينة رفضت العملية. لازم يتسجل السبب، وإلا المبلغ يفضل محجوز للأبد ومش ممكن يترد بطريقة تانية.
   * ولو الكاشير رد نقديًا بدلًا منها، بنسجّل رد جديد على النقدي — مش بنعدّل القديم.
   */
  async function reject(row) {
    const reason = rejectReason.trim();
    if (!reason) return toast.error("اكتب سبب رفض الماكينة قبل التسجيل");
    setBusyId(row.refund_id);
    try {
      if (replacementMethod === "cash" && !sessionId) {
        return toast.error("افتح الوردية أولاً ليُسجَّل الرد النقدي على الدرج");
      }
      const res = await posApi.rejectRefund(row.refund_id, {
        reason,
        replacement_method: replacementMethod || undefined,
        session_id: replacementMethod === "cash" ? sessionId : undefined,
      });
      setDone((prev) => ({ ...prev, [row.refund_id]: res }));
      toast.success(
        res?.replacement
          ? `اتسجل رفض العملية، واترد ${fmtMoney(res.replacement.amount)} على ${METHOD_LABEL[res.replacement.method] ?? res.replacement.method}`
          : "سُجّل رفض العملية، وتحرر المبلغ ولم يبق محجوزاً",
        { duration: 10000 },
      );
      setRejectingId(null);
      setRejectReason("");
      setReplacementMethod("");
      onRejected?.(res);
    } catch (e) {
      toast.error(e?.message || "تعذّر تسجيل رفض العملية");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div
      className="shrink-0 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2"
      data-testid="pending-refunds"
    >
      <p className="text-[12px] font-bold text-amber-900">
        رد مطلوب على الماكينة: اعكس المبلغ على جهاز الدفع واكتب رقم المرجع هنا
      </p>
      <ul className="mt-1 flex flex-col gap-1">
        {remaining.map((row) => (
          <li key={row.refund_id} className="flex flex-wrap items-center gap-2 text-[12px]">
            <span className="font-semibold text-foreground">
              {METHOD_LABEL[row.method] ?? row.method}: {fmtMoney(row.amount)}
            </span>
            {row.order_number ? (
              <span className="num text-[11px] text-muted-foreground">فاتورة {row.order_number}</span>
            ) : null}
            <input
              value={references[row.refund_id] ?? ""}
              onChange={(e) => setReferences((prev) => ({ ...prev, [row.refund_id]: e.target.value }))}
              placeholder="رقم المرجع (RRN)"
              aria-label={`رقم مرجع ${METHOD_LABEL[row.method] ?? row.method}`}
              className="h-7 w-40 rounded-md border border-border bg-background px-2 text-[12px]"
            />
            <button
              type="button"
              onClick={() => confirm(row)}
              disabled={!reference(row) || busyId === row.refund_id}
              className="h-7 rounded-md bg-[#E8761A] px-3 text-[12px] font-bold text-white disabled:opacity-50"
            >
              {busyId === row.refund_id ? "جارٍ التأكيد…" : "تأكيد الرد"}
            </button>
            <button
              type="button"
              onClick={() => setRejectingId(rejectingId === row.refund_id ? null : row.refund_id)}
              className="h-7 rounded-md border border-red-300 px-3 text-[12px] font-bold text-red-700"
            >
              الماكينة رفضت
            </button>
            {rejectingId === row.refund_id ? (
              <span className="flex flex-wrap items-center gap-2">
                <input
                  value={rejectReason}
                  onChange={(e) => setRejectReason(e.target.value)}
                  placeholder="سبب الرفض"
                  aria-label="سبب رفض الماكينة"
                  className="h-7 w-48 rounded-md border border-border bg-background px-2 text-[12px]"
                />
                <select
                  value={replacementMethod}
                  onChange={(e) => setReplacementMethod(e.target.value)}
                  aria-label="وسيلة بديلة"
                  className="h-7 rounded-md border border-border bg-background px-2 text-[12px]"
                >
                  <option value="">بدون رد بديل</option>
                  <option value="cash">رد نقدي من الدرج</option>
                </select>
                <button
                  type="button"
                  onClick={() => reject(row)}
                  disabled={busyId === row.refund_id}
                  className="h-7 rounded-md bg-red-600 px-3 text-[12px] font-bold text-white disabled:opacity-50"
                >
                  تسجيل الرفض
                </button>
              </span>
            ) : null}
          </li>
        ))}
      </ul>
      {remaining.length === 0 ? (
        <p className="text-[12px] font-semibold text-emerald-700">تم تأكيد كل الردود على الماكينة</p>
      ) : null}
    </div>
  );
}
