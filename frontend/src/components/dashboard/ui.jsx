import React from "react";
import { Link } from "react-router-dom";
import { ArrowRight, ArrowUpRight, ArrowDownRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { useI18n } from "@/lib/i18n";

/** هيكل عظمي بلمعان — مكان مؤشر التحميل: الشاشة بتترسم بشكلها النهائي
 *  فورًا والبيانات بتملا مكانها في أجزاء من الثانية. */
export function Skeleton({ className }) {
  return <div aria-hidden="true" className={cn("skeleton rounded-xl", className)} />;
}

export function KpiSkeleton() {
  return (
    <div className="rounded-2xl border border-border bg-card p-5">
      <div className="flex items-center justify-between">
        <Skeleton className="h-3.5 w-20" />
        <Skeleton className="h-7 w-7 rounded-lg" />
      </div>
      <Skeleton className="mt-3 h-6 w-28" />
      <Skeleton className="mt-3 h-3 w-16" />
    </div>
  );
}

export function Delta({ value, className }) {
  const positive = value >= 0;
  const Icon = positive ? ArrowUpRight : ArrowDownRight;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 text-[12px] font-semibold tabular-nums whitespace-nowrap",
        positive ? "text-success" : "text-destructive",
        className
      )}>
      
      <Icon className="h-3.5 w-3.5" />
      {positive ? "+" : ""}
      {value.toFixed(1)}%
    </span>);

}

export function SectionCard({ title, action, actionTo, children, className, bodyClassName }) {
  return (
    <section className={cn("rounded-2xl bg-card border border-border", className)}>
      {(title || action) &&
      <div className="flex items-center justify-between px-5 pt-4 pb-3">
          {title && <h2 className="font-display text-[15px] font-semibold whitespace-nowrap truncate">{title}</h2>}
          {action && actionTo &&
        <Link
          to={actionTo}
          className="inline-flex items-center gap-1 text-[12.5px] font-medium text-primary hover:gap-1.5 transition-all">
          
              {action}
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
        }
        </div>
      }
      <div className={cn("px-5 pb-5", bodyClassName)}>{children}</div>
    </section>);

}

export function KpiCard({ label, value, sub, delta, to, accent }) {
  return (
    <Link
      to={to}
      className="group relative rounded-2xl bg-card border border-border p-5 hover:border-primary/40 hover:shadow-sm transition-all">
      
      <div className="flex items-center justify-between">
        <span className="text-[12.5px] font-medium text-muted-foreground whitespace-nowrap truncate">{label}</span>
        {accent &&
        <span className={cn("h-7 w-7 rounded-lg grid place-items-center", accent.bg)}>
            {React.cloneElement(accent.icon, { className: cn("h-4 w-4", accent.color) })}
          </span>
        }
      </div>
      <div className="mt-2.5 min-w-0">
        <div className="font-display text-[24px] font-semibold leading-none tabular-nums tracking-tight whitespace-nowrap truncate">
          {value}
        </div>
        <div className="mt-2 h-4 flex items-center justify-between gap-2">
          <span className="text-[12px] text-muted-foreground whitespace-nowrap truncate">{sub}</span>
          {delta != null && <Delta value={delta} className="shrink-0" />}
        </div>
      </div>
    </Link>);

}

export function ProgressBar({ used, limit, tone = "primary" }) {
  const pct = Math.min(100, Math.round(used / limit * 100));
  const toneClass = {
    primary: "bg-primary",
    accent: "bg-accent",
    warning: "bg-warning",
    destructive: "bg-destructive"
  }[tone];
  return (
    <div className="h-2 w-full rounded-full bg-surface overflow-hidden">
      <div className={cn("h-full rounded-full transition-all", toneClass)} style={{ width: `${pct}%` }} />
    </div>);

}

export function StatusDot({ tone }) {
  const map = {
    primary: "bg-primary",
    accent: "bg-accent",
    warning: "bg-warning",
    destructive: "bg-destructive",
    success: "bg-success",
    muted: "bg-muted-foreground"
  };
  return <span className={cn("inline-block h-1.5 w-1.5 rounded-full", map[tone] || map.muted)} />;
}

export function Badge({ children, tone = "muted" }) {
  const map = {
    muted: "bg-surface text-muted-foreground",
    primary: "bg-primary/10 text-primary",
    accent: "bg-accent/10 text-accent",
    warning: "bg-warning/15 text-warning",
    destructive: "bg-destructive/10 text-destructive",
    success: "bg-success/15 text-success"
  };
  return (
    <span className={cn("inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11.5px] font-medium whitespace-nowrap", map[tone] || map.muted)}>
      {children}
    </span>
  );




}

export function PageHeader({ title, subtitle, actions }) {
  const { lang } = useI18n();
  return (
    <div className={cn("flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3 mb-6", lang === "ar" && "sm:flex-row-reverse")}>
      <div className={cn("min-w-0", lang === "ar" && "text-right")}>
        <h1 className="font-display text-[24px] font-semibold tracking-tight whitespace-nowrap truncate">{title}</h1>
        {subtitle && <p className="text-[13.5px] text-muted-foreground mt-1 line-clamp-2">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>);

}