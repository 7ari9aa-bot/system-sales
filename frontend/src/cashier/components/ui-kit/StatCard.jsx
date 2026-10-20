import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import { cn } from "@/cashier/lib/utils";

const TONES = {
  primary: { ring: "ring-primary/15", bg: "bg-primary/10", text: "text-primary" },
  success: { ring: "ring-emerald-200/60", bg: "bg-emerald-50", text: "text-emerald-600" },
  warning: { ring: "ring-amber-200/60", bg: "bg-amber-50", text: "text-amber-600" },
  danger: { ring: "ring-rose-200/60", bg: "bg-rose-50", text: "text-rose-600" },
  info: { ring: "ring-sky-200/60", bg: "bg-sky-50", text: "text-sky-600" },
  violet: { ring: "ring-violet-200/60", bg: "bg-violet-50", text: "text-violet-600" },
};

// بطاقة مؤشر إحصائي واحدة: القيمة، العنوان، ملاحظة صغيرة، واتجاه التغير.
export default function StatCard({ label, value, hint, icon: Icon, tone = "primary", trend }) {
  const t = TONES[tone] ?? TONES.primary;
  const TrendIcon = trend?.direction === "down" ? ArrowDownRight : trend?.direction === "flat" ? Minus : ArrowUpRight;

  return (
    <div className="animate-fade-up rounded-xl border border-border bg-card p-3 card-soft transition-shadow hover:shadow-md">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-[11px] font-medium text-muted-foreground">{label}</p>
          <p className="num mt-1 break-words font-heading text-base font-bold leading-tight tracking-tight sm:text-lg">{value}</p>
          {hint && <p className="mt-0.5 truncate text-[10px] text-muted-foreground">{hint}</p>}
        </div>
        {Icon && (
          <span className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ring-1", t.bg, t.text, t.ring)}>
            <Icon className="h-4 w-4" aria-hidden="true" />
          </span>
        )}
      </div>
      {trend && (
        <div
          className={cn(
            "mt-2 inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-medium",
            trend.direction === "down" ? "bg-rose-50 text-rose-600" : trend.direction === "flat" ? "bg-muted text-muted-foreground" : "bg-emerald-50 text-emerald-600",
          )}
        >
          <TrendIcon className="h-3 w-3" aria-hidden="true" />
          <span className="num">{trend.value}</span>
          <span className="text-muted-foreground">{trend.label}</span>
        </div>
      )}
    </div>
  );
}