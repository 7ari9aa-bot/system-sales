/** مساعد المبيعات — محادثة تحليلية مستمرة مع وكيل sales_intelligence.
 *  كل سؤال = تحليل كامل بأدوات حقيقية (مفيش أرقام من محتوى النموذج)؛
 *  الرد بيرجع بلوكات مغلقة الخادم-البناء. بيانات الحوار محفوظة على السيرفر.
 *  الواجهة بنفس لغة الداشبورد: كروت كاملة الحواف، أفاتار FIHRIST، وحالة
 *  فراغ hero بدل شاشة فاضية. */

import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BarChart3, MessageSquareText, PanelLeftClose, ShieldCheck, Sparkles, X } from "lucide-react";
import { PageHeader } from "@/components/dashboard/ui";
import Logo from "@/components/dashboard/Logo";
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

const EXAMPLE_ICONS = [BarChart3, Sparkles, MessageSquareText, Sparkles, BarChart3, BarChart3];

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
  const scrollRef = React.useRef(null);

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

  // hold the scroll at the newest turn whenever the thread grows
  React.useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length, sending, activeId]);

  const send = (content) => {
    setDrafts((d) => ({ ...d, [activeId ?? "new"]: "" }));
    const key = `${activeId ?? "new"}:${Date.now()}`;
    if (!activeId) {
      createThread.mutate({}, {
        onSuccess: (thread) => {
          setActiveId(thread.id);
          sendTurn.mutate({ id: thread.id, content, idempotency_key: key });
        },
      });
      return;
    }
    sendTurn.mutate({ id: activeId, content, idempotency_key: key });
  };

  const draft = drafts[activeId ?? "new"] ?? "";
  const chatSurface = (
    <section className="flex min-h-[60vh] min-w-0 flex-1 flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-sm">
      {activeThread && activeThread.title ? (
        <div className="flex items-center gap-2.5 border-b border-border px-4 py-3">
          <Logo size={24} />
          <h2 className="min-w-0 truncate text-[14px] font-semibold">{activeThread.title}</h2>
        </div>
      ) : null}

      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto p-4">
        {!activeId ? (
          <div className="flex h-full flex-col items-center justify-center gap-5 py-12 text-center animate-fade-in">
            <span className="grid h-14 w-14 place-items-center rounded-2xl bg-primary/10 text-primary shadow-sm">
              <Logo size={38} />
            </span>
            <div className="space-y-1.5">
              <p className="font-display text-[19px] font-semibold">
                {t("salesAssistant.emptyTitle")}
              </p>
              <p className="mx-auto max-w-md text-[13px] leading-6 text-muted-foreground">
                {t("salesAssistant.emptyHint")}
              </p>
            </div>
            <div className="grid w-full max-w-2xl gap-2 sm:grid-cols-2">
              {examples.map((ex, i) => {
                const Icon = EXAMPLE_ICONS[i % EXAMPLE_ICONS.length];
                return (
                  <button
                    key={ex}
                    type="button"
                    onClick={() => send(ex)}
                    disabled={sending || createThread.isPending}
                    className="group flex items-center gap-2.5 rounded-2xl border border-border bg-card px-3.5 py-3 text-start text-[12.5px] font-medium shadow-sm hover:border-primary/35 hover:bg-surface active:scale-[0.99] transition-all disabled:opacity-50"
                  >
                    <span className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-surface text-primary group-hover:bg-primary/10 transition-colors">
                      <Icon className="h-4 w-4" />
                    </span>
                    <span className="min-w-0">{ex}</span>
                  </button>
                );
              })}
            </div>
            <p className="flex items-center gap-1.5 text-[11px] text-muted-foreground/80">
              <ShieldCheck className="h-3.5 w-3.5" />
              {t("salesAssistant.groundingNote")}
            </p>
          </div>
        ) : messagesQuery.isLoading ? (
          <p className="py-12 text-center text-[12.5px] text-muted-foreground">
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
  );

  const sidebarBody = (
    <>
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
      <label className="flex cursor-pointer items-center gap-2 border-t border-border px-4 py-2.5 text-[12px] text-muted-foreground select-none">
        <input
          type="checkbox"
          checked={includeArchived}
          onChange={(e) => setIncludeArchived(e.target.checked)}
          className="accent-[hsl(var(--primary))]"
        />
        {t("salesAssistant.showArchived")}
      </label>
    </>
  );

  return (
    <div className="min-h-0 flex-1 space-y-4">
      <PageHeader
        title={t("nav.salesAssistant")}
        subtitle={t("salesAssistant.subtitle")}
        actions={
          <button
            type="button"
            onClick={() => setPanelOpen((v) => !v)}
            className="inline-flex items-center gap-1.5 rounded-xl border border-border bg-card px-2.5 py-1.5 text-[12.5px] font-medium shadow-sm lg:hidden"
          >
            {panelOpen ? <PanelLeftClose className="h-4 w-4" /> : <MessageSquareText className="h-4 w-4" />}
            {t("salesAssistant.threads")}
          </button>
        }
      />

      <div className="flex min-h-[68vh] gap-4">
        {/* لوحة المحادثات — ثابتة على الشاشات الكبيرة، drawer فوق خلفية على الموبايل */}
        <aside className="hidden w-[300px] shrink-0 flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-sm lg:sticky lg:top-4 lg:flex lg:max-h-[calc(100vh-7rem)]">
          {sidebarBody}
        </aside>

        {panelOpen && (
          <div className="fixed inset-0 z-50 flex lg:hidden">
            <div
              className="absolute inset-0 bg-black/45 backdrop-blur-[2px]"
              onClick={() => setPanelOpen(false)}
              aria-hidden
            />
            <div className="relative ml-auto flex h-full w-[86%] max-w-[340px] flex-col bg-card shadow-2xl animate-fade-in">
              <div className="flex items-center justify-between border-b border-border px-3 py-2.5">
                <span className="text-[13px] font-semibold">{t("salesAssistant.threads")}</span>
                <button
                  type="button"
                  onClick={() => setPanelOpen(false)}
                  className="rounded-lg p-1.5 text-muted-foreground hover:bg-surface"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
              {sidebarBody}
            </div>
          </div>
        )}

        {chatSurface}
      </div>
    </div>
  );
}
