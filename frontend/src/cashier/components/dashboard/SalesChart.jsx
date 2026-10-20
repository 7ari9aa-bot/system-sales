import { useState } from "react";
import SectionCard from "@/cashier/components/ui-kit/SectionCard";
import { salesSeries } from "@/cashier/lib/mockData";
import { fmtMoney, fmtMoneyShort } from "@/cashier/lib/format";
import { cn } from "@/cashier/lib/utils";

const RANGES = [
  { key: "day", label: "آخر ٧ أيام" },
  { key: "week", label: "أسابيع" },
  { key: "month", label: "أشهر" },
];

// رسم بياني مبيعات حسب الفترة (مرسوم يدويًا ليظهر بالكامل من أول تحميل).
export default function SalesChart() {
  const [range, setRange] = useState("day");
  const data = salesSeries[range];
  const max = Math.max(...data.map((d) => d.value));
  const total = data.reduce((s, d) => s + d.value, 0);
  const best = data.reduce((a, b) => (b.value > a.value ? b : a), data[0]);

  return (
    <SectionCard
      title="حركة المبيعات"
      description={`إجمالي الفترة ${fmtMoney(total)} — أفضل فترة: ${best.label}`}
      action={
        <div className="flex rounded-lg bg-muted p-0.5">
          {RANGES.map((r) => (
            <button
              key={r.key}
              type="button"
              onClick={() => setRange(r.key)}
              className={cn(
                "rounded-md px-2.5 py-1 text-xs font-semibold transition-colors",
                range === r.key ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {r.label}
            </button>
          ))}
        </div>
      }
    >
      <div className="flex h-[230px] items-end gap-2 sm:gap-4">
        {data.map((d, i) => {
          const height = Math.max(8, Math.round((d.value / max) * 150));
          const isBest = d.value === max;
          return (
            <div key={`${d.label}-${i}`} className="group flex h-full flex-1 flex-col items-center justify-end gap-2">
              <span className="num text-[10px] font-semibold text-muted-foreground">{fmtMoneyShort(d.value)}</span>
              <div
                className={cn(
                  "w-full max-w-[46px] rounded-t-lg transition-all duration-300 group-hover:opacity-90",
                  isBest ? "bg-primary" : "bg-primary/35",
                )}
                style={{ height }}
                title={`${d.label}: ${fmtMoney(d.value)}`}
              />
              <span className="truncate text-[10px] text-muted-foreground">{d.label}</span>
            </div>
          );
        })}
      </div>
    </SectionCard>
  );
}