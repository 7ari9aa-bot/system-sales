import React from "react";
import { Sparkles, ShieldCheck, Users, ListChecks, ShoppingBag, Repeat, Plus, Power } from "lucide-react";
import { PageHeader, Badge, SectionCard, ProgressBar } from "@/components/dashboard/ui";
import useSalesStats from "@/hooks/useSalesStats";
import useUsageSummary from "@/hooks/useUsageSummary";
import useApprovals from "@/hooks/useApprovals";
import { formatCurrency } from "@/lib/regional";
import { useT } from "@/lib/i18n";

function Stat({ icon: Icon, label, value, tone }) {
  const toneClass = {
    primary: "bg-primary/10 text-primary",
    accent: "bg-accent/10 text-accent",
    warning: "bg-warning/15 text-warning",
    muted: "bg-surface text-muted-foreground",
  }[tone];
  return (
    <div className="rounded-2xl bg-card border border-border p-4">
      <span className={`h-9 w-9 rounded-lg grid place-items-center ${toneClass}`}>
        <Icon className="h-[18px] w-[18px]" />
      </span>
      <div className="mt-3 font-display text-[22px] font-semibold tabular-nums leading-none">{value}</div>
      <div className="text-[12px] text-muted-foreground mt-1 leading-tight line-clamp-2 min-h-[2rem]">{label}</div>
    </div>
  );
}

export default function AI() {
  const t = useT();
  const live = useSalesStats("30d");
  const usage = useUsageSummary();
  const approvals = useApprovals();
  const [agents, setAgents] = React.useState([]);
  React.useEffect(() => {
    let alive = true;
    import("@/lib/api").then(({ api }) =>
      api("/ai/agents").then((rows) => alive && setAgents(Array.isArray(rows) ? rows : [])).catch(() => alive && setAgents([]))
    );
    return () => { alive = false; };
  }, []);
  const pending = approvals?.items?.length ?? 0;
  const tokens = usage?.totals ? (usage.totals.tokens_in ?? 0) + (usage.totals.tokens_out ?? 0) : null;
  const cost = usage?.totals?.cost ?? null;
  const a = {
    conversationsHandled: live?.openConversations ?? 0,
    automationRate: null,
    handovers: null,
    leadsQualified: null,
    followUps: null,
    ordersAssisted: live?.aiOrders ?? 0,
    approvalsWaiting: pending,
    spendThisMonth: cost == null ? 0 : Number(cost),
    tokensUsed: tokens,
  };
  return (
    <div>
      <PageHeader
        title={t("ai.title")}
        subtitle={t("ai.subtitle")}
        actions={
          <button className="h-9 px-3.5 rounded-lg bg-primary text-primary-foreground text-[13px] font-medium flex items-center gap-1.5">
            <Plus className="h-4 w-4" /> {t("ai.new")}
          </button>
        }
      />

      <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-3.5 mb-5">
        <Stat icon={Repeat} label={t("ai.stat.conversations")} value={a.conversationsHandled.toLocaleString()} tone="accent" />
        <Stat icon={Sparkles} label={t("ai.stat.tokens")} value={a.tokensUsed == null ? "—" : a.tokensUsed.toLocaleString()} tone="primary" />
        <Stat icon={ShieldCheck} label={t("ai.stat.pendingApprovals")} value={a.approvalsWaiting.toLocaleString()} tone="warning" />
        <Stat icon={Users} label={t("ai.stat.activeAgents")} value={agents.filter((ag) => ag.is_active).length.toLocaleString()} tone="accent" />
        <Stat icon={ListChecks} label={t("ai.stat.openConversations")} value={(live?.openConversations ?? 0).toLocaleString()} tone="primary" />
        <Stat icon={ShoppingBag} label={t("ai.stat.orders")} value={a.ordersAssisted} tone="muted" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <SectionCard title={t("ai.agents.title")} className="lg:col-span-2" bodyClassName="pt-1">
          <div className="space-y-3">
            {agents.map((ag) => (
              <div key={ag.id} className="flex items-center gap-3.5 p-3.5 rounded-xl border border-border hover:bg-surface/50 transition-colors">
                <span className="h-10 w-10 shrink-0 rounded-xl bg-accent/10 text-accent grid place-items-center">
                  <Sparkles className="h-5 w-5" />
                </span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-[14px] font-semibold truncate">{ag.name}</span>
                    <Badge tone="success"><span className="h-1.5 w-1.5 rounded-full bg-success" /> {t("ai.agents.active")}</Badge>
                  </div>
                  <div className="text-[12px] text-muted-foreground mt-0.5 truncate">
                    {t("ai.agents.summary", { handled: ag.handled, automation: ag.automation, handovers: ag.handovers })}
                  </div>
                </div>
                <button className="h-8 w-8 grid place-items-center rounded-lg hover:bg-surface text-muted-foreground">
                  <Power className="h-4 w-4" />
                </button>
              </div>
            ))}
          </div>
        </SectionCard>

        <SectionCard title={t("ai.approvals.title")} action={t("common.viewAll")} actionTo="/ai">
          <div className="rounded-xl border border-warning/30 bg-warning/10 p-4">
            <div className="flex items-center gap-2 text-warning font-medium text-[13px]">
              <ShieldCheck className="h-4 w-4" />
              {t("ai.approvals.waiting", { n: a.approvalsWaiting })}
            </div>
            <p className="text-[12px] text-muted-foreground mt-1.5 leading-relaxed">
              {t("ai.approvals.body")}
            </p>
            <button className="mt-3 w-full h-9 rounded-lg bg-warning text-white text-[13px] font-medium">
              {t("ai.approvals.review")}
            </button>
          </div>
        </SectionCard>
      </div>

      <div className="mt-5">
        <SectionCard title={t("ai.usage.title")} bodyClassName="pt-3">
          <div className="grid sm:grid-cols-2 gap-5">
            <div className="flex items-center gap-3.5">
              <span className="h-11 w-11 rounded-xl bg-accent/10 text-accent grid place-items-center text-[13px] font-bold tabular-nums" dir="ltr">
                {a.tokensUsed == null ? "—" : a.tokensUsed >= 1000 ? `${(a.tokensUsed / 1000).toFixed(1)}K` : a.tokensUsed}
              </span>
              <div>
                <div className="text-[13px] font-medium">{t("ai.stat.tokens")}</div>
                <div className="text-[12px] text-muted-foreground">{t("ai.usage.thisCycle")}</div>
              </div>
            </div>
            <div className="flex items-center gap-3.5">
              <span className="h-11 w-11 rounded-xl bg-warning/15 text-warning grid place-items-center font-display text-[15px] font-bold">
                {a.spendThisMonth ? formatCurrency(a.spendThisMonth) : "—"}
              </span>
              <div>
                <div className="text-[13px] font-medium">{t("ai.usage.spend")}</div>
                <div className="text-[12px] text-muted-foreground">{t("ai.usage.thisCycle")}</div>
              </div>
            </div>
          </div>
        </SectionCard>
      </div>
    </div>
  );
}