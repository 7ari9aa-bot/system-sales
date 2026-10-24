import { useEffect, useState } from "react";
import { History, ShoppingCart } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";

// رأس شاشة الكاشير: عنوان الشاشة ورقم الفاتورة، بيانات اليوم والكاشير والوردية، وأزرار الفواتير المعلقة والخروج.
export default function PosHeaderBar({
  invoiceNo,
  cashier,
  shiftOpenedAt,
  suspendedCount = 0,
  onRestore,
}) {
  const [now, setNow] = useState(() => new Date());

  // ساعة الشاشة تتحدّث كل دقيقة.
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 60000);
    return () => clearInterval(id);
  }, []);

  const dayLabel = now.toLocaleDateString("ar-EG-u-nu-latn", { weekday: "long", day: "2-digit", month: "2-digit", year: "numeric" });
  const timeLabel = now.toLocaleTimeString("ar-EG-u-nu-latn", { hour: "2-digit", minute: "2-digit" });

  return (
    <header className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <div className="min-w-0">
        <h2 className="font-heading flex items-center gap-2 text-xl font-extrabold leading-tight">
          <ShoppingCart className="h-[18px] w-[18px] text-primary" aria-hidden="true" />
          المبيعات
        </h2>
        <p className="num text-[11px] font-semibold text-muted-foreground">فاتورة رقم {invoiceNo}</p>
      </div>

      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted-foreground">
        <span className="num font-semibold text-foreground">
          {dayLabel} {timeLabel}
        </span>
        <span aria-hidden="true">|</span>
        <span className="font-semibold text-foreground" aria-label="الكاشير">
          {cashier || "—"}
        </span>
        <span aria-hidden="true">|</span>
        <span className="inline-flex items-center gap-1.5 font-semibold text-emerald-700">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" aria-hidden="true" />
          {shiftOpenedAt ? `اليوم مفتوح منذ ${new Date(shiftOpenedAt).toLocaleTimeString("ar-EG-u-nu-latn", { hour: "2-digit", minute: "2-digit" })}` : "اليوم مفتوح"}
        </span>
      </div>

      {onRestore ? (
        <div className="ms-auto flex items-center gap-2">
          <Button variant="outline" size="sm" className="h-8 gap-1.5 text-[12px]" onClick={onRestore}>
            <History className="h-3.5 w-3.5" />
            الفواتير المعلقة
            <span className="num rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] font-bold text-primary">{suspendedCount}</span>
          </Button>
        </div>
      ) : null}
    </header>
  );
}