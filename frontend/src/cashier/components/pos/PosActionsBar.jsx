import { Ban, FilePlus2, PauseCircle, Printer, ReceiptText, StickyNote } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import { cn } from "@/cashier/lib/utils";
import FlipButtons from "@/cashier/components/pos/FlipButtons";

const SECONDARY = "h-9 gap-2 px-3.5 text-[13px]";

// الشريط السفلي: أزرار الفاتورة، وزرّا التقليب بين الفواتير.
export default function PosActionsBar({
  hasLines,
  hasLastReceipt,
  hasNote,
  payLabel = "طباعة",
  onPay,
  onSuspend,
  onCancel,
  onNew,
  onReprint,
  onNote,
  onPrev,
  onNext,
  prevDisabled,
  nextDisabled,
}) {
  return (
    <div className="flex flex-wrap items-center justify-center gap-2">
      <Button
        className="h-10 gap-2 bg-success px-5 text-[14px] font-bold text-success-foreground hover:bg-success/90"
        disabled={!hasLines}
        onClick={onPay}
      >
        <Printer className="h-4 w-4" />
        {payLabel}
        <span className="text-[11px] opacity-80">(F2)</span>
      </Button>

      <Button variant="outline" className={SECONDARY} onClick={onNote}>
        <StickyNote className="h-4 w-4" />
        ملاحظة
        {hasNote && <span className="h-1.5 w-1.5 rounded-full bg-primary" aria-label="توجد ملاحظة" />}
      </Button>

      {onSuspend ? (
        <Button variant="outline" className={SECONDARY} disabled={!hasLines} onClick={onSuspend}>
          <PauseCircle className="h-4 w-4" />
          تعليق الفاتورة
          <span className="text-[11px] opacity-70">(F4)</span>
        </Button>
      ) : null}

      <Button variant="outline" className={SECONDARY} onClick={onNew}>
        <FilePlus2 className="h-4 w-4" />
        فاتورة جديدة
      </Button>

      <Button variant="outline" className={SECONDARY} disabled={!hasLastReceipt} onClick={onReprint}>
        <ReceiptText className="h-4 w-4" />
        إعادة طباعة
      </Button>

      <Button
        variant="outline"
        className={cn(SECONDARY, "border-destructive/40 text-destructive hover:bg-destructive/10 hover:text-destructive")}
        disabled={!hasLines}
        onClick={onCancel}
      >
        <Ban className="h-4 w-4" />
        إلغاء الفاتورة
      </Button>

      {onPrev ? <FlipButtons onPrev={onPrev} onNext={onNext} prevDisabled={prevDisabled} nextDisabled={nextDisabled} /> : null}
    </div>
  );
}