import { useMemo, useState } from "react";
import { Banknote, CreditCard, Landmark, Loader2, Plus, Receipt as ReceiptIcon, Trash2, Wallet } from "lucide-react";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { money, subMoney, sumTenders } from "./money";
import Numpad from "./Numpad";

const METHODS = [
  { value: "cash", icon: Banknote },
  { value: "card", icon: CreditCard },
  { value: "wallet", icon: Wallet },
  { value: "bank_transfer", icon: Landmark },
];

/** شاشة الدفع — تقسيمة تندر زي ERPNext: بلاطة لكل وسيلة، الضغط عليها
 * بيملّي المبلغ الباقي تلقائياً، واللوحة الرقمية بتعدّل البلاطة المختارة.
 * الفلوس نصوص — الجمع والطرح على مونيز 2. */
export default function PaymentPanel({
  quote,
  methods,
  tenders,
  onTendersChange,
  onSell,
  busy,
  discountBlocked,
}) {
  const t = useT();

  const [selected, setSelected] = useState(0);

  const due = quote?.grand_total ?? "0.00";
  const paid = sumTenders(tenders);
  const diff = subMoney(paid, due); // موجب = فلوس زيادة للعميل

  const activeTender = tenders[selected] ?? null;

  const remainingForNew = useMemo(() => {
    const left = subMoney(due, paid);
    return Number(left) > 0 ? left : "0.00";
  }, [due, paid]);

  function addTender(method) {
    const next = [...tenders, { method, amount: remainingForNew }];
    onTendersChange(next);
    setSelected(next.length - 1);
  }

  function removeTender(index) {
    const next = tenders.filter((_, i) => i !== index);
    onTendersChange(next);
    setSelected((prev) => Math.max(0, Math.min(prev, next.length - 1)));
  }

  function setTenderAmount(index, value) {
    onTendersChange(
      tenders.map((t, i) => (i === index ? { ...t, amount: value } : t))
    );
  }

  function numpadDigit(d) {
    if (!activeTender) return;
    let current = String(activeTender.amount || "0");
    if (d === ".") {
      if (current.includes(".")) return;
      current = `${current}.`;
    } else {
      const [, frac] = current.split(".");
      if (frac !== undefined && frac.length >= 2) return;
      current = current === "0" ? d : current + d;
    }
    setTenderAmount(selected, current);
  }

  function numpadBackspace() {
    if (!activeTender) return;
    const current = String(activeTender.amount || "0");
    setTenderAmount(selected, current.length > 1 ? current.slice(0, -1) : "0");
  }

  const available = methods.length > 0 ? methods : ["cash", "card", "wallet", "bank_transfer"];
  const hasCash = tenders.some((t) => t.method === "cash");

  return (
    <div className="rounded-2xl bg-card border border-border p-4">
      <div className="text-[13px] font-medium mb-3">
        {t("pos.splitTender", "Split payment")}
      </div>

      {/* بلاطات الدفع المضافة */}
      <div className="space-y-1.5 mb-3">
        {tenders.length === 0 && (
          <p className="text-[12.5px] text-muted-foreground py-2">
            {t("pos.addTenderHint", "Pick a payment method to start.")}
          </p>
        )}
        {tenders.map((tender, i) => (
          <div
            key={`${tender.method}-${i}`}
            onClick={() => setSelected(i)}
            className={cn(
              "flex items-center gap-2 rounded-xl border px-3 py-2 cursor-pointer",
              i === selected ? "border-primary bg-primary/5" : "border-border"
            )}
          >
            <span className="text-[12.5px] flex-1">
              {t(`pos.method.${tender.method}`)}
            </span>
            <input
              value={tender.amount}
              onChange={(e) => setTenderAmount(i, e.target.value)}
              onFocus={() => setSelected(i)}
              dir="ltr"
              inputMode="decimal"
              className="h-8 w-24 rounded-lg border border-border bg-surface px-2 text-[13px] tabular-nums"
            />
            <button
              type="button"
              aria-label={t("pos.removeTender", "Remove")}
              onClick={(e) => {
                e.stopPropagation();
                removeTender(i);
              }}
              className="h-7 w-7 grid place-items-center rounded-lg text-destructive hover:bg-destructive/10"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
      </div>

      {/* وسايل متاحة للإضافة */}
      <div className="grid grid-cols-2 gap-1.5 mb-3">
        {available.map((m) => {
          const Icon = METHODS.find((x) => x.value === m)?.icon ?? ReceiptIcon;
          return (
            <button
              key={m}
              type="button"
              onClick={() => addTender(m)}
              className="h-10 rounded-xl border border-border text-[12.5px] inline-flex items-center justify-center gap-1.5 hover:bg-surface"
            >
              <Icon className="h-4 w-4" />
              {t(`pos.method.${m}`)}
              <Plus className="h-3 w-3" />
            </button>
          );
        })}
      </div>

      {/* الحالة: الباقي أو فكة العميل */}
      <dl className="space-y-1.5 mb-3 text-[13px]" dir="ltr">
        <div className="flex items-center justify-between">
          <dt className="text-muted-foreground">{t("pos.paidSoFar", "Paid")}</dt>
          <dd className="tabular-nums">{money(paid)}</dd>
        </div>
        {Number(diff) >= 0 ? (
          <div className="flex items-center justify-between text-success">
            <dt className="text-muted-foreground">{t("pos.change", "Change due")}</dt>
            <dd className="tabular-nums">{money(diff)}</dd>
          </div>
        ) : (
          <div className="flex items-center justify-between text-destructive">
            <dt className="text-muted-foreground">{t("pos.remaining", "Remaining")}</dt>
            <dd className="tabular-nums">{money(diff.replace("-", ""))}</dd>
          </div>
        )}
      </dl>

      {/* لوحة الأرقام للبلاطة المختارة */}
      {(
        <div className="mb-3">
          <div className="text-[11.5px] text-muted-foreground mb-1.5">
            {activeTender
              ? t("pos.padEditing", "Editing: {m}", {
                  m: t(`pos.method.${activeTender.method}`),
                })
              : t("pos.padPick", "Pick a tender tile to type its amount.")}
          </div>
          <Numpad
            disabled={!activeTender || busy}
            onDigit={numpadDigit}
            onBackspace={numpadBackspace}
            onClear={() => activeTender && setTenderAmount(selected, "0")}
          />
        </div>
      )}

      <button
        type="button"
        onClick={onSell}
        disabled={busy || discountBlocked || !quote || tenders.length === 0 || Number(paid) + 0.005 < Number(due)}
        className="h-12 w-full rounded-xl bg-primary text-primary-foreground text-[14px] font-semibold disabled:opacity-50 inline-flex items-center justify-center gap-2"
      >
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <ReceiptIcon className="h-4 w-4" />}
        {t("pos.charge", "Charge {a}", { a: money(due) })}
      </button>
      {!hasCash && tenders.length > 0 && (
        <p className="mt-2 text-[11.5px] text-muted-foreground text-center">
          {t("pos.noCashHint", "No cash tender — no change will be computed.")}
        </p>
      )}
    </div>
  );
}
