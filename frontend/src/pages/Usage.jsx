import React from "react";
import { Sparkles, MessageSquare, Users, CreditCard, ArrowRight, Cpu } from "lucide-react";
import { Link } from "react-router-dom";
import { PageHeader, SectionCard, ProgressBar, Badge } from "@/components/dashboard/ui";
import { USAGE, TOKEN_USAGE } from "@/lib/dashboardData";
import { formatCurrency } from "@/lib/regional";
import { cn } from "@/lib/utils";

function UsageRow({ icon: Icon, label, used, limit, tone, unit }) {
  const pct = Math.round((used / limit) * 100);
  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <span className="flex items-center gap-2 text-[13px] font-medium">
          <Icon className="h-4 w-4 text-muted-foreground" />
          {label}
        </span>
        <span className="text-[12.5px] tabular-nums text-muted-foreground">
          {used.toLocaleString()} / {limit.toLocaleString()} {unit}
        </span>
      </div>
      <ProgressBar used={used} limit={limit} tone={pct > 85 ? "warning" : tone} />
      <div className="mt-1 text-[11.5px] text-muted-foreground">{(limit - used).toLocaleString()} {unit} remaining</div>
    </div>
  );
}

const TONE_BG = {
  accent: "bg-accent",
  primary: "bg-primary",
  warning: "bg-warning",
  "chart-4": "bg-chart-4",
};

export default function Usage() {
  const u = USAGE;
  const tokenPct = Math.round((TOKEN_USAGE.total / TOKEN_USAGE.limit) * 100);

  return (
    <div className="space-y-5 animate-fade-in">
      <PageHeader
        title="Plan & usage"
        subtitle="Track your plan limits, AI token consumption, and billing cycle."
        actions={
          <Link to="/billing" className="inline-flex items-center gap-1.5 h-9 px-3.5 rounded-lg bg-primary text-primary-foreground text-[13px] font-medium hover:opacity-90 transition-opacity">
            <CreditCard className="h-4 w-4" />
            Manage billing
          </Link>
        }
      />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <SectionCard title="Plan" className="lg:col-span-1">
          <div className="flex items-center gap-2.5 mb-4">
            <span className="h-10 w-10 rounded-lg bg-primary text-primary-foreground grid place-items-center font-display font-semibold text-[15px]">
              G
            </span>
            <div>
              <div className="font-display text-[17px] font-semibold leading-none">{u.plan} plan</div>
              <div className="text-[12px] text-muted-foreground mt-1"><span className="bdi">{formatCurrency(u.spend)}</span> spent this cycle</div>
            </div>
          </div>
          <div className="space-y-4">
            <UsageRow icon={Sparkles} label="AI usage" used={u.aiUsage.used} limit={u.aiUsage.limit} unit="credits" tone="accent" />
            <UsageRow icon={MessageSquare} label="Conversations" used={u.conversations.used} limit={u.conversations.limit} unit="" tone="primary" />
            <UsageRow icon={Users} label="Team members" used={u.team.used} limit={u.team.limit} unit="seats" tone="primary" />
          </div>
          <div className="mt-5 pt-4 border-t border-border flex items-center justify-between">
            <span className="text-[12px] text-muted-foreground flex items-center gap-1.5">
              <CreditCard className="h-3.5 w-3.5" />
              Renews Oct 14
            </span>
            <Link to="/billing" className="text-[12.5px] font-medium text-primary hover:underline inline-flex items-center gap-1">
              Upgrade plan <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        </SectionCard>

        <SectionCard title="AI token consumption" className="lg:col-span-2" action="By model">
          <div className="flex items-end justify-between mb-4">
            <div>
              <div className="font-display text-[28px] font-semibold tabular-nums leading-none">
                {TOKEN_USAGE.total.toLocaleString()}
              </div>
              <div className="text-[12px] text-muted-foreground mt-1.5">
                of {TOKEN_USAGE.limit.toLocaleString()} tokens this cycle
              </div>
            </div>
            <Badge tone={tokenPct > 85 ? "warning" : "primary"}>{tokenPct}% used</Badge>
          </div>

          <div className="h-2 w-full rounded-full bg-surface overflow-hidden mb-5 flex">
            {TOKEN_USAGE.models.map((m) => (
              <div
                key={m.id}
                className={TONE_BG[m.tone] || "bg-muted-foreground"}
                style={{ width: `${(m.tokens / TOKEN_USAGE.limit) * 100}%` }}
              />
            ))}
          </div>

          <div className="grid sm:grid-cols-2 gap-3">
            {TOKEN_USAGE.models.map((m) => (
              <div key={m.id} className="flex items-center gap-3 p-3 rounded-xl border border-border bg-surface/50">
                <span className="h-9 w-9 rounded-lg bg-card border border-border grid place-items-center shrink-0">
                  <Cpu className="h-4 w-4 text-muted-foreground" />
                </span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between">
                    <span className="text-[13px] font-medium truncate">{m.name}</span>
                    <span className={cn("h-2 w-2 rounded-full shrink-0 ml-2", TONE_BG[m.tone] || "bg-muted-foreground")} />
                  </div>
                  <div className="flex items-center justify-between mt-0.5">
                    <span className="text-[11.5px] text-muted-foreground tabular-nums">
                      {m.tokens.toLocaleString()} tokens
                    </span>
                    <span className="text-[11.5px] text-muted-foreground tabular-nums">{m.share}%</span>
                  </div>
                </div>
              </div>
            ))}
          </div>

          <div className="mt-5 pt-4 border-t border-border flex items-center justify-between">
            <span className="text-[12px] text-muted-foreground">Total spend this cycle</span>
            <span className="text-[14px] font-semibold tabular-nums bdi">{formatCurrency(TOKEN_USAGE.cycleSpend)}</span>
          </div>
        </SectionCard>
      </div>
    </div>
  );
}