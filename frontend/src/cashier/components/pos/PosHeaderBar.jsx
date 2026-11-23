import { useEffect, useState } from "react";
import { Banknote, History, LayoutGrid, Printer, ShoppingCart, Users, Wifi, WifiOff } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";

export default function PosHeaderBar({
  invoiceNo,
  cashier,
  shiftOpenedAt,
  suspendedCount = 0,
  onRestore,
  onCashMovement,
  onHandover,
  onPrinterSetup,
  onPickVariant,
  isOnline = true,
  offlineCount = 0,
  onSyncOffline,
}) {
  const [now, setNow] = useState(() => new Date());

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
        <span className="inline-flex items-center gap-1.5 font-semibold text-emerald-700 dark:text-emerald-400">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" aria-hidden="true" />
          {shiftOpenedAt ? `اليوم مفتوح منذ ${new Date(shiftOpenedAt).toLocaleTimeString("ar-EG-u-nu-latn", { hour: "2-digit", minute: "2-digit" })}` : "اليوم مفتوح"}
        </span>

        {!isOnline ? (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-100 dark:bg-amber-950/40 text-amber-800 dark:text-amber-300 font-bold text-[10px]">
            <WifiOff className="h-3 w-3" />
            دون اتصال
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 text-[10px] text-slate-500">
            <Wifi className="h-3 w-3 text-emerald-600" />
            متصل
          </span>
        )}

        {offlineCount > 0 ? (
          <button
            type="button"
            onClick={onSyncOffline}
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-blue-100 dark:bg-blue-950/40 text-blue-800 dark:text-blue-300 font-bold text-[10px] hover:underline cursor-pointer"
          >
            معلق للمزامنة: {offlineCount}
          </button>
        ) : null}
      </div>

      <div className="ms-auto flex flex-wrap items-center gap-1.5">
        {onPickVariant ? (
          <Button
            variant="outline"
            size="sm"
            className="h-8 gap-1.5 text-[11px]"
            onClick={onPickVariant}
            title="اختيار الصنف من الكتالوج لما الباركود أو التيكيت يكون تالف"
          >
            <LayoutGrid className="h-3.5 w-3.5 text-primary" />
            اختيار صنف
          </Button>
        ) : null}

        {onCashMovement ? (
          <Button
            variant="outline"
            size="sm"
            className="h-8 gap-1.5 text-[11px]"
            onClick={onCashMovement}
            title="حركة نقدية بالدرج (إيداع / صرف / توريد خزنة)"
          >
            <Banknote className="h-3.5 w-3.5 text-emerald-600" />
            حركة درج
          </Button>
        ) : null}

        {onHandover ? (
          <Button
            variant="outline"
            size="sm"
            className="h-8 gap-1.5 text-[11px]"
            onClick={onHandover}
            title="تسليم الدرج والوردية المفتوحة لكاشير آخر، من غير إغلاق اليوم"
          >
            <Users className="h-3.5 w-3.5 text-blue-600" />
            تسليم لكاشير آخر
          </Button>
        ) : null}

        {onPrinterSetup ? (
          <Button
            variant="outline"
            size="sm"
            className="h-8 gap-1.5 text-[11px]"
            onClick={onPrinterSetup}
            title="إعداد الطابعة الحرارية ودرج النقدية"
          >
            <Printer className="h-3.5 w-3.5 text-slate-600 dark:text-slate-300" />
            الطابعة
          </Button>
        ) : null}

        {onRestore ? (
          <Button variant="outline" size="sm" className="h-8 gap-1.5 text-[12px]" onClick={onRestore}>
            <History className="h-3.5 w-3.5" />
            الفواتير المعلقة
            <span className="num rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] font-bold text-primary">{suspendedCount}</span>
          </Button>
        ) : null}
      </div>
    </header>
  );
}
