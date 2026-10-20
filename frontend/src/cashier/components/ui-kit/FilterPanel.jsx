import { ChevronDown } from "lucide-react";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/cashier/components/ui/collapsible";
import { Button } from "@/cashier/components/ui/button";
import { cn } from "@/cashier/lib/utils";

// لوحة فلاتر قابلة للفتح والإخفاء، تُستخدم أعلى كل الجداول.
export default function FilterPanel({ children, activeCount = 0, onReset, defaultOpen = true, className, headerClassName, contentClassName }) {
  return (
    <Collapsible defaultOpen={defaultOpen} className={cn("rounded-xl border border-border bg-card card-soft", className)}>
      <div className={cn("flex items-center justify-between gap-2 px-3 py-2", headerClassName)}>
        <CollapsibleTrigger asChild>
          <button type="button" className="group flex items-center gap-2 text-[13px] font-semibold text-foreground">
            <ChevronDown className="h-3.5 w-3.5 text-muted-foreground transition-transform group-data-[state=closed]:-rotate-90" />
            فلاتر البحث
            {activeCount > 0 && (
              <span className="num rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-bold text-primary">{activeCount}</span>
            )}
          </button>
        </CollapsibleTrigger>
        {onReset && (
          <Button type="button" variant="ghost" size="sm" className="h-7 text-xs text-muted-foreground hover:text-foreground" onClick={onReset}>
            مسح الفلاتر
          </Button>
        )}
      </div>
      <CollapsibleContent>
        <div className={cn("border-t border-border px-3 py-3", contentClassName)}>{children}</div>
      </CollapsibleContent>
    </Collapsible>
  );
}