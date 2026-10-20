import { Ban, BadgeCheck } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import { cn } from "@/cashier/lib/utils";

// الشريط السفلي: إتمام الاستبدال وإلغاء المسودة. (الخادم لا يخزن ملاحظة أو تعليقًا للاستبدال.)
export default function ExchangeActionsBar({ canComplete, hasDraft, busy = false, label = "إتمام الاستبدال", onComplete, onCancel }) {
  return (
    <div className="sticky bottom-0 z-20 flex flex-wrap items-center justify-center gap-2 rounded-lg border border-border bg-card/95 px-2 py-2 backdrop-blur">
      <Button className="h-9 gap-2 bg-success px-5 text-[13px] font-bold text-success-foreground hover:bg-success/90" disabled={!canComplete || busy} onClick={onComplete}>
        <BadgeCheck className="h-4 w-4" />
        {busy ? "جارٍ التنفيذ…" : label}
        <span className="text-[11px] opacity-80">(F2)</span>
      </Button>
      <Button
        variant="outline"
        className={cn("h-9 gap-2 px-3.5 text-[13px]", "border-destructive/40 text-destructive hover:bg-destructive/10 hover:text-destructive")}
        disabled={!hasDraft || busy}
        onClick={onCancel}
      >
        <Ban className="h-4 w-4" />
        إلغاء العملية
      </Button>
    </div>
  );
}
