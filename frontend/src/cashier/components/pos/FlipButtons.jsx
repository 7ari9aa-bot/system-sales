import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/cashier/lib/utils";

// زر تقليب: خلفية شفافة تتحول للون التمييز عند المرور عليه.
const STEP_BTN =
  "flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground transition-all duration-150 hover:bg-card hover:text-primary hover:shadow-sm active:scale-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-40";

// زرّا التقليب بين الفواتير: «السابق» يفتح فاتورة أقدم، و«التالي» يرجع للأحدث.
export default function FlipButtons({ onPrev, onNext, prevDisabled, nextDisabled, className }) {
  return (
    <div className={cn("flex items-center rounded-xl border border-border bg-muted/70 p-0.5 shadow-sm", className)}>
      <button
        type="button"
        className={STEP_BTN}
        disabled={prevDisabled}
        onClick={onPrev}
        title="الفاتورة السابقة"
        aria-label="الفاتورة السابقة"
      >
        <ChevronRight className="h-[18px] w-[18px] stroke-[2.5]" />
      </button>
      <span className="h-5 w-px bg-border" aria-hidden="true" />
      <button
        type="button"
        className={STEP_BTN}
        disabled={nextDisabled}
        onClick={onNext}
        title="الفاتورة التالية"
        aria-label="الفاتورة التالية"
      >
        <ChevronLeft className="h-[18px] w-[18px] stroke-[2.5]" />
      </button>
    </div>
  );
}