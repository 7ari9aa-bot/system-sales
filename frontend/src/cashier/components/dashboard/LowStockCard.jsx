import { Link } from "react-router-dom";
import { AlertTriangle } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import SectionCard from "@/cashier/components/ui-kit/SectionCard";
import StatusBadge from "@/cashier/components/ui-kit/StatusBadge";
import ColorSwatch from "@/cashier/components/ui-kit/ColorSwatch";
import { colorHex, lowStockAlerts, stockStatus } from "@/cashier/lib/mockData";

// تنبيهات النواقص على مستوى اللون والمقاس، لا الرصيد المجمع فقط.
export default function LowStockCard() {
  return (
    <SectionCard
      title="تنبيهات المخزون"
      description="أصناف وصلت إلى حد إعادة الطلب"
      action={
        <Button asChild variant="ghost" size="sm" className="h-7 text-xs text-primary hover:text-primary">
          <Link to="/cashier/inventory">فتح المخزون</Link>
        </Button>
      }
    >
      {lowStockAlerts.length === 0 ? (
        <p className="py-4 text-center text-[13px] text-muted-foreground">لا توجد نواقص حاليًا — المخزون بحالة جيدة.</p>
      ) : (
        <ul className="divide-y divide-border">
          {lowStockAlerts.map((v) => {
            const status = stockStatus(v.stock, v.threshold);
            return (
              <li key={v.id} className="flex items-center justify-between gap-3 py-2.5 first:pt-0 last:pb-0">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{v.productName}</p>
                  <p className="mt-0.5 flex items-center gap-2 text-[11px] text-muted-foreground">
                    <ColorSwatch color={v.color} hex={colorHex(v.color)} />
                    <span>مقاس {v.size}</span>
                    <span className="num">{v.sku}</span>
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <span className="num text-sm font-bold">{v.stock}</span>
                  <StatusBadge kind="inventory" value={status} />
                </div>
              </li>
            );
          })}
        </ul>
      )}
      <p className="mt-3 flex items-center gap-1.5 rounded-lg bg-amber-50 px-2.5 py-2 text-[11px] text-amber-800">
        <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        حد إعادة الطلب الحالي ٥ قطع لكل متغير، ويمكن تعديله من إعدادات المنتج.
      </p>
    </SectionCard>
  );
}