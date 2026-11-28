import { cn } from "@/applications/apparel/lib/utils";

// بطاقة قسم بعنوان وإجراء اختياري — الوحدة الأساسية لبناء الشاشات.
export default function SectionCard({ title, description, action, children, className, contentClassName, noPadding = false, flat = false }) {
  return (
    <section className={cn(flat ? "min-w-0" : "rounded-xl border border-border bg-card card-soft", className)}>
      {(title || action) && (
        <header className={cn("flex items-center justify-between gap-2 border-b border-border", flat ? "pb-2" : "px-3 py-2")}>
          <div className="min-w-0">
            {title && <h2 className="truncate font-heading text-[13px] font-bold">{title}</h2>}
            {description && <p className="mt-0.5 truncate text-[11px] text-muted-foreground">{description}</p>}
          </div>
          {action && <div className="flex shrink-0 items-center gap-1.5">{action}</div>}
        </header>
      )}
      <div className={cn(noPadding ? "" : flat ? "pt-2" : "p-3", contentClassName)}>{children}</div>
    </section>
  );
}