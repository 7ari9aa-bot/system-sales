import React from "react";
import { ArrowRight, DollarSign, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";
import { SectionCard } from "@/components/dashboard/ui";
import { useRealUsage } from "@/hooks/useRealData";
import { formatCurrency } from "@/lib/regional";

export default function PlanUsage() {
  const { data, loading, error, retry } = useRealUsage();
  const totals = data?.totals;
  const tokenCount = totals
    ? (Number(totals.tokens_in) || 0) + (Number(totals.tokens_out) || 0)
    : null;

  return (
    <SectionCard title="Usage" action="Manage billing" actionTo="/settings/billing">
      {error && (
        <div role="alert" className="mb-4 flex items-center justify-between gap-3 text-[12px] text-destructive">
          <span>{error}</span>
          <button type="button" onClick={retry} className="shrink-0 underline">Retry</button>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="flex items-center gap-2 text-[12px] text-muted-foreground">
            <Sparkles className="h-4 w-4" />AI tokens
          </div>
          <div className="mt-2 font-display text-[22px] font-semibold tabular-nums">
            {loading ? "…" : tokenCount == null ? "—" : tokenCount.toLocaleString()}
          </div>
        </div>
        <div className="rounded-xl border border-border bg-surface p-4">
          <div className="flex items-center gap-2 text-[12px] text-muted-foreground">
            <DollarSign className="h-4 w-4" />AI spend
          </div>
          <div className="mt-2 font-display text-[22px] font-semibold tabular-nums">
            {loading ? "…" : totals?.cost == null ? "—" : formatCurrency(Number(totals.cost), false, "USD")}
          </div>
        </div>
      </div>

      <div className="mt-4 flex items-center justify-between gap-3 border-t border-border pt-4 text-[11.5px] text-muted-foreground">
        <span>Usage totals come from the backend. Plan limits and renewal dates are not available yet.</span>
        <Link to="/settings/billing" className="inline-flex shrink-0 items-center gap-1 font-medium text-primary hover:underline">
          View billing <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </div>
    </SectionCard>
  );
}
