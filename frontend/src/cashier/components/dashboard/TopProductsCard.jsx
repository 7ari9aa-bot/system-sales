import SectionCard from "@/cashier/components/ui-kit/SectionCard";
import { topProducts } from "@/cashier/lib/mockData";
import { fmtInt, fmtMoney } from "@/cashier/lib/format";

// المنتجات الأكثر مبيعًا مع نسبة مساهمة كل منتج.
export default function TopProductsCard() {
  const max = Math.max(...topProducts.map((p) => p.revenue));

  return (
    <SectionCard title="الأكثر مبيعًا" description="خلال آخر ٣٠ يومًا">
      <ul className="space-y-3">
        {topProducts.map((p, i) => (
          <li key={p.id}>
            <div className="flex items-center justify-between gap-2">
              <div className="flex min-w-0 items-center gap-2">
                <span className="num flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-muted text-[10px] font-bold text-muted-foreground">
                  {i + 1}
                </span>
                <span className="truncate text-sm font-medium">{p.name}</span>
              </div>
              <span className="num shrink-0 text-xs font-semibold">{fmtMoney(p.revenue)}</span>
            </div>
            <div className="mt-1.5 flex items-center gap-2 ps-7">
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
                <div className="h-full rounded-full bg-primary/70" style={{ width: `${(p.revenue / max) * 100}%` }} />
              </div>
              <span className="num shrink-0 text-[10px] text-muted-foreground">{fmtInt(p.qty)} قطعة</span>
            </div>
          </li>
        ))}
      </ul>
    </SectionCard>
  );
}