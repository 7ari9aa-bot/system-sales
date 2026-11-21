import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import SectionCard from "@/cashier/components/ui-kit/SectionCard";
import { cn } from "@/cashier/lib/utils";
import { GROUPS, groupQuery, receiptFromApi, summaryCards, trackingErrorMessage } from "@/cashier/api/receiptTracking";

// متابعة الإيصالات الإلكترونية: إيه اللي قبلته المصلحة، إيه اللي رفضته، وإيه اللي مهلته بتخلص.
// للقراءة فقط: تصحيح الإيصال المرفوض بيتم من النظام نفسه. المهلة (٩٦ ساعة، أو ٧٢ لمرتجع بدون إيصال
// أصلي) بيحسبها الخادم، والشاشة بس بتعرضها.

const TONE = {
  danger: "border-red-200 bg-red-50 text-red-700",
  ok: "border-emerald-200 bg-emerald-50 text-emerald-700",
  muted: "border-border bg-muted/40 text-muted-foreground",
};
const ROW_TONE = {
  expired: "border-red-300 bg-red-50",
  urgent: "border-orange-300 bg-orange-50",
  fix: "border-amber-200 bg-amber-50/60",
  retrying: "border-border bg-muted/30",
  ok: "border-border bg-card",
};

export function TrackingView({ summary, receipts, total, group, onGroup }) {
  const cards = summaryCards(summary);
  return (
    <div className="space-y-3" data-testid="receipt-tracking">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        {cards.map((c) => (
          <div key={c.key} className={cn("rounded-lg border p-2.5", TONE[c.tone])} data-card={c.key}>
            <div className="text-[11px]">{c.label}</div>
            <div className="mt-0.5 text-xl font-bold tabular-nums">{c.value}</div>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="تصفية الإيصالات">
        {GROUPS.map((g) => (
          <button
            key={g.value || "all"}
            type="button"
            role="tab"
            aria-selected={g.value === group}
            onClick={() => onGroup?.(g.value)}
            className={cn(
              "rounded-full border px-3 py-1 text-[12px]",
              g.value === group ? "border-primary bg-primary text-primary-foreground" : "border-border bg-card",
            )}
          >
            {g.label}
          </button>
        ))}
      </div>

      {receipts.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border p-6 text-center text-[13px] text-muted-foreground">
          مفيش إيصالات هنا. أول ما الكاشير يبيع والإيصال الإلكتروني يتفعّل، هتلاقيها هنا.
        </p>
      ) : (
        <ul className="space-y-1.5">
          {receipts.map((r) => (
            <li key={r.id} className={cn("rounded-lg border p-2.5", ROW_TONE[r.attention])} data-attention={r.attention}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-mono text-[12.5px] font-bold" dir="ltr">{r.number}</span>
                <span className="text-[12px]">{r.statusText}</span>
              </div>
              {r.attentionText && <p className="mt-1 text-[12px] font-medium">{r.attentionText}</p>}
              {r.deadlineText && (r.attention === "fix" || r.attention === "urgent") && (
                <p className="mt-0.5 text-[12px]">الوقت المتبقي للتصحيح: <b>{r.deadlineText}</b></p>
              )}
              {r.errors.length > 0 && (
                <ul className="mt-1 list-disc pe-4 text-[11.5px] text-muted-foreground">
                  {r.errors.map((e, i) => <li key={i} dir="auto">{e}</li>)}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
      {total > receipts.length && (
        <p className="text-center text-[11px] text-muted-foreground">بنعرض {receipts.length} من {total}. استخدم التصفية لتضييق القائمة.</p>
      )}
    </div>
  );
}

export default function ReceiptTracking() {
  const [group, setGroup] = useState("");
  const summary = useQuery({ queryKey: ["einvoice", "summary"], staleTime: 15_000, queryFn: () => api("/einvoice/receipts/summary") });
  const list = useQuery({
    queryKey: ["einvoice", "receipts", group],
    staleTime: 15_000,
    queryFn: () => api(`/einvoice/receipts${groupQuery({ group, limit: 100 })}`),
  });
  const error = summary.error || list.error;

  return (
    <SectionCard title="متابعة الإيصالات" description="اللي قبلته مصلحة الضرائب واللي رفضته واللي مهلته بتخلص. للقراءة فقط.">
      {error ? (
        <p className="rounded-lg border border-red-200 bg-red-50 p-3 text-[13px] text-red-700" role="alert">{trackingErrorMessage(error)}</p>
      ) : summary.isLoading || list.isLoading ? (
        <div className="flex items-center gap-2 p-4 text-[13px] text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> جاري التحميل…</div>
      ) : (
        <TrackingView
          summary={summary.data}
          receipts={(list.data?.items ?? []).map(receiptFromApi)}
          total={list.data?.total ?? 0}
          group={group}
          onGroup={setGroup}
        />
      )}
    </SectionCard>
  );
}
