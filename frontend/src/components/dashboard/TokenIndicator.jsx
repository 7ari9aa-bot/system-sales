import React, { useState, useRef, useEffect } from "react";
import { Sparkles, ChevronDown } from "lucide-react";
import { formatCurrency } from "@/lib/regional";
import { cn } from "@/lib/utils";
import useUsageSummary from "@/hooks/useUsageSummary";

/** مؤشر استهلاك الذكاء — أرقام حقيقية من /ai/usage/summary: التوكنز
 *  المستهلكة (in+out) ومصروف الفترة. مفيش «حد باقة» من الـbackend
 *  فمش بنعرض حد وهمي. */
export default function TokenIndicator() {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const usage = useUsageSummary();

  useEffect(() => {
    function handler(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const tokens = usage?.totals ? (usage.totals.tokens_in ?? 0) + (usage.totals.tokens_out ?? 0) : null;
  const cost = usage?.totals?.cost ?? null;

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 h-9 px-2.5 rounded-lg border border-border text-[12.5px] font-medium hover:bg-surface transition-colors"
        title="AI token consumption"
      >
        <Sparkles className="h-3.5 w-3.5 text-accent" />
        <span className="tabular-nums hidden sm:inline">
          {tokens == null ? "—" : tokens >= 1000 ? `${(tokens / 1000).toFixed(1)}K` : tokens}
        </span>
        <ChevronDown className={cn("h-3.5 w-3.5 text-muted-foreground transition-transform", open && "rotate-180")} />
      </button>

      {open && (
        <div className="absolute right-0 z-50 mt-2 w-64 rounded-xl border border-border bg-popover shadow-lg p-3 animate-fade-in">
          <div className="flex items-center justify-between mb-1">
            <span className="text-[12.5px] font-semibold">AI tokens used</span>
          </div>
          <div className="flex items-center justify-between text-[12px]">
            <span className="text-muted-foreground">Used</span>
            <span className="tabular-nums font-medium bdi">
              {tokens == null ? "—" : tokens.toLocaleString()}
            </span>
          </div>
          <div className="mt-3 pt-2 border-t border-border flex items-center justify-between text-[11.5px] text-muted-foreground">
            <span>Spent this cycle</span>
            <span className="tabular-nums font-medium text-foreground bdi">
              {cost == null ? "—" : formatCurrency(Number(cost))}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
