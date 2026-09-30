import React from "react";
import { Sparkles, ArrowRight, ShieldCheck, Users, ListChecks, ShoppingBag, Repeat, DollarSign, MessageSquare } from "lucide-react";
import { Link } from "react-router-dom";
import { SectionCard } from "@/components/dashboard/ui";
import { formatCurrency } from "@/lib/regional";
import { useT } from "@/lib/i18n";
import useSalesStats from "@/hooks/useSalesStats";
import useUsageSummary from "@/hooks/useUsageSummary";
import useApprovals from "@/hooks/useApprovals";

function Stat({ icon: Icon, label, value, tone }) {
  const toneClass = {
    primary: "bg-primary/10 text-primary",
    accent: "bg-accent/10 text-accent",
    warning: "bg-warning/15 text-warning",
    muted: "bg-surface text-muted-foreground",
  }[tone];
  return (
    <div className="flex items-center gap-3">
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
  const [agents, setAgents] = React.useState([]);

  React.useEffect(() => {
    let alive = true;
    import("@/lib/api").then(({ api }) =>
      api("/ai/agents")
        .then((rows) => alive && setAgents(Array.isArray(rows) ? rows : []))
        .catch(() => alive && setAgents([])),
    );
    return () => {
      alive = false;
    };
  }, []);

  const pending = approvals?.items?.length ?? 0;
  const activeAgents = agents.filter((a) => a.is_active).length;
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
    >
      <div className="grid grid-cols-2 gap-x-4 gap-y-4">
        <Stat icon={MessageSquare} label={t("ai.stat.openConversations")} value={(live?.openConversations ?? 0).toLocaleString()} tone="accent" />
        <Stat icon={ShoppingBag} label={t("home.aiOrdersHint")} value={(live?.aiOrders ?? 0).toLocaleString()} tone="primary" />
        <Stat icon={ShieldCheck} label={t("ai.stat.pendingApprovals")} value={pending.toLocaleString()} tone="warning" />
        <Stat icon={Users} label={t("ai.stat.activeAgents")} value={activeAgents.toLocaleString()} tone="accent" />
        <Stat icon={ListChecks} label={t("ai.stat.tokens")} value={tokens == null ? "—" : tokens.toLocaleString()} tone="primary" />
        <Stat icon={DollarSign} label={t("home.aiSpend")} value={cost == null ? "—" : formatCurrency(Number(cost))} tone="muted" />
      </div>

      <div className="mt-4 pt-4 border-t border-border flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5 min-w-0">
          <span className="h-8 w-8 rounded-lg bg-warning/15 text-warning grid place-items-center">
            <DollarSign className="h-4 w-4" />
          </span>
          <div>
            <div className="font-display text-[16px] font-semibold tabular-nums leading-none bdi">
              {cost == null ? "—" : formatCurrency(Number(cost))}
            </div>
            <div className="text-[12px] text-muted-foreground mt-1">{t("home.usedThisMonth")}</div>
          </div>
        </div>
        <Link to="/ai" className="shrink-0 whitespace-nowrap inline-flex items-center gap-1 text-[12.5px] font-medium text-primary hover:gap-1.5 transition-all">
          {t("home.approvalsWaiting", { n: pending })}
          <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </div>
    </SectionCard>
  );
}
