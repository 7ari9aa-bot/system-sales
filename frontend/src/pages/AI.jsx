import React from "react";
import { useNavigate } from "react-router-dom";
import {
  Sparkles,
  ShieldCheck,
  Users,
  ListChecks,
  ShoppingBag,
  Repeat,
  Plus,
  Power,
  Check,
  X,
  Cpu,
  Layers,
  Wrench,
  CheckCircle2,
} from "lucide-react";
import { PageHeader, Badge, SectionCard } from "@/components/dashboard/ui";
import useSalesStats from "@/hooks/useSalesStats";
import useUsageSummary from "@/hooks/useUsageSummary";
import useApprovals from "@/hooks/useApprovals";
import { formatCurrency } from "@/lib/regional";
import { useI18n, useT } from "@/lib/i18n";
import { api, apiCached, invalidateCache, peekCache } from "@/lib/api";

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

const AGENTS_PATH = "/ai/agents";
const APPROVALS_PATH = "/ai/approvals?status=PENDING";
const AGENT_KINDS_PATH = "/ai/agent-kinds";

export default function AI() {
  const t = useT();
  const { lang } = useI18n();
  const navigate = useNavigate();
  const isAr = lang === "ar";
  const live = useSalesStats("30d");
  const usage = useUsageSummary();
  const approvals = useApprovals();
  const [agents, setAgents] = React.useState(() => peekCache(AGENTS_PATH) || null);
  const [agentKinds, setAgentKinds] = React.useState(() => peekCache(AGENT_KINDS_PATH) || null);
  const [agentError, setAgentError] = React.useState("");
  const [approvalError, setApprovalError] = React.useState("");
  const [resolvedApprovals, setResolvedApprovals] = React.useState(() => new Set());
  const [busyAgent, setBusyAgent] = React.useState("");
  const [busyApproval, setBusyApproval] = React.useState("");
  const [showCatalog, setShowCatalog] = React.useState(false);
  const [provisioningKind, setProvisioningKind] = React.useState("");

  const loadAgents = React.useCallback(async () => {
    try {
      const rows = await apiCached(AGENTS_PATH, { ttlMs: 0 });
      setAgents(Array.isArray(rows) ? rows : []);
      setAgentError("");
    } catch (error) {
      setAgentError(error?.message || (isAr ? "تعذر تحميل الوكلاء" : "Could not load agents"));
    }
  }, [isAr]);

  const loadKinds = React.useCallback(async () => {
    try {
      const rows = await apiCached(AGENT_KINDS_PATH, { ttlMs: 0 });
      setAgentKinds(Array.isArray(rows) ? rows : []);
    } catch {
      // Fallback
    }
  }, []);

  React.useEffect(() => {
    let alive = true;
    const cached = peekCache(AGENTS_PATH);
    if (cached) setAgents(cached);
    apiCached(AGENTS_PATH)
      .then((rows) => alive && setAgents(Array.isArray(rows) ? rows : []))
      .catch((error) => {
        if (!alive) return;
        setAgentError(error?.message || (isAr ? "تعذر تحميل الوكلاء" : "Could not load agents"));
      });

    const cachedKinds = peekCache(AGENT_KINDS_PATH);
    if (cachedKinds) setAgentKinds(cachedKinds);
    apiCached(AGENT_KINDS_PATH)
      .then((rows) => alive && setAgentKinds(Array.isArray(rows) ? rows : []))
      .catch(() => {});

    return () => { alive = false; };
  }, [isAr]);

  const pendingItems = (approvals?.items ?? []).filter((item) => !resolvedApprovals.has(item.id));
  const activeCount = agents == null ? null : agents.filter((agent) => agent.is_active).length;
  const pendingCount = approvals == null || approvals.error ? null : pendingItems.length;
  const tokens = usage?.totals ? (usage.totals.tokens_in ?? 0) + (usage.totals.tokens_out ?? 0) : null;
  const cost = usage?.totals?.cost ?? null;

  async function provisionAgent(kindDef) {
    setProvisioningKind(kindDef.kind);
    setAgentError("");
    try {
      await api(AGENTS_PATH, {
        method: "POST",
        body: {
          kind: kindDef.kind,
          name: kindDef.name,
          model: kindDef.default_model,
          description: kindDef.description,
        },
      });
      invalidateCache(AGENTS_PATH);
      invalidateCache(AGENT_KINDS_PATH);
      await loadAgents();
      await loadKinds();
      setShowCatalog(false);
    } catch (error) {
      setAgentError(error?.message || (isAr ? "تعذر تهيئة الوكيل" : "Could not provision agent"));
    } finally {
      setProvisioningKind("");
    }
  }

  async function toggleAgent(agent) {
    setBusyAgent(agent.id);
    setAgentError("");
    try {
      const updated = await api(`${AGENTS_PATH}/${agent.id}`, {
        method: "PATCH",
        body: { is_active: !agent.is_active },
        headers: { "If-Match": `"${agent.version}"` },
      });
      setAgents((rows) => (rows || []).map((row) => row.id === agent.id ? { ...row, ...updated } : row));
      invalidateCache(AGENTS_PATH);
    } catch (error) {
      setAgentError(error?.message || (isAr ? "تعذر تحديث حالة الوكيل" : "Could not update agent status"));
    } finally {
      setBusyAgent("");
    }
  }

  async function decideApproval(item, decision) {
    setBusyApproval(item.id);
    setApprovalError("");
    try {
      await api(`/ai/approvals/${item.id}/decide`, {
        method: "POST",
        body: { decision },
      });
      invalidateCache(APPROVALS_PATH);
      setResolvedApprovals((current) => new Set(current).add(item.id));
    } catch (error) {
      setApprovalError(error?.message || (isAr ? "تعذر حفظ القرار" : "Could not save the decision"));
    } finally {
      setBusyApproval("");
    }
  }

  // Set of kinds already provisioned for this tenant
  const provisionedKinds = new Set((agents || []).map((a) => a.kind));

  return (
    <div>
      <PageHeader
        title={t("ai.title")}
        subtitle={t("ai.subtitle")}
        actions={
          <button
            type="button"
            onClick={() => setShowCatalog(!showCatalog)}
            className="h-9 px-3.5 rounded-lg bg-primary text-primary-foreground text-[13px] font-medium flex items-center gap-1.5 shadow-sm hover:opacity-90 transition-opacity"
          >
            <Layers className="h-4 w-4" /> {isAr ? "كتالوج الوكلاء" : "Agent Catalog"}
          </button>
        }
      />

      {live?.dashboardError && (
        <div role="alert" className="mb-4 flex items-center justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          <span>{live.dashboardError}</span>
          <button type="button" onClick={live.retryDashboard} className="shrink-0 underline">{t("common.retry", "Retry")}</button>
        </div>
      )}
      {usage?.error && (
        <div role="status" className="mb-4 flex items-center justify-between gap-3 text-[11.5px] text-muted-foreground">
          <span>{usage.error}</span>
          <button type="button" onClick={usage.retry} className="shrink-0 text-primary hover:underline">{t("common.retry", "Retry")}</button>
        </div>
      )}

      {/* Stats bar */}
      <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-3.5 mb-5">
        <Stat icon={Repeat} label={t("ai.stat.conversations")} value={live?.openConversations == null ? "—" : live.openConversations.toLocaleString()} tone="accent" />
        <Stat icon={Sparkles} label={t("ai.stat.tokens")} value={tokens == null ? "—" : tokens.toLocaleString()} tone="primary" />
        <Stat icon={ShieldCheck} label={t("ai.stat.pendingApprovals")} value={pendingCount == null ? "—" : `${pendingCount.toLocaleString()}${approvals?.truncated ? "+" : ""}`} tone="warning" />
        <Stat icon={Users} label={t("ai.stat.activeAgents")} value={activeCount == null ? "—" : activeCount.toLocaleString()} tone="accent" />
        <Stat icon={ListChecks} label={t("ai.usage.spend")} value={cost == null ? "—" : formatCurrency(Number(cost), true, "USD")} tone="primary" />
        <Stat icon={ShoppingBag} label={t("ai.stat.orders")} value={live?.aiOrders == null ? "—" : live.aiOrders.toLocaleString()} tone="muted" />
      </div>

      {/* Agent Catalog Drawer / Modal */}
      {showCatalog && (
        <div className="mb-6 rounded-2xl border border-primary/20 bg-primary/5 p-5 shadow-sm transition-all">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-[16px] font-bold flex items-center gap-2">
                <Layers className="h-5 w-5 text-primary" />
                {isAr ? "كتالوج الوكلاء المتاحين في المنصة" : "Platform Agent Catalog"}
              </h2>
              <p className="text-[12px] text-muted-foreground mt-0.5">
                {isAr
                  ? "تعريفات الوكلاء الرسمية المسجلة في الـ Agent Registry. يتم تزويد كل وكيل تلقائيًا بحزمة أدواته وحدوده الأمنية."
                  : "Standard agent definitions registered in the Agent Registry. Each agent is provisioned with its verified toolset."}
              </p>
            </div>
            <button
              type="button"
              onClick={() => setShowCatalog(false)}
              className="h-8 w-8 grid place-items-center rounded-lg hover:bg-surface text-muted-foreground"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <div className="grid sm:grid-cols-2 gap-4">
            {(agentKinds || []).map((kindDef) => {
              const isProvisioned = provisionedKinds.has(kindDef.kind);
              const isBusy = provisioningKind === kindDef.kind;

              return (
                <div
                  key={kindDef.kind}
                  className="rounded-xl border border-border bg-card p-4 flex flex-col justify-between hover:border-primary/40 transition-colors"
                >
                  <div>
                    <div className="flex items-center justify-between gap-2 mb-2">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-[15px]">{kindDef.name}</span>
                        <span className="text-[10px] font-mono bg-surface px-1.5 py-0.5 rounded border border-border">
                          {kindDef.kind}
                        </span>
                      </div>
                      <Badge tone={isProvisioned ? "success" : "muted"}>
                        {isProvisioned
                          ? (isAr ? "تم التجهيز" : "Provisioned")
                          : (isAr ? "متاح" : "Available")}
                      </Badge>
                    </div>

                    <p className="text-[12px] text-muted-foreground mb-3 leading-relaxed">
                      {kindDef.description || (isAr ? "لا يوجد وصف متوفر" : "No description")}
                    </p>

                    <div className="flex flex-wrap gap-1.5 mb-3">
                      <span className="inline-flex items-center gap-1 text-[11px] font-medium bg-surface text-foreground px-2 py-0.5 rounded-md border border-border">
                        <Cpu className="h-3 w-3 text-muted-foreground" />
                        {kindDef.default_model}
                      </span>
                      <span className="inline-flex items-center gap-1 text-[11px] font-medium bg-surface text-foreground px-2 py-0.5 rounded-md border border-border">
                        <Wrench className="h-3 w-3 text-muted-foreground" />
                        {kindDef.allowed_tools?.length || 0} {isAr ? "أدوات مصرح بها" : "tools"}
                      </span>
                      {kindDef.definition_version && (
                        <span className="text-[10px] font-mono text-muted-foreground bg-surface px-1.5 py-0.5 rounded border border-border">
                          v{kindDef.definition_version}
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="pt-2 border-t border-border flex items-center justify-between">
                    <span className="text-[11px] text-muted-foreground">
                      {kindDef.guardrail_profile ? `Guardrail: ${kindDef.guardrail_profile}` : ""}
                    </span>
                    {isProvisioned ? (
                      <span className="inline-flex items-center gap-1 text-[12px] font-medium text-success">
                        <CheckCircle2 className="h-4 w-4" /> {isAr ? "جاهز للاستخدام" : "Active & Ready"}
                      </span>
                    ) : (
                      <button
                        type="button"
                        disabled={isBusy}
                        onClick={() => provisionAgent(kindDef)}
                        className="h-8 px-3 rounded-lg bg-primary text-primary-foreground text-[12px] font-medium flex items-center gap-1.5 hover:opacity-90 disabled:opacity-50"
                      >
                        <Plus className="h-3.5 w-3.5" />
                        {isBusy ? "…" : (isAr ? "تهيئة الوكيل" : "Provision Agent")}
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Main sections */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <SectionCard title={t("ai.agents.title")} className="lg:col-span-2" bodyClassName="pt-1">
          {agentError && (
            <div role="alert" className="mb-3 rounded-lg bg-destructive/10 px-3 py-2 text-[12px] text-destructive">
              {agentError}
            </div>
          )}
          <div className="space-y-3">
            {agents === null ? (
              <div className="py-8 text-center text-[13px] text-muted-foreground">
                {agentError ? (
                  <>
                    <span>{isAr ? "تعذر تحميل الوكلاء." : "Agents could not be loaded."}</span>
                    <button type="button" onClick={() => void loadAgents()} className="ml-3 text-primary hover:underline">
                      {isAr ? "إعادة المحاولة" : "Retry"}
                    </button>
                  </>
                ) : (
                  isAr ? "جارٍ تحميل الوكلاء…" : "Loading agents…"
                )}
              </div>
            ) : agents.length === 0 ? (
              <div className="py-8 text-center text-[13px] text-muted-foreground">
                {isAr ? "لا توجد وكلاء بعد. افتح كتالوج الوكلاء لتجهيز الوكلاء المطلوبين." : "No agents yet. Open the Agent Catalog to provision."}
              </div>
            ) : (
              agents.map((agent) => (
                <div key={agent.id} className="flex items-center gap-3.5 p-3.5 rounded-xl border border-border hover:bg-surface/50 transition-colors">
                  <span className="h-10 w-10 shrink-0 rounded-xl bg-accent/10 text-accent grid place-items-center">
                    <Sparkles className="h-5 w-5" />
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-[14px] font-semibold truncate">{agent.name}</span>
                      {agent.kind && (
                        <span className="text-[10px] font-mono text-muted-foreground bg-surface px-1.5 py-0.5 rounded-md border border-border">
                          {agent.kind}
                        </span>
                      )}
                      <Badge tone={agent.is_active ? "success" : "muted"}>
                        <span className={`h-1.5 w-1.5 rounded-full ${agent.is_active ? "bg-success" : "bg-muted-foreground"}`} />
                        {agent.is_active ? t("ai.agents.active") : (isAr ? "متوقف" : "Inactive")}
                      </Badge>
                    </div>
                    <div className="text-[12px] text-muted-foreground mt-0.5 truncate">
                      {agent.description || agent.model || (isAr ? "لا يوجد وصف" : "No description")}
                    </div>
                  </div>
                  <button
                    type="button"
                    aria-label={agent.is_active ? (isAr ? "إيقاف الوكيل" : "Deactivate agent") : (isAr ? "تفعيل الوكيل" : "Activate agent")}
                    title={agent.is_active ? (isAr ? "إيقاف الوكيل" : "Deactivate agent") : (isAr ? "تفعيل الوكيل" : "Activate agent")}
                    disabled={busyAgent === agent.id}
                    onClick={() => toggleAgent(agent)}
                    className="h-8 w-8 grid place-items-center rounded-lg hover:bg-surface text-muted-foreground disabled:opacity-50"
                  >
                    <Power className="h-4 w-4" />
                  </button>
                </div>
              ))
            )}
          </div>
        </SectionCard>

        <SectionCard title={t("ai.approvals.title")} action={t("common.viewAll")} actionTo="/inbox">
          <div className="rounded-xl border border-warning/30 bg-warning/10 p-4">
            <div className="flex items-center gap-2 text-warning font-medium text-[13px]">
              <ShieldCheck className="h-4 w-4" />
              {t("ai.approvals.waiting", { n: pendingCount == null ? "—" : approvals?.truncated ? `${pendingCount}+` : pendingCount })}
            </div>
            <p className="text-[12px] text-muted-foreground mt-1.5 leading-relaxed">{t("ai.approvals.body")}</p>
            {approvalError && <div role="alert" className="mt-2 text-[11px] text-destructive">{approvalError}</div>}
            {approvals?.error && (
              <div role="alert" className="mt-2 flex items-center justify-between gap-2 text-[11px] text-destructive">
                <span>{approvals.error}</span>
                <button type="button" onClick={approvals.retry} className="shrink-0 underline">{t("common.retry", "Retry")}</button>
              </div>
            )}
            {approvals == null ? (
              <div role="status" className="mt-3 text-[12px] text-muted-foreground">{t("common.loading", "Loading…")}</div>
            ) : approvals.error ? null : pendingItems.length === 0 ? (
              <div className="mt-3 text-[12px] text-muted-foreground">{isAr ? "لا توجد موافقات معلّقة." : "There are no pending approvals."}</div>
            ) : (
              <div className="mt-3 space-y-2">
                {pendingItems.slice(0, 5).map((item) => (
                  <div key={item.id} className="rounded-lg border border-warning/20 bg-background/70 p-2.5">
                    <div className="text-[12px] font-medium truncate">{item.action}</div>
                    <div className="text-[10.5px] text-muted-foreground mt-0.5">{item.risk_level} · {item.entity_type}</div>
                    <div className="mt-2 flex gap-2">
                      <button type="button" disabled={busyApproval === item.id} onClick={() => decideApproval(item, "APPROVED")} className="inline-flex items-center gap-1 rounded-md bg-success/10 px-2 py-1 text-[11px] text-success disabled:opacity-50"><Check className="h-3 w-3" />{isAr ? "موافقة" : "Approve"}</button>
                      <button type="button" disabled={busyApproval === item.id} onClick={() => decideApproval(item, "REJECTED")} className="inline-flex items-center gap-1 rounded-md bg-destructive/10 px-2 py-1 text-[11px] text-destructive disabled:opacity-50"><X className="h-3 w-3" />{isAr ? "رفض" : "Reject"}</button>
                    </div>
                  </div>
                ))}
                {pendingItems.length > 5 && (
                  <button type="button" onClick={() => navigate("/inbox")} className="w-full text-center text-[11px] text-primary hover:underline">{isAr ? "عرض بقية الموافقات" : "View remaining approvals"}</button>
                )}
              </div>
            )}
          </div>
        </SectionCard>
      </div>

      <div className="mt-5">
        <SectionCard title={t("ai.usage.title")} bodyClassName="pt-3">
          <div className="grid sm:grid-cols-2 gap-5">
            <div className="flex items-center gap-3.5">
              <span className="h-11 w-11 rounded-xl bg-accent/10 text-accent grid place-items-center text-[13px] font-bold tabular-nums" dir="ltr">{tokens == null ? "—" : tokens >= 1000 ? `${(tokens / 1000).toFixed(1)}K` : tokens}</span>
              <div><div className="text-[13px] font-medium">{t("ai.stat.tokens")}</div><div className="text-[12px] text-muted-foreground">{t("ai.usage.thisCycle")}</div></div>
            </div>
            <div className="flex items-center gap-3.5">
              <span className="h-11 w-11 rounded-xl bg-warning/15 text-warning grid place-items-center font-display text-[15px] font-bold">{cost == null ? "—" : formatCurrency(Number(cost), false, "USD")}</span>
              <div><div className="text-[13px] font-medium">{t("ai.usage.spend")}</div><div className="text-[12px] text-muted-foreground">{t("ai.usage.thisCycle")}</div></div>
            </div>
          </div>
        </SectionCard>
      </div>
    </div>
  );
}
