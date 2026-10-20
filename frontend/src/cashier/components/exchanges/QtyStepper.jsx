import { Minus, Plus } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import { cn } from "@/cashier/lib/utils";

const NO_SPINNER =
  "[appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none";
const QTY_BTN = "h-5 w-5 shrink-0 text-muted-foreground hover:bg-accent hover:text-primary";

// خانة كمية موحّدة: الكتابة المباشرة هي الأساس، وزرّا التقليل/الزيادة مساعدة سريعة.
export default function QtyStepper({ value, onChange, onStep, max, disabled, label }) {
  return (
    <div className="flex items-center justify-center gap-0.5">
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className={QTY_BTN}
        disabled={disabled}
        onClick={() => onStep(-1)}
        aria-label={`تقليل كمية ${label}`}
      >
        <Minus className="h-3 w-3" />
      </Button>
      <input
        type="number"
        min={1}
        max={max}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className={cn(
          "num h-6 w-8 rounded-md border border-input bg-background text-center text-[13px] font-bold outline-none focus:border-ring focus:ring-1 focus:ring-ring disabled:opacity-40",
          NO_SPINNER,
        )}
        aria-label={`كمية ${label}`}
      />
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className={QTY_BTN}
        disabled={disabled}
        onClick={() => onStep(1)}
        aria-label={`زيادة كمية ${label}`}
      >
        <Plus className="h-3 w-3" />
      </Button>
    </div>
  );
}