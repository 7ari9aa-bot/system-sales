/** مساعد المبيعات — محادثة تحليلية مستمرة مع وكيل sales_intelligence.
 *  كل سؤال = تحليل كامل بأدوات حقيقية (مفيش أرقام من محتوى النموذج)؛
 *  الرد بيرجع بلوكات مغلقة الخادم-البناء. بيانات الحوار محفوظة على السيرفر. */

import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { PageHeader } from "@/components/dashboard/ui";
import Composer from "@/components/salesAssistant/Composer";
import MessageList from "@/components/salesAssistant/MessageList";
import ThreadListPanel from "@/components/salesAssistant/ThreadListPanel";
import { api } from "@/lib/api";
import { useI18n, useT } from "@/lib/i18n";

/** مفاتيح الكاش دقيقة عشان الإبطال يستهدف مفتاح واحد — لا prefix invalidation
 *  (الدرس: صفحة اتحطّت لأن invalidate لاحق مفاتيح ماينتميش ليها). */
const threadsKey = (params) => ["sales-chat", "threads", params ?? {}];
const messagesKey = (id) => ["sales-chat", "thread", id, "messages"];

const EXAMPLES_AR = [
  "قارن مبيعات الشهر ده باللي فات.",
  "أفضل المنتجات المبيع الشهر ده؟",
  "إيه أداء القنوات؟",
  "المرتجعات عملت إيه؟",
  "أداء الشحن والفروع",
  "المنتجات اللي مخزونها هيخلص",
];
const EXAMPLES_EN = [
  "Compare this month's sales to last month.",
  "Best selling products this month?",
  "How are the channels performing?",
  "What about the returns?",
  "Shipping and branches performance",
  "Products about to run out of stock",
];

export default function SalesAssistant() {
  const t = useT();
  const { lang } = useI18n();
  const isAr = lang === "ar";
  const queryClient = useQueryClient();
  const [activeId, setActiveId] = React.useState(null);
  const [search, setSearch] = React.useState("");
  const [includeArchived, setIncludeArchived] = React.useState(false);
  const [drafts, setDrafts] = React.useState({});
  const [panelOpen, setPanelOpen] = React.useState(false);

  const threadsQuery = useQuery({
    queryKey: threadsKey({ search, includeArchived }),
    queryFn: () => {
      const params = new URLSearchParams();
      if (search.trim()) params.set("search", search.trim());
      if (includeArchived) params.set("include_archived", "true");
      const qs = params.toString();
      return api(`/ai/sales-chat/threads${qs ? `?${qs}` : ""}`);
    },
  });

  const messagesQuery = useQuery({
    queryKey: messagesKey(activeId),
    enabled: !!activeId,
    queryFn: () => api(`/ai/sales-chat/threads/${activeId}/messages?limit=100`),
  });

  const invalidateThread = (id) => {
    queryClient.invalidateQueries({ queryKey: messagesKey(id), exact: true });
    queryClient.invalidateQueries({ queryKey: ["sales-chat", "threads"], exact: false });
  };

  const createThread = useMutation({
    mutationFn: (payload) => api("/ai/sales-chat/threads", { method: "POST", body: payload }),
    onSuccess: (thread) => {
      queryClient.invalidateQueries({ queryKey: ["sales-chat", "threads"], exact: false });
      setActiveId(thread.id);
      setPanelOpen(false);
    },
  });

  const sendTurn = useMutation({
    mutationFn: ({ id, content, idempotency_key }) =>
      api(`/ai/sales-chat/threads/${id}/messages`, {
        method: "POST",
        body: { content, idempotency_key },
      }),
    onSuccess: (_data, vars) => invalidateThread(vars.id),
    onError: (_err, vars) => invalidateThread(vars.id),
  });

  const updateThread = useMutation({
    mutationFn: ({ id, ...body }) =>
      api(`/ai/sales-chat/threads/${id}`, { method: "PATCH", body }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["sales-chat", "threads"], exact: false }),
  });

  const deleteThread = useMutation({
    mutationFn: ({ id }) => api(`/ai/sales-chat/threads/${id}`, { method: "DELETE" }),
    onSuccess: (_data, vars) => {
      queryClient.invalidateQueries({ queryKey: ["sales-chat", "threads"], exact: false });
      if (vars.id === activeId) setActiveId(null);
    },
  });

  const retryTurn = useMutation({
    mutationFn: ({ threadId, messageId }) =>
      api(`/ai/sales-chat/threads/${threadId}/messages/${messageId}/retry`, { method: "POST" }),
    onSuccess: (_data, vars) => invalidateThread(vars.threadId),
    onError: (_err, vars) => invalidateThread(vars.threadId),
  });

  const threads = threadsQuery.data ?? [];
  const activeThread = threads.find((th) => th.id === activeId) ?? null;
  const messages = messagesQuery.data ?? [];
  const sending = sendTurn.isPending;
  const examples = isAr ? EXAMPLES_AR : EXAMPLES_EN;

  const send = (content) => {
    let id = activeId;
    setDrafts((d) => ({ ...d, [id ?? "new"]: "" }));
    const key = (id ?? "new") + ":" + Date.now();
    if (!id) {
      createThread.mutate({}, {
        onSuccess: (thread) => {
          setActiveId(thread.id);
          sendTurn.mutate({ id: thread.id, content, idempotency_key: key });
          setDrafts((d) => ({ ...d, [thread.id]: "" }));
        },
      });
      return;
    }
    sendTurn.mutate({ id, content, idempotency_key: key });
  };

  const draft = drafts[activeId ?? "new"] ?? "";

  return (
    <div className="min-h-0 flex-1 space-y-4">
      <PageHeader
        title={t("nav.salesAssistant")}
        subtitle={t("salesAssistant.subtitle")}
        actions={
          <button
            type="button"
            onClick={() => setPanelOpen((v) => !v)}
            className="inline-flex items-center gap-1.5 rounded-xl border border-border px-2.5 py-1.5 text-[12.5px] lg:hidden"
          >
            {panelOpen ? <PanelLeftClose className="h-4 w-4" /> : <PanelLeftOpen className="h-4 w-4" />}
            {t("salesAssistant.threads")}
          </button>
        }
      />

      <div className="grid min-h-[65vh] gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">
        {/* لوحة المحادثات — drawer على الموبايل */}
        <aside
          className={
            panelOpen
              ? "rounded-2xl border border-border bg-card lg:sticky lg:top-4 lg:max-h-[calc(100vh-7rem)]"
              : "hidden lg:block lg:sticky lg:top-4 lg:max-h-[calc(100vh-7rem)] rounded-2xl border border-border bg-card"
          }
        >
          <ThreadListPanel
            threads={threads}
            activeId={activeId}
            onSelect={(th) => {
              setActiveId(th.id);
              setPanelOpen(false);
            }}
            onNew={() => {
              setActiveId(null);
              setPanelOpen(false);
            }}
            onRename={(th, title) => updateThread.mutate({ id: th.id, title })}
            onArchive={(th) => updateThread.mutate({ id: th.id, status: "archived" })}
            onRestore={(th) => updateThread.mutate({ id: th.id, status: "active" })}
            onDelete={(th) => deleteThread.mutate({ id: th.id })}
            search={search}
            onSearchChange={setSearch}
          />
          <label className="flex items-center gap-2 border-t border-border px-4 py-2.5 text-[12px] text-muted-foreground">
            <input
              type="checkbox"
              checked={includeArchived}
              onChange={(e) => setIncludeArchived(e.target.checked)}
              className="accent-[var(--primary)]"
            />
            {t("salesAssistant.showArchived")}
          </label>
        </aside>

        {/* مساحة المحادثة */}
        <section className="flex min-h-[60vh] min-w-0 flex-col rounded-2xl border border-border bg-card">
          {activeThread && activeThread.title ? (
            <div className="border-b border-border px-4 py-3">
              <h2 className="truncate text-[14px] font-semibold">{activeThread.title}</h2>
            </div>
          ) : null}

          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            {!activeId ? (
              <div className="flex h-full flex-col items-center justify-center gap-4 py-10 text-center">
                <p className="text-[14px] font-medium">{t("salesAssistant.emptyTitle")}</p>
                <p className="max-w-md text-[12.5px] text-muted-foreground">{t("salesAssistant.emptyHint")}</p>
                <div className="grid w-full max-w-xl gap-2 sm:grid-cols-2">
                  {examples.map((ex) => (
                    <button
                      key={ex}
                      type="button"
                      onClick={() => send(ex)}
                      disabled={sending || createThread.isPending}
                      className="rounded-xl border border-border bg-card px-3 py-2.5 text-start text-[12.5px] hover:bg-surface transition-colors disabled:opacity-50"
                    >
                      {ex}
                    </button>
                  ))}
                </div>
              </div>
            ) : messagesQuery.isLoading ? (
              <p className="py-10 text-center text-[12.5px] text-muted-foreground">
                {t("salesAssistant.loading")}
              </p>
            ) : (
              <MessageList
                messages={messages}
                pending={sending}
                onRetry={(m) => retryTurn.mutate({ threadId: activeId, messageId: m.id })}
              />
            )}
          </div>

          <Composer
            value={draft}
            onChange={(v) => setDrafts((d) => ({ ...d, [activeId ?? "new"]: v }))}
            onSend={send}
            disabled={sending || createThread.isPending}
          />
        </section>
      </div>
    </div>
  );
}
