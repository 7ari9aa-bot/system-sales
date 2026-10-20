import { cn } from "@/cashier/lib/utils";

// حالة "لا توجد بيانات" مع توضيح الإجراء التالي.
export default function EmptyState({ icon: Icon, title, description, action, className, compact = false }) {
  return (
    <div className={cn("flex flex-col items-center justify-center text-center", compact ? "px-4 py-6" : "px-6 py-10", className)}>
      {Icon && (
        <span className="mb-2 flex h-10 w-10 items-center justify-center rounded-full bg-muted text-muted-foreground">
          <Icon className="h-4 w-4" aria-hidden="true" />
        </span>
      )}
      <p className="font-heading text-[13px] font-semibold">{title}</p>
      {description && <p className="mt-1 max-w-sm text-[11px] leading-relaxed text-muted-foreground">{description}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}