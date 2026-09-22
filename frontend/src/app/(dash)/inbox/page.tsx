"use client";

import * as React from "react";
import {
  MessagesSquare,
  MessageCircleOff,
  Send,
  UserCheck,
  UserPlus,
  UserRoundX,
  Users,
  Search,
  Check,
  CheckCheck,
  Clock,
  AlertCircle,
  PanelRightClose,
  PanelRightOpen,
} from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  useConversations,
  useAssignConversation,
  useMarkConversationRead,
  useMe,
  useMessages,
  useSendMessage,
  useSlaRisk,
  INBOX_VIEW_IDS,
  INBOX_VIEW_STATUS,
  INBOX_CLIENT_VIEWS,
  isInboxViewId,
  qk,
  type Conversation,
  type InboxViewId,
  type Page,
} from "@/lib/queries";
import type { InfiniteData } from "@tanstack/react-query";
import { useQueryClient } from "@tanstack/react-query";
import { useRealtimeEvents, type RealtimeEvent } from "@/lib/use-realtime";
import { t } from "@/lib/t";
import { formatTime } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui/states";
import { CustomerDrawer } from "@/components/customer-drawer";
import { InboxContextPanel } from "@/components/inbox-context-panel";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

const CHANNEL_VARIANT: Record<string, "success" | "primary" | "default"> = {
  whatsapp: "success",
  telegram: "primary",
  webchat: "default",
};

const CHANNELS = ["all", "whatsapp", "telegram", "webchat"] as const;

/** §99 — views wired end-to-end: server-backed (status param) plus the
 *  client-filtered ones. Everything else renders disabled (قريبًا) — never
 *  faked. */
const SUPPORTED_VIEWS: ReadonlySet<InboxViewId> = new Set<InboxViewId>([
  "all",
  ...(Object.keys(INBOX_VIEW_STATUS) as InboxViewId[]),
  ...INBOX_CLIENT_VIEWS,
]);

/** Labels are read at render time (not module load) so a language switch
 *  re-renders them. */
function viewLabel(id: InboxViewId): string {
  switch (id) {
    case "my":
      return t.viewMy;
    case "unassigned":
      return t.viewUnassigned;
    case "all":
      return t.filterAll;
    case "priority":
      return t.viewPriority;
    case "sla-risk":
      return t.viewSlaRisk;
    case "waiting-customer":
      return t.viewWaitingCustomer;
    case "waiting-team":
      return t.viewWaitingTeam;
    case "vip":
      return t.viewVip;
    case "ai":
      return t.viewAi;
    case "ai-handover":
      return t.viewAiHandover;
    case "mentioned":
      return t.viewMentioned;
    case "team":
      return t.viewTeam;
    case "custom":
      return t.viewCustom;
  }
}

/** روابط الوسائط الواردة: نسمح فقط بـ http/https — أي قيمة أخرى (مثل javascript:) تُعرض كنص */
function safeUrl(url: string): string | null {
  return /^https?:\/\//i.test(url) ? url : null;
}

/** §111 — نستمع فقط لجداول صندوق الوارد؛ لكل جدول من order/notification مستمعوه الخاصون. */
const INBOX_STREAMS: string[] = ["message.events", "conversation.events"];

function StatusIcon({ status }: { status: string }) {
  if (status === "read") return <CheckCheck className="size-3 text-primary inline" />;
  if (status === "delivered") return <CheckCheck className="size-3 text-muted-foreground inline" />;
  if (status === "sent") return <Check className="size-3 text-muted-foreground inline" />;
  if (status === "failed") return <AlertCircle className="size-3 text-destructive inline" />;
  return <Clock className="size-3 text-muted-foreground/60 inline" />;
}

function ConversationsSkeleton() {
  return (
    <div className="space-y-2 p-3" aria-busy="true" aria-label={t.loading}>
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="flex items-center gap-3">
          <Skeleton className="size-9 rounded-full" />
          <div className="flex-1 space-y-1.5">
            <Skeleton className="h-3.5 w-28" />
            <Skeleton className="h-3 w-20" />
          </div>
        </div>
      ))}
    </div>
  );
}

function ConversationRow({
  convo,
  active,
  onSelect,
}: {
  convo: Conversation;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      data-testid={`convo-${convo.id}`}
      className={cn(
        "w-full rounded-xl border p-3 text-start transition-all duration-150 ease-smooth",
        active
          ? "border-primary/40 bg-primary-soft shadow-xs"
          : "border-transparent hover:bg-muted/70",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-sm font-bold" dir="auto">
          {convo.customer_name || `${convo.customer_id.slice(0, 8)}…`}
        </span>
        <Badge variant={CHANNEL_VARIANT[convo.channel] ?? "default"} className="text-[10px]">
          {convo.channel}
        </Badge>
      </div>
      <div className="mt-1 flex items-center justify-between">
        <span className="text-xs text-muted-foreground">{formatTime(convo.last_message_at)}</span>
        <span className="flex items-center gap-1.5">
          {/* §156: عرض حالة الانتظار في الصف — يوضّح وجه الفرق بين القنوات
              المُصفّاة بـstatus (بانتظار العميل/الفريق/AI). */}
          {convo.status !== "open" && convo.status !== "closed" && (
            <span className="text-[10px] text-muted-foreground">{convo.status}</span>
          )}
          {convo.unread_count > 0 && (
            <Badge variant="primary" data-testid={`unread-${convo.id}`}>
              {convo.unread_count}
            </Badge>
          )}
        </span>
      </div>
    </button>
  );
}

export default function InboxPage() {
  // useSearchParams يحتاج حدود Suspense أثناء التصيير المسبق
  return (
    <React.Suspense fallback={null}>
      <InboxContent />
    </React.Suspense>
  );
}

function InboxContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const conversationParam = searchParams.get("conversation");
  // §87 — الـview جزء من حالة الصفحة في الـURL، فأي رابط مثل
  // /inbox?view=unassigned&conversation=... يفتح على نفس الشاشة.
  const viewParam = searchParams.get("view");
  const view: InboxViewId = isInboxViewId(viewParam) ? viewParam : "all";
  const [selected, setSelected] = React.useState<string | null>(null);
  const [channelFilter, setChannelFilter] = React.useState<string>("all");
  const [searchQuery, setSearchQuery] = React.useState("");
  const [showContextPanel, setShowContextPanel] = React.useState(true);
  const [drawerCustomerId, setDrawerCustomerId] = React.useState<string | null>(null);
  const [draft, setDraft] = React.useState("");
  const bottomRef = React.useRef<HTMLDivElement>(null);

  const conversationsQuery = useConversations(view);
  const messagesQuery = useMessages(selected);
  const markRead = useMarkConversationRead();
  const sendMessage = useSendMessage(selected ?? "");
  const assignConversation = useAssignConversation();
  const me = useMe();
  const queryClient = useQueryClient();

  // §99 SLA risk — client join with GET /sla/risk; fetched only while the
  // view is active so no other inbox surface pays for it.
  const slaRiskQuery = useSlaRisk({ enabled: view === "sla-risk" });
  const slaRiskIds = React.useMemo(
    () =>
      new Set(
        (slaRiskQuery.data?.items ?? [])
          .filter((item) => item.status === "breached" || item.at_risk)
          .map((item) => item.conversation_id),
      ),
    [slaRiskQuery.data],
  );

  // §111 — لا إعادة جلب كاملة مع كل حدث SSE. التحديث موجّه: المحادثة المتأثرة
  // وحدها تعيد جلب رسائلها، وصف القائمة يُرقَّع في مكانه (في كل كاشات الـviews).
  useRealtimeEvents({
    streams: INBOX_STREAMS,
    onEvent: React.useCallback(
      (event: RealtimeEvent) => {
        const payload = event.payload;
        const conversationId =
          typeof payload.conversation_id === "string" ? payload.conversation_id : null;

        if (event.stream === "message.events" && conversationId) {
          // 1) المحادثة المتأثرة فقط — الـpayload لا يحمل شكل Message كاملًا
          //    (لا id ولا status ولا created_at) فلا يمكن تركيب الرسالة محليًا.
          queryClient.invalidateQueries({ queryKey: qk.messages(conversationId) });

          // 2) ترقيع صف القائمة في كل الـviews: message.received دائمًا وارد
          //    (يزيد غير المقروء)، أما message.outbound فيحمل message_id فقط
          //    (آخر ظهور فقط).
          const isInbound =
            typeof payload.body === "string" || typeof payload.channel === "string";
          queryClient.setQueriesData<InfiniteData<Page<Conversation>>>(
            { queryKey: qk.conversations },
            (previous) => {
              if (!previous) return previous;
              return {
                ...previous,
                pages: previous.pages.map((page) => ({
                  ...page,
                  items: page.items.map((c) =>
                    c.id === conversationId
                      ? {
                          ...c,
                          last_message_at: new Date().toISOString(),
                          unread_count:
                            isInbound && conversationId !== selected
                              ? c.unread_count + 1
                              : c.unread_count,
                        }
                      : c,
                  ),
                })),
              };
            },
          );
          return;
        }

        // أحداث بلا شكل قابل للتطبيق محليًا (conversation.events — لا منتج
        // له في الـbackend حتى الآن) → تسوية القائمة كاملة.
        queryClient.invalidateQueries({ queryKey: qk.conversations });
      },
      [queryClient, selected],
    ),
  });

  const allConversations = React.useMemo(
    () => (conversationsQuery.data?.pages ?? []).flatMap((page) => page.items),
    [conversationsQuery.data],
  );
  const activeConversation = allConversations.find((c) => c.id === selected);

  // §99 — client-filtered views operate on fields already in the payload:
  // my/unassigned read assignee_user_id, sla-risk joins the /sla/risk ids.
  const viewFilteredConversations = React.useMemo(() => {
    if (!INBOX_CLIENT_VIEWS.includes(view)) return allConversations;
    if (view === "my") return me.data ? allConversations.filter((c) => c.assignee_user_id === me.data?.id) : [];
    if (view === "unassigned") return allConversations.filter((c) => c.assignee_user_id == null);
    return allConversations.filter((c) => slaRiskIds.has(c.id));
  }, [allConversations, view, me.data, slaRiskIds]);

  const filteredConversations = React.useMemo(() => {
    return viewFilteredConversations.filter((c) => {
      const matchChannel = channelFilter === "all" || c.channel === channelFilter;
      const q = searchQuery.toLowerCase().trim();
      const matchSearch =
        !q ||
        (c.customer_name && c.customer_name.toLowerCase().includes(q)) ||
        c.customer_id.toLowerCase().includes(q) ||
        c.channel.toLowerCase().includes(q);
      return matchChannel && matchSearch;
    });
  }, [viewFilteredConversations, channelFilter, searchQuery]);

  const messages = messagesQuery.data ?? [];

  React.useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  // فتح المحادثة القادمة من الرابط (?conversation=<id>) — §87: المعامل يبقى
  // في الـURL حتى يكون الرابط قابلًا للمشاركة والتحديث دون فقدان الحالة.
  React.useEffect(() => {
    if (!conversationParam) return;
    setSelected(conversationParam);
  }, [conversationParam]);

  // تصفير المسودة عند أي تبديل للمحادثة المختارة — يمنع إرسال ردّ لعميل خطأ
  React.useEffect(() => {
    setDraft("");
  }, [selected]);

  function updateParams(mutate: (params: URLSearchParams) => void) {
    const params = new URLSearchParams(searchParams.toString());
    mutate(params);
    router.replace(`/inbox?${params.toString()}`, { scroll: false });
  }

  function selectView(next: InboxViewId) {
    if (next === view) return;
    updateParams((params) => params.set("view", next));
  }

  function selectConversation(id: string) {
    setSelected(id);
    setDraft(""); // ردّ نظيف عند تبديل المحادثة
    // §87 — كتابة المحادثة المفتوحة في الـURL مع الحفاظ على باقي المعاملات
    updateParams((params) => params.set("conversation", id));
    const target = allConversations.find((c) => c.id === id);
    if (target && target.unread_count > 0) markRead.mutate(id);
  }

  function send() {
    const body = draft.trim();
    if (!selected || !body || sendMessage.isPending) return;
    setDraft("");
    sendMessage.mutate(body);
  }

  const slaRiskLoading = view === "sla-risk" && slaRiskQuery.isLoading;

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title={t.inbox}
        description="كل محادثات العملاء من مختلف القنوات في مكان واحد — مزامنة فورية عبر SSE"
      />

      {conversationsQuery.isError && (
        <ErrorState
          message={(conversationsQuery.error as Error).message}
          onRetry={() => conversationsQuery.refetch()}
          className="mb-4"
        />
      )}

      <div className="grid flex-1 gap-4 lg:grid-cols-[300px_1fr] lg:min-h-[calc(100dvh-13rem)]">
        {/* conversations list + §99 views rail */}
        <Card className="flex flex-col overflow-hidden p-0 border border-border">
          <div className="border-b border-border p-3 space-y-2">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-bold">{t.conversations}</h2>
              <Badge variant="default" className="text-[11px]">
                {filteredConversations.length}
              </Badge>
            </div>

            {/* search filter */}
            <div className="relative">
              <Search className="pointer-events-none absolute start-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="بحث عن محادثة..."
                className="ps-8 h-8 text-xs"
              />
            </div>

            {/* §99 views rail — spec order; server views hit the API param,
                client views filter loaded pages, the rest stay disabled. */}
            <div className="flex flex-wrap gap-1 text-[11px]" data-testid="views-rail">
              {INBOX_VIEW_IDS.map((id) => {
                const supported = SUPPORTED_VIEWS.has(id);
                return (
                  <button
                    key={id}
                    type="button"
                    data-testid={`view-${id}`}
                    title={supported ? viewLabel(id) : `${viewLabel(id)} — ${t.comingSoon}`}
                    disabled={!supported}
                    aria-pressed={view === id}
                    onClick={() => selectView(id)}
                    className={cn(
                      "rounded-md px-2 py-0.5 transition-colors",
                      view === id
                        ? "bg-primary text-white font-medium"
                        : "bg-muted text-muted-foreground hover:bg-muted/80",
                      !supported && "opacity-40 hover:bg-muted cursor-not-allowed",
                    )}
                  >
                    {viewLabel(id)}
                  </button>
                );
              })}
            </div>

            {/* channel filter pills — merged into the §99 rail */}
            <div className="flex items-center gap-1 overflow-x-auto pb-1 text-[11px]">
              <span className="shrink-0 text-[10px] text-muted-foreground">{t.allChannels}:</span>
              {CHANNELS.map((ch) => (
                <button
                  key={ch}
                  type="button"
                  data-testid={`channel-${ch}`}
                  onClick={() => setChannelFilter(ch)}
                  className={cn(
                    "rounded-md px-2 py-0.5 capitalize transition-colors",
                    channelFilter === ch
                      ? "bg-primary text-white font-medium"
                      : "bg-muted text-muted-foreground hover:bg-muted/80",
                  )}
                >
                  {ch === "all" ? t.filterAll : ch}
                </button>
              ))}
            </div>
          </div>

          <div className="flex-1 overflow-y-auto p-2 space-y-1">
            {conversationsQuery.isLoading || slaRiskLoading ? (
              <ConversationsSkeleton />
            ) : filteredConversations.length === 0 ? (
              <EmptyState
                icon={<MessageCircleOff aria-hidden="true" />}
                title={t.noConversations}
                description={t.noConversationsHint}
                testid="inbox-empty"
              />
            ) : (
              <>
                {filteredConversations.map((c) => (
                  <ConversationRow
                    key={c.id}
                    convo={c}
                    active={selected === c.id}
                    onSelect={() => selectConversation(c.id)}
                  />
                ))}
                {conversationsQuery.hasNextPage && (
                  <div className="p-2">
                    <Button
                      variant="outline"
                      size="sm"
                      className="w-full text-xs"
                      onClick={() => conversationsQuery.fetchNextPage()}
                      disabled={conversationsQuery.isFetchingNextPage}
                      data-testid="load-more-conversations"
                    >
                      {conversationsQuery.isFetchingNextPage ? t.loading : t.loadMore}
                    </Button>
                  </div>
                )}
              </>
            )}
          </div>
        </Card>

        {/* thread and optional context panel */}
        <Card className="flex flex-col overflow-hidden p-0 border border-border">
          {!selected || !activeConversation ? (
            <EmptyState
              icon={<MessagesSquare aria-hidden="true" />}
              title={t.selectConversation}
              description={t.selectConversationHint}
              className="flex-1"
            />
          ) : (
            <div className={cn("grid flex-1 overflow-hidden", showContextPanel ? "lg:grid-cols-[1fr_280px]" : "grid-cols-1")}>
              {/* Message thread container */}
              <div className="flex flex-col h-full overflow-hidden">
                {/* Thread Header */}
                <div className="flex items-center justify-between border-b border-border px-4 py-2.5 bg-muted/20">
                  <div className="flex items-center gap-3">
                    <div className="size-8 rounded-full bg-primary/10 text-primary flex items-center justify-center font-bold text-xs">
                      {activeConversation.channel.slice(0, 1).toUpperCase()}
                    </div>
                    <div>
                      <div className="text-sm font-bold leading-none" dir="auto">
                        {activeConversation.customer_name || `${activeConversation.customer_id.slice(0, 8)}…`}
                      </div>
                      <div className="flex items-center gap-2 mt-1">
                        <Badge
                          variant={CHANNEL_VARIANT[activeConversation.channel] ?? "default"}
                          className="text-[10px] px-1.5 py-0"
                        >
                          {activeConversation.channel}
                        </Badge>
                        <span className="text-[11px] text-muted-foreground">
                          {activeConversation.status}
                        </span>
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-1">
                    {/* §99 — assign action. The backend has no team-members
                        listing endpoint yet, so the menu offers self-assign
                        and unassign; picking another member stays disabled. */}
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-xs gap-1.5"
                          data-testid="assign-button"
                        >
                          {activeConversation.assignee_user_id != null ? (
                            <UserCheck className="size-3.5" />
                          ) : (
                            <UserPlus className="size-3.5" />
                          )}
                          {activeConversation.assignee_user_id == null
                            ? t.assign
                            : activeConversation.assignee_user_id === me.data?.id
                              ? t.assignedToYou
                              : t.assignedBadge}
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem
                          data-testid="assign-to-me"
                          disabled={!me.data || assignConversation.isPending}
                          onSelect={() =>
                            me.data &&
                            assignConversation.mutate({
                              conversationId: activeConversation.id,
                              userId: me.data.id,
                            })
                          }
                        >
                          <UserPlus aria-hidden="true" />
                          {t.assignToMe}
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          variant="destructive"
                          data-testid="unassign-button"
                          disabled={activeConversation.assignee_user_id == null || assignConversation.isPending}
                          onSelect={() =>
                            assignConversation.mutate({
                              conversationId: activeConversation.id,
                              userId: null,
                            })
                          }
                        >
                          <UserRoundX aria-hidden="true" />
                          {t.unassign}
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem disabled title={t.comingSoon}>
                          <Users aria-hidden="true" />
                          {t.assignOtherMember} — {t.comingSoon}
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>

                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-8"
                      title={showContextPanel ? "إخفاء لوحة السياق" : "إظهار لوحة السياق"}
                      onClick={() => setShowContextPanel(!showContextPanel)}
                    >
                      {showContextPanel ? (
                        <PanelRightClose className="size-4" />
                      ) : (
                        <PanelRightOpen className="size-4" />
                      )}
                    </Button>
                  </div>
                </div>

                {/* Thread message list */}
                <div className="flex-1 space-y-3 overflow-y-auto p-4">
                  {messagesQuery.isLoading ? (
                    <div className="space-y-3" aria-busy="true" aria-label={t.loading}>
                      {Array.from({ length: 4 }).map((_, i) => (
                        <Skeleton key={i} className={cn("h-10 w-2/3", i % 2 ? "ms-auto" : "")} />
                      ))}
                    </div>
                  ) : messages.length === 0 ? (
                    <div className="py-12 text-center text-xs text-muted-foreground">
                      لا توجد رسائل في هذه المحادثة حتى الآن
                    </div>
                  ) : (
                    messages.map((m) => (
                      <div
                        key={m.id}
                        className={cn(
                          "max-w-[75%] rounded-2xl px-4 py-2.5 text-sm shadow-2xs",
                          m.direction === "outbound"
                            ? "ms-auto bg-primary text-white rounded-ee-xs"
                            : "me-auto bg-muted text-foreground rounded-es-xs",
                        )}
                      >
                        <p className="whitespace-pre-wrap leading-relaxed">{m.body}</p>
                        {m.media_url && safeUrl(m.media_url) ? (
                          <a
                            href={safeUrl(m.media_url) as string}
                            target="_blank"
                            rel="noreferrer"
                            dir="ltr"
                            className={cn(
                              "mt-1.5 block text-xs underline font-medium",
                              m.direction === "outbound" ? "text-white/90" : "text-primary",
                            )}
                          >
                            {m.media_type ?? "ملف مرفق"}
                          </a>
                        ) : m.media_url ? (
                          <span
                            dir="ltr"
                            className={cn(
                              "mt-1.5 block text-xs font-medium",
                              m.direction === "outbound" ? "text-white/90" : "text-muted-foreground",
                            )}
                          >
                            {m.media_type ?? "ملف مرفق"}
                          </span>
                        ) : null}
                        <div
                          className={cn(
                            "mt-1 flex items-center justify-end gap-1 text-[10px]",
                            m.direction === "outbound" ? "text-white/70" : "text-muted-foreground/70",
                          )}
                        >
                          <span>{formatTime(m.created_at)}</span>
                          {m.direction === "outbound" && <StatusIcon status={m.status} />}
                        </div>
                      </div>
                    ))
                  )}
                  <div ref={bottomRef} />
                </div>

                {/* Reply Input Bar */}
                <div className="flex gap-2 border-t border-border p-3 bg-card">
                  <Input
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && send()}
                    placeholder={t.writeReply}
                    data-testid="reply-input"
                    className="flex-1 text-sm"
                  />
                  <Button
                    onClick={send}
                    disabled={!draft.trim() || sendMessage.isPending}
                    data-testid="send-reply"
                    className="gap-1.5 px-4"
                  >
                    <Send className="size-4" />
                    {t.send}
                  </Button>
                </div>
              </div>

              {/* §99 context panel — customer / orders / timeline / AI / notes */}
              {showContextPanel && (
                <InboxContextPanel
                  customerId={activeConversation.customer_id}
                  channel={activeConversation.channel}
                  onOpenCustomerDrawer={() => setDrawerCustomerId(activeConversation.customer_id)}
                />
              )}
            </div>
          )}
        </Card>
      </div>

      <CustomerDrawer
        customerId={drawerCustomerId}
        open={Boolean(drawerCustomerId)}
        onOpenChange={(open) => {
          if (!open) setDrawerCustomerId(null);
        }}
      />
    </div>
  );
}
