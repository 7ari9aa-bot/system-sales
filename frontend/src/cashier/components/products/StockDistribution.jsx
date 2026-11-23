import { fmtInt } from "@/cashier/lib/format";
import { allocationLabel, secondaryWarehouses } from "@/cashier/lib/stockDistribution";

// توزيع الرصيد الافتتاحي على أكتر من مخزن: المحل عنده فرع ومخزن، والموديل الجديد بيتقسم بينهم
// وقت الإدخال. الرقم اللي في جدول التركيبات إجمالي، واللي هنا بيحدد نصيب كل مخزن تاني.
export default function StockDistribution({ rows, warehouses = [], primaryId, onChangeAllocation, problem }) {
  const secondary = secondaryWarehouses(warehouses, primaryId);
  const withStock = rows.filter((r) => Number(r.stock) > 0);

  // محل عنده مخزن واحد: مفيش توزيع يتقال، والقسم كله ما ياخدش مساحة من الشاشة.
  if (secondary.length === 0 || withStock.length === 0) return null;

  return (
    <div className="rounded-xl border border-border bg-muted/20 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-semibold text-muted-foreground">توزيع الرصيد على مخازن تانية</span>
        <span className="text-[11px] text-muted-foreground">
          اللي مش هيتوزّع بيفضل في المخزن المختار فوق. التوزيع بياخد حركة مخزون لكل مخزن.
        </span>
      </div>

      <div className="mt-2 space-y-2">
        {withStock.map((row) => (
          <div key={row.id} className="rounded-lg border border-border bg-background p-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-[12px] font-semibold text-foreground">
                {row.color && row.size ? `${row.color} / ${row.size}` : row.sku}
                <span className="num ms-2 text-[11px] font-normal text-muted-foreground">{fmtInt(Number(row.stock))} قطعة</span>
              </span>
              <span className="text-[11px] text-muted-foreground">{allocationLabel(row, warehouses, primaryId)}</span>
            </div>
            <div className="mt-1 flex flex-wrap gap-2">
              {secondary.map((w) => (
                <label key={w.id} className="flex items-center gap-1 text-[11px] font-semibold text-muted-foreground">
                  <span>{w.name}</span>
                  <input
                    type="number"
                    min={0}
                    step="1"
                    aria-label={`${w.name} — ${row.color ?? ""} ${row.size ?? row.sku}`}
                    value={row.alloc?.[w.id] ?? ""}
                    onChange={(e) => onChangeAllocation(row.id, w.id, e.target.value)}
                    className="h-8 w-16 rounded-md border border-input bg-background px-2 text-center text-[12px] text-foreground"
                  />
                </label>
              ))}
            </div>
          </div>
        ))}
      </div>

      {problem && (
        <p role="alert" className="mt-2 rounded-lg border border-destructive/40 bg-destructive/10 px-2 py-1 text-[12px] font-semibold text-destructive">
          {problem}
        </p>
      )}
    </div>
  );
}
