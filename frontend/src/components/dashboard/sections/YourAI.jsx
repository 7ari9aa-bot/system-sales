import React from "react";
import { Sparkles, ArrowRight, ShieldCheck, Users, ListChecks, ShoppingBag, DollarSign, MessageSquare } from "lucide-react";
import { Link } from "react-router-dom";
import { SectionCard } from "@/components/dashboard/ui";
import { formatCurrency } from "@/lib/regional";
import { useT } from "@/lib/i18n";
import useSalesStats from "@/hooks/useSalesStats";
import useUsageSummary from "@/hooks/useUsageSummary";
import useApprovals from "@/hooks/useApprovals";
import { apiCached, peekCache } from "@/lib/api";

function Stat({ icon: Icon, label, value, tone }) {
  const toneClass = {
    primary: "bg-primary/10 text-primary",
    accent: "bg-accent/10 text-accent",
    warning: "bg-warning/15 text-warning",
    muted: "bg-surface text-muted-foreground",
  }[tone];
  return (
    <div className="flex items-center gap-3 rounded-xl border border-border/70 bg-surface-subtle px-3.5 py-3">
      <span className={`h-9 w-9 shrink-0 rounded-lg grid place-items-center ${toneClass}`}>
        <Icon className="h-[17px] w-[17px]" />
      </span>
      <div className="min-w-0">
        <div className="font-display text-[19px] font-semibold tabular-nums leading-none">{value}</div>
        <div className="text-[12px] text-muted-foreground mt-1 leading-tight line-clamp-2 min-h-[2rem]">{label}</div>
      </div>
    </div>
  );
}

/** مساعدك الذكي — ست أرقام حقيقية: محادثات مفتوحة وطلبات بمساعدة
 *  الذكاء من read model السيرفر، موافقات معلّقة، وكلاء نشطون، توكنز
 *  ومصروف من /ai/usage/summary. مفيش معدلات أتمتة وهمية. */
export default function YourAI() {
  const t = useT();
  const live = useSalesStats("30d");
  const usage = useUsageSummary();
  const approvals = useApprovals();
  const [agents, setAgents] = React.useState(null);
  const [agentError, setAgentError] = React.useState("");
  const [agentAttempt, setAgentAttempt] = React.useState(0);

  React.useEffect(() => {
    let alive = true;
    const cached = peekCache("/ai/agents");
    if (cached) setAgents(Array.isArray(cached) ? cached : []);
    apiCached("/ai/agents")
      .then((rows) => {
        if (!alive) return;
        setAgents(Array.isArray(rows) ? rows : []);
        setAgentError("");
      })
      .catch((error) => {
        if (!alive) return;
        setAgentError(error?.message || "Could not load AI agents");
      });
    return () => {
      alive = false;
    };
  }, [agentAttempt]);

  const pending = approvals?.items?.length ?? null;
  const activeAgents = agents?.filter((a) => a.is_active).length ?? null;
  const tokens = usage?.totals ? (usage.totals.tokens_in ?? 0) + (usage.totals.tokens_out ?? 0) : null;
  const cost = usage?.totals?.cost ?? null;

  return (
    <SectionCard
      title={
        <span className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-accent" />
          {t("home.yourAI.title")}
        </span>
      }
      action={t("home.manageAI")}
      actionTo="/ai"
      className="h-full"
      bodyClassName="flex flex-col gap-4 h-[calc(100%-54px)]"
    >
      {(live?.dashboardError || usage?.error || approvals?.error || agentError) && <div role="status" className="mb-3 flex flex-wrap items-center justify-between gap-2 text-[11.5px] text-muted-foreground">
        <span>{live?.dashboardError || usage?.error || approvals?.error || agentError}</span>
        <span className="flex items-center gap-3">
          {live?.dashboardError && <button type="button" onClick={live.retryDashboard} className="text-primary hover:underline">{t("common.retry", "Retry")}</button>}
          {usage?.error && <button type="button" onClick={usage.retry} className="text-primary hover:underline">{t("common.retry", "Retry")}</button>}
          {approvals?.error && <button type="button" onClick={approvals.retry} className="text-primary hover:underline">{t("common.retry", "Retry")}</button>}
          {agentError && <button type="button" onClick={() => setAgentAttempt((attempt) => attempt + 1)} className="text-primary hover:underline">{t("common.retry", "Retry")}</button>}
        </span>
      </div>}
      <div className="grid flex-1 grid-cols-2 gap-2.5 [grid-auto-rows:1fr]">
        <Stat icon={MessageSquare} label={t("ai.stat.openConversations")} value={live?.openConversations == null ? "—" : live.openConversations.toLocaleString()} tone="accent" />
        <Stat icon={ShoppingBag} label={t("home.aiOrdersHint")} value={live?.aiOrders == null ? "—" : live.aiOrders.toLocaleString()} tone="primary" />
        <Stat icon={ShieldCheck} label={t("ai.stat.pendingApprovals")} value={pending == null || approvals?.error ? "—" : `${pending.toLocaleString()}${approvals?.truncated ? "+" : ""}`} tone="warning" />
        <Stat icon={Users} label={t("ai.stat.activeAgents")} value={activeAgents == null ? "—" : activeAgents.toLocaleString()} tone="accent" />
        <Stat icon={ListChecks} label={t("ai.stat.tokens")} value={tokens == null ? "—" : tokens.toLocaleString()} tone="primary" />
        <Stat icon={DollarSign} label={t("home.aiSpend")} value={cost == null ? "—" : formatCurrency(Number(cost), false, "USD")} tone="muted" />
      </div>

      <div className="mt-4 pt-4 border-t border-border flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5 min-w-0">
          <span className="h-8 w-8 rounded-lg bg-warning/15 text-warning grid place-items-center">
            <DollarSign className="h-4 w-4" />
          </span>
          <div>
            <div className="font-display text-[16px] font-semibold tabular-nums leading-none bdi">
              {cost == null ? "—" : formatCurrency(Number(cost), false, "USD")}
            </div>
            <div className="text-[12px] text-muted-foreground mt-1">{t("ai.usage.thisCycle")}</div>
          </div>
        </div>
        <Link to="/ai" className="shrink-0 whitespace-nowrap inline-flex items-center gap-1 text-[12.5px] font-medium text-primary hover:gap-1.5 transition-all">
          {pending == null || approvals?.error ? "—" : t("home.approvalsWaiting", { n: approvals?.truncated ? `${pending}+` : pending })}
          <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </div>
    </SectionCard>
  );
}
