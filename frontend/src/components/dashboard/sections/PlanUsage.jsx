import React from "react";
import { Sparkles, MessageSquare, Users, ArrowRight, CreditCard } from "lucide-react";
import { Link } from "react-router-dom";
import { SectionCard, ProgressBar } from "@/components/dashboard/ui";
import { useRealUsage } from "@/hooks/useRealData";
import { formatCurrency } from "@/lib/regional";

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

export default function PlanUsage() {
  const u = useRealUsage();
  return (
    <SectionCard title="Plan & usage" action="Manage plan" actionTo="/billing">
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-2.5">
          <span className="h-9 w-9 rounded-lg bg-primary text-primary-foreground grid place-items-center font-display font-semibold text-[13px]">
            G
          </span>
          <div>
            <div className="font-display text-[16px] font-semibold leading-none">{u.plan ?? "Early access"} plan</div>
            <div className="text-[12px] text-muted-foreground mt-1"><span className="bdi">{u.spend == null ? "—" : formatCurrency(u.spend, false, "USD")}</span> spent this cycle</div>
          </div>
        </div>
        <Link to="/billing" className="inline-flex items-center gap-1 text-[12.5px] font-medium text-primary hover:gap-1.5 transition-all">
          View usage <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </div>

      <div className="grid sm:grid-cols-3 gap-5">
        <UsageRow icon={Sparkles} label="AI usage" used={u.aiUsage.used} limit={u.aiUsage.limit} unit="credits" tone="accent" />
        <UsageRow icon={MessageSquare} label="Conversations" used={u.conversations.used} limit={u.conversations.limit} unit="" tone="primary" />
        <UsageRow icon={Users} label="Team members" used={u.team.used} limit={u.team.limit} unit="seats" tone="primary" />
      </div>

      <div className="mt-5 pt-4 border-t border-border flex items-center justify-between">
        <span className="text-[12px] text-muted-foreground flex items-center gap-1.5">
          <CreditCard className="h-3.5 w-3.5" />
          Renews Oct 14
        </span>
        <Link to="/billing" className="text-[12.5px] font-medium text-primary hover:underline">
          Upgrade plan
        </Link>
      </div>
    </SectionCard>
  );
}
