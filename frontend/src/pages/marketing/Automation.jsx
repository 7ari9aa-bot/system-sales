import React from "react";
import { Plus, Zap, MessageSquare, Play, Pause, Archive } from "lucide-react";
import { Badge } from "@/components/dashboard/ui";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { useI18n, useT } from "@/lib/i18n";

const WORKFLOWS_PATH = "/workflows";

export default function Automation() {
  const t = useT();
  const { lang } = useI18n();
  const isAr = lang === "ar";
  const [workflows, setWorkflows] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [formOpen, setFormOpen] = React.useState(false);
  const [name, setName] = React.useState("");
  const [triggerEvent, setTriggerEvent] = React.useState("order.created");
  const [message, setMessage] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const [busyId, setBusyId] = React.useState("");
  const [error, setError] = React.useState("");

  const loadWorkflows = React.useCallback(async () => {
    setLoading(true);
    try {
      const rows = await api(WORKFLOWS_PATH);
      setWorkflows(Array.isArray(rows) ? rows : []);
      setError("");
    } catch (err) {
      setError(err?.message || (isAr ? "تعذر تحميل مسارات الأتمتة" : "Could not load workflows"));
    } finally {
      setLoading(false);
    }
  }, [isAr]);

  React.useEffect(() => { void loadWorkflows(); }, [loadWorkflows]);

  async function createWorkflow(event) {
    event.preventDefault();
    if (!name.trim() || !triggerEvent.trim() || !message.trim()) return;
    setSaving(true);
    setError("");
    try {
      await api(WORKFLOWS_PATH, {
        method: "POST",
        body: {
          name: name.trim(),
          trigger_event: triggerEvent.trim(),
          description: isAr ? "إشعار داخلي عند وقوع الحدث المحدد." : "Send an in-app notification when the selected event occurs.",
          definition: { steps: [{ action: "notify", subject: name.trim(), message: message.trim() }] },
        },
      });
      setName("");
      setTriggerEvent("order.created");
      setMessage("");
      setFormOpen(false);
      await loadWorkflows();
    } catch (err) {
      setError(err?.message || (isAr ? "تعذر إنشاء مسار الأتمتة" : "Could not create workflow"));
    } finally {
      setSaving(false);
    }
  }

  async function changeStatus(workflow, status) {
    if (status === "archived") {
      const confirmed = window.confirm(isAr ? `أرشفة مسار «${workflow.name}» نهائيًا؟` : `Archive “${workflow.name}” permanently?`);
      if (!confirmed) return;
    }
    setBusyId(workflow.id);
    setError("");
    try {
      const updated = await api(`${WORKFLOWS_PATH}/${workflow.id}/status`, {
        method: "PATCH",
        body: { status },
        headers: { "If-Match": `"${workflow.version}"` },
      });
      setWorkflows((rows) => (rows || []).map((row) => row.id === workflow.id ? updated : row));
    } catch (err) {
      const message = err?.message || (isAr ? "تعذر تحديث حالة المسار" : "Could not update workflow status");
      await loadWorkflows();
      setError(message);
    } finally {
      setBusyId("");
    }
  }

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-[13px] text-muted-foreground">{t("marketing.automation.subtitle")}</p>
          <p className="mt-1 text-[11.5px] text-muted-foreground">{isAr ? "التنشيط يجعل المسار يستجيب للأحداث تلقائيًا." : "Activating a workflow lets it respond to matching events automatically."}</p>
        </div>
        <Button type="button" onClick={() => setFormOpen((open) => !open)} className="gap-1.5"><Plus className="h-4 w-4" />{t("marketing.automation.new")}</Button>
      </div>

      {error && <div role="alert" className="mb-3 rounded-lg border border-destructive/20 bg-destructive/10 px-3 py-2 text-[12px] text-destructive">{error}</div>}

      {formOpen && (
        <form onSubmit={createWorkflow} className="mb-4 grid gap-3 rounded-2xl border border-border bg-card p-4 sm:grid-cols-2">
          <label className="grid gap-1.5 text-[12px] text-muted-foreground">{isAr ? "اسم المسار" : "Workflow name"}<Input required maxLength={255} value={name} onChange={(event) => setName(event.target.value)} /></label>
          <label className="grid gap-1.5 text-[12px] text-muted-foreground">
            {isAr ? "اسم الحدث المشغّل" : "Trigger event name"}
            <Input required maxLength={127} value={triggerEvent} onChange={(event) => setTriggerEvent(event.target.value)} />
          </label>
          <label className="grid gap-1.5 text-[12px] text-muted-foreground sm:col-span-2">
            {isAr ? "رسالة الإشعار الداخلي" : "In-app notification message"}
            <Input required value={message} onChange={(event) => setMessage(event.target.value)} />
          </label>
          <p className="text-[11px] leading-relaxed text-muted-foreground sm:col-span-2">
            {isAr ? "يُنشأ المسار كمسودة بخطوة إشعار داخل التطبيق. استخدم اسم حدث يرسله النظام، مثل order.created؛ لا تنشّطه قبل مراجعة القواعد." : "The workflow is created as a draft with one in-app notification step. Use an event emitted by the system, such as order.created; review before activating it."}
          </p>
          <div className="flex gap-2 sm:col-span-2">
            <Button type="submit" disabled={saving || !name.trim() || !message.trim()}>{saving ? "…" : (isAr ? "إنشاء مسودة" : "Create draft")}</Button>
            <Button type="button" variant="outline" onClick={() => setFormOpen(false)}>{t("ls.cancel")}</Button>
          </div>
        </form>
      )}

      {loading && workflows == null ? (
        <div className="rounded-2xl border border-border bg-card py-10 text-center text-[13px] text-muted-foreground">{isAr ? "جارٍ تحميل مسارات الأتمتة…" : "Loading workflows…"}</div>
      ) : workflows == null && error ? (
        <div className="rounded-2xl border border-border bg-card py-8 text-center text-[13px] text-muted-foreground">
          <p>{isAr ? "تعذر تحميل مسارات الأتمتة." : "Workflows could not be loaded."}</p>
          <Button type="button" variant="outline" onClick={() => void loadWorkflows()} className="mt-3">{isAr ? "إعادة المحاولة" : "Retry"}</Button>
        </div>
      ) : workflows != null && workflows.length === 0 ? (
        <div className="rounded-2xl border border-border bg-card py-10 text-center text-[13px] text-muted-foreground">{isAr ? "لا توجد مسارات أتمتة محفوظة." : "No saved workflows."}</div>
      ) : (
        <div className="space-y-3">
          {workflows.map((workflow) => {
            const status = workflow.status || "draft";
            const statusLabel = status === "draft" ? (isAr ? "مسودة" : "Draft") : status === "archived" ? (isAr ? "مؤرشف" : "Archived") : t(`marketing.automation.${status}`);
            const target = status === "active" ? "paused" : "active";
            return (
              <div key={workflow.id} className="rounded-2xl border border-border bg-card p-4">
                <div className="flex flex-wrap items-center gap-3">
                  <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-accent/10 text-accent"><Zap className="h-5 w-5" /></span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="truncate text-[14px] font-semibold">{workflow.name}</span>
                      <Badge tone={status === "active" ? "success" : status === "paused" ? "warning" : "muted"}>{statusLabel}</Badge>
                    </div>
                    <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[12px] text-muted-foreground">
                      <span>{isAr ? "عند الحدث" : "On event"}: <code dir="ltr">{workflow.trigger_event}</code></span>
                      <span aria-hidden="true">·</span>
                      <span>{isAr ? "الإصدار" : "Version"} {workflow.current_version}</span>
                    </div>
                  </div>
                  {status !== "archived" && (
                    <div className="flex gap-1">
                      <Button type="button" variant={status === "active" ? "outline" : "default"} size="sm" disabled={busyId === workflow.id} onClick={() => changeStatus(workflow, target)} className="gap-1.5">
                        {status === "active" ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
                        {status === "active" ? t("marketing.automation.paused") : (isAr ? "تفعيل" : "Activate")}
                      </Button>
                      <Button type="button" variant="ghost" size="icon" disabled={busyId === workflow.id} onClick={() => changeStatus(workflow, "archived")} aria-label={isAr ? "أرشفة المسار" : "Archive workflow"} title={isAr ? "أرشفة" : "Archive"}><Archive className="h-4 w-4" /></Button>
                    </div>
                  )}
                </div>
                {workflow.description && <p className="mt-3 border-t border-border pt-3 text-[11.5px] text-muted-foreground">{workflow.description}</p>}
                <div className="mt-3 flex items-center gap-2 border-t border-border pt-3 text-[11.5px] text-muted-foreground">
                  <MessageSquare className="h-3.5 w-3.5" />{isAr ? "خطوات الإشعار محفوظة في الإصدار الحالي." : "The notification step is stored in the current workflow version."}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
