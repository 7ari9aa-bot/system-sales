import React from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Boxes, CheckCircle2, MessageSquare, ShieldCheck, ShoppingBag } from "lucide-react";
import { SectionCard, Skeleton } from "@/components/dashboard/ui";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import useSalesStats from "@/hooks/useSalesStats";
import useApprovals from "@/hooks/useApprovals";

const ICONS = {
  approval: ShieldCheck,
  inbox: MessageSquare,
  inventory: Boxes,
  orders: ShoppingBag,
};

/** يحتاج انتباه — عناصر مشتقة من أرقام حقيقية فقط، والعنصر بيظهر بس
 *  لما رقمه أعلى من صفر: موافقات معلّقة، محادثات غير مقروءة، منتجات
 *  نفدت، ومنتجات مخزونها منخفض. */
export default function NeedsAttention() {
  const t = useT();
  const live = useSalesStats("30d");
  const approvals = useApprovals();

  const items = [];
  const pending = approvals?.error ? null : approvals?.items?.length ?? null;
  if (pending > 0) {
    items.push({
      id: "ap1", type: "approval", tone: "primary",
      title: t("home.attention.approvals.title", { n: approvals?.truncated ? `${pending}+` : pending }),
      detailKey: t("home.attention.approvals.detail"),
      actionKey: t("home.attention.approvals.action"), to: "/ai",
    });
  }
  const unread = live?.unread ?? 0;
  if (unread > 0) {
    items.push({
      id: "ap2", type: "inbox", tone: "primary",
      title: t("home.attention.inbox.title", { n: unread }),
      detailKey: t("home.attention.inbox.detail"),
      actionKey: t("home.attention.inbox.action"), to: "/inbox",
    });
  }
  const out = live?.outOfStock ?? 0;
  if (out > 0) {
    items.push({
      id: "ap3", type: "inventory", tone: "destructive",
      title: t("home.attention.outOfStock.title", { n: out }),
      detailKey: t("home.attention.outOfStock.detail"),
      actionKey: t("home.attention.outOfStock.action"), to: "/inventory",
    });
  }
  const low = live?.lowStock ?? 0;
  if (low > 0) {
    items.push({
      id: "ap4", type: "inventory", tone: "warning",
      title: t("home.attention.lowStock.title", { n: low }),
      detailKey: t("home.attention.lowStock.detail"),
      actionKey: t("home.attention.lowStock.action"), to: "/inventory",
    });
  }

  const toneRing = {
    warning: "bg-warning/15 text-warning",
    primary: "bg-primary/10 text-primary",
    destructive: "bg-destructive/10 text-destructive",
  };
  const loadError = live?.dashboardError || approvals?.error;
  const retryUnavailable = () => {
    if (live?.dashboardError) live.retryDashboard();
    if (approvals?.error) approvals.retry();
  };

  return (
    <SectionCard title={t("home.needsAttention.title")} testid="needs-attention">
      {!live && approvals == null ? (
        <div className="space-y-3 py-2">
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex items-center gap-3.5">
              <Skeleton className="h-9 w-9 rounded-lg" />
              <div className="flex-1 space-y-1.5">
                <Skeleton className="h-3.5 w-2/5" />
                <Skeleton className="h-3 w-3/5" />
              </div>
            </div>
          ))}
        </div>
      ) : !live || approvals == null ? (
        <div role="status" className="py-3 text-center text-[12.5px] text-muted-foreground">{t("common.loading", "Loading current signals…")}</div>
      ) : items.length === 0 && loadError ? (
        <div role="alert" className="flex flex-col items-center gap-2 py-3 text-center text-[12.5px] text-muted-foreground">
          <span>{loadError}</span>
          <button type="button" onClick={retryUnavailable} className="text-primary hover:underline">{t("common.retry", "Retry")}</button>
        </div>
      ) : items.length === 0 ? (
        <div role="status" className="flex min-h-12 items-center gap-3 rounded-xl bg-success/5 px-3 py-2.5">
          <CheckCircle2 className="h-5 w-5 shrink-0 text-success" />
          <div className="min-w-0 flex flex-col gap-0.5 sm:flex-row sm:items-baseline sm:gap-2">
            <p className="font-display text-[13.5px] font-semibold">{t("home.allCaughtUp")}</p>
            <p className="text-[12px] text-muted-foreground">{t("home.allCaughtUpDesc")}</p>
          </div>
        </div>
      ) : (
        <>
        {loadError && <p role="status" className="mb-2 flex items-center justify-between gap-2 text-[11.5px] text-muted-foreground">
          <span>{loadError}</span>
          <button type="button" onClick={retryUnavailable} className="shrink-0 text-primary hover:underline">{t("common.retry", "Retry")}</button>
        </p>}
        <ul className="divide-y divide-border">
          {items.map((item) => {
            const Icon = ICONS[item.type] || MessageSquare;
            return (
              <li key={item.id} data-testid={`attention-${item.type}`}>
                <Link
                  to={item.to}
                  className="group flex items-center gap-3.5 py-3 first:pt-1 last:pb-1 -mx-1 px-1 rounded-lg hover:bg-surface/60 transition-colors"
                >
                  <span className={cn("h-9 w-9 shrink-0 rounded-lg grid place-items-center", toneRing[item.tone])}>
                    <Icon className="h-[18px] w-[18px]" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="text-[13.5px] font-medium truncate">{item.title}</div>
                    <div className="text-[12px] text-muted-foreground truncate">{item.detailKey}</div>
                  </div>
                  <span className="hidden sm:inline-flex items-center gap-1 text-[12.5px] font-medium text-primary opacity-0 group-hover:opacity-100 transition-opacity">
                    {item.actionKey}
                    <ArrowRight className="h-3.5 w-3.5" />
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
        </>
      )}
    </SectionCard>
  );
}
