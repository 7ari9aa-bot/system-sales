import React from "react";
import { Link } from "react-router-dom";
import { ArrowRight, TrendingUp, AlertTriangle, Sparkles } from "lucide-react";
import { SectionCard } from "@/components/dashboard/ui";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import useSalesStats from "@/hooks/useSalesStats";

const TONE = {
  success: { icon: TrendingUp, ring: "bg-success/15 text-success" },
  warning: { icon: AlertTriangle, ring: "bg-warning/15 text-warning" },
  primary: { icon: Sparkles, ring: "bg-primary/10 text-primary" },
};

/** رؤى الأعمال — مشتقة من أرقام حقيقية: أعلى مصدر منسوب، صحة المخزون،
 *  طلبات الذكاء. الرؤية بتظهر بس لما بياناتها موجودة. */
export default function BusinessInsights() {
  const t = useT();
  const live = useSalesStats("30d");

  const insights = [];
  const top = live?.sources?.[0];
  if (top) {
    insights.push({
      id: "i1", tone: "success",
      title: t("insight.source.title", { name: top.source }),
      body: t("insight.source.body", { money: formatMoneyShort(top.revenue), n: top.conversions }),
      actionKey: t("home.viewAnalytics"), to: "/analytics",
    });
  }
  const low = live?.lowStock ?? 0;
  const out = live?.outOfStock ?? 0;
  if (low > 0 || out > 0) {
    insights.push({
      id: "i2", tone: "warning",
      title: t("insight.stock.title", { n: low }),
      body: t("insight.stock.body", { m: out }),
      actionKey: t("home.attention.lowStock.action"), to: "/inventory",
    });
  }
  const aiOrders = live?.aiOrders ?? 0;
  if (aiOrders > 0) {
    insights.push({
      id: "i3", tone: "primary",
      title: t("insight.ai.title", { n: aiOrders }),
      body: t("insight.ai.body"),
      actionKey: t("home.manageAI"), to: "/ai",
    });
  }

  return (
    <SectionCard title={t("home.businessInsights.title")} action={t("home.exploreAnalytics")} actionTo="/analytics">
      {insights.length === 0 ? (
        <p className="py-6 text-center text-[12.5px] text-muted-foreground">{t("insight.empty")}</p>
      ) : (
        <div className="space-y-2.5">
          {insights.map((ins) => {
            const tone = TONE[ins.tone];
            const Icon = tone.icon;
            return (
              <Link
                key={ins.id}
                to={ins.to}
                className="group flex gap-3.5 p-3 -mx-1 rounded-xl hover:bg-surface/60 transition-colors"
              >
                <span className={cn("h-9 w-9 shrink-0 rounded-lg grid place-items-center", tone.ring)}>
                  <Icon className="h-[18px] w-[18px]" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-[13.5px] font-medium line-clamp-2">{ins.title}</div>
                  <div className="text-[12px] text-muted-foreground mt-0.5 leading-relaxed line-clamp-2 min-h-[2.5rem]">{ins.body}</div>
                  <span className="inline-flex items-center gap-1 text-[12px] font-medium text-primary mt-1.5 group-hover:gap-1.5 transition-all">
                    {ins.actionKey}
                    <ArrowRight className="h-3.5 w-3.5" />
                  </span>
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </SectionCard>
  );
}

function formatMoneyShort(v) {
  const n = Number(v ?? 0);
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(n);
}
