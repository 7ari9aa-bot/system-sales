import { cn } from "@/cashier/lib/utils";

// مربع لون صغير يوضّح لون القطعة داخل الجداول.
export default function ColorSwatch({ color, hex, className, showLabel = true }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 whitespace-nowrap", className)}>
      <span
        className="h-3.5 w-3.5 shrink-0 rounded-full ring-1 ring-black/10"
        style={{ backgroundColor: hex ?? "#A1A1AA" }}
        aria-hidden="true"
      />
      {showLabel && <span className="text-xs text-muted-foreground">{color}</span>}
    </span>
  );
}