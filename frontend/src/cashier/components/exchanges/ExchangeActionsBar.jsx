import { Ban, PauseCircle, Printer, StickyNote, BadgeCheck } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import { cn } from "@/cashier/lib/utils";

const SECONDARY = "h-9 gap-2 px-3.5 text-[13px]";

// الشريط السفلي: إتمام الاستبدال، طباعة الإيصال، ملاحظة، تعليق العملية، إلغاء العملية.
export default function ExchangeActionsBar({
  canComplete,
  canPrint,
  hasNote,
  hasDraft,
  onComplete,
  onPrint,
  onNote,
  onHold,
  onCancel,
}) {
  return (
    <div className="sticky bottom-0 z-20 flex flex-wrap items-center justify-center gap-2 rounded-lg border border-border bg-card/95 px-2 py-2 backdrop-blur">
      <Button
        className="h-9 gap-2 bg-success px-5 text-[13px] font-bold text-success-foreground hover:bg-success/90"
        disabled={!canComplete}
        onClick={onComplete}
      >
        <BadgeCheck className="h-4 w-4" />
        إتمام الاستبدال
        <span className="text-[11px] opacity-80">(F2)</span>
      </Button>

      <Button variant="outline" className={SECONDARY} disabled={!canPrint} onClick={onPrint}>
        <Printer className="h-4 w-4" />
        طباعة الإيصال
      </Button>

      <Button variant="outline" className={SECONDARY} onClick={onNote}>
        <StickyNote className="h-4 w-4" />
        ملاحظة
        {hasNote && <span className="h-1.5 w-1.5 rounded-full bg-primary" aria-label="توجد ملاحظة" />}
      </Button>

      <Button variant="outline" className={SECONDARY} disabled={!hasDraft} onClick={onHold}>
        <PauseCircle className="h-4 w-4" />
        تعليق العملية
        <span className="text-[11px] opacity-70">(F4)</span>
      </Button>

      <Button
        variant="outline"
        className={cn(SECONDARY, "border-destructive/40 text-destructive hover:bg-destructive/10 hover:text-destructive")}
        disabled={!hasDraft}
        onClick={onCancel}
      >
        <Ban className="h-4 w-4" />
        إلغاء العملية
      </Button>
    </div>
  );
}