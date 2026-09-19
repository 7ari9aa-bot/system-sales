"use client";

import * as React from "react";
import Link from "next/link";
import {
  MessagesSquare,
  MessageCircleOff,
  Send,
  User,
  Phone,
  Mail,
  ShoppingBag,
  ExternalLink,
  PanelRightClose,
  PanelRightOpen,
  RefreshCw,
  Search,
  Check,
  CheckCheck,
  Clock,
  AlertCircle,
} from "lucide-react";
import {
  useConversations,
  useMarkConversationRead,
  useMessages,
  useSendMessage,
  useCustomer,
  type Conversation,
  type Message,
} from "@/lib/queries";
import { useRealtimeEvents } from "@/lib/use-realtime";
import { t } from "@/lib/t";
import { formatTime } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui/states";
import { CustomerDrawer } from "@/components/customer-drawer";
import { cn } from "@/lib/utils";

const CHANNEL_VARIANT: Record<string, "success" | "primary" | "default"> = {
  whatsapp: "success",
  telegram: "primary",
  webchat: "default",
};

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
        {convo.unread_count > 0 && (
          <Badge variant="primary" data-testid={`unread-${convo.id}`}>
            {convo.unread_count}
          </Badge>
        )}
      </div>
    </button>
  );
}

function CustomerSidebar({
  customerId,
  channel,
  onOpenCustomerDrawer,
}: {
  customerId: string;
  channel: string;
  onOpenCustomerDrawer: () => void;
}) {
  const customerQuery = useCustomer(customerId);
  const customer = customerQuery.data;

  return (
    <div className="flex flex-col border-s border-border bg-card/50 p-4 space-y-5 overflow-y-auto">
      <div className="flex items-center justify-between border-b border-border pb-3">
        <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
          معلومات العميل (360°)
        </h3>
        <Button
          size="sm"
          variant="ghost"
          onClick={onOpenCustomerDrawer}
          className="text-xs text-primary gap-1 h-7 px-2"
        >
          عرض كامل <ExternalLink className="size-3" />
        </Button>
      </div>

      <div className="flex flex-col items-center text-center space-y-2">
        <div className="flex size-14 items-center justify-center rounded-full bg-primary/10 text-primary font-bold text-xl">
          {customer?.name?.slice(0, 2) || <User className="size-6" />}
        </div>
        <div>
          <h4 className="font-bold text-sm text-foreground">{customer?.name || "عميل بدون اسم"}</h4>
          <span className="text-[11px] text-muted-foreground" dir="ltr">
            ID: {customerId.slice(0, 10)}…
          </span>
        </div>
        <Badge variant={CHANNEL_VARIANT[channel] ?? "default"} className="capitalize text-[11px]">
          قناة: {channel}
        </Badge>
      </div>

      <div className="space-y-3 pt-2 text-xs">
        <div className="rounded-lg border border-border bg-muted/40 p-2.5 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground flex items-center gap-1.5">
              <Phone className="size-3.5" /> الهاتف
            </span>
            <span dir="ltr" className="font-medium">
              {customer?.phone || "—"}
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground flex items-center gap-1.5">
              <Mail className="size-3.5" /> البريد
            </span>
            <span dir="ltr" className="font-medium truncate max-w-[140px]">
              {customer?.email || "—"}
            </span>
          </div>
        </div>

        <div className="rounded-lg border border-border bg-muted/40 p-2.5">
          <span className="text-muted-foreground">إجمالي قيمة المشتريات (LTV)</span>
          <div className="mt-1 text-base font-bold text-foreground" dir="ltr">
            {Number(customer?.lifetime_value || 0).toLocaleString("en-US", {
              minimumFractionDigits: 2,
            })}{" "}
            <span className="text-xs font-normal">ج.م</span>
          </div>
        </div>
      </div>

      <div className="space-y-2 pt-2">
        <Button variant="outline" size="sm" asChild className="w-full text-xs justify-start">
          <Link href="/orders">
            <ShoppingBag className="size-3.5 me-2" />
            إنشاء طلب جديد
          </Link>
        </Button>
      </div>
    </div>
  );
}

export default function InboxPage() {
  const [selected, setSelected] = React.useState<string | null>(null);
  const [channelFilter, setChannelFilter] = React.useState<string>("all");
  const [searchQuery, setSearchQuery] = React.useState("");
  const [showCustomerSidebar, setShowCustomerSidebar] = React.useState(true);
  const [drawerCustomerId, setDrawerCustomerId] = React.useState<string | null>(null);
  const [draft, setDraft] = React.useState("");
  const bottomRef = React.useRef<HTMLDivElement>(null);

  const conversationsQuery = useConversations();
  const messagesQuery = useMessages(selected);
  const markRead = useMarkConversationRead();
  const sendMessage = useSendMessage(selected ?? "");

  // Realtime events via SSE
  useRealtimeEvents({
    onEvent: React.useCallback(() => {
      conversationsQuery.refetch();
      if (selected) {
        messagesQuery.refetch();
      }
    }, [conversationsQuery, messagesQuery, selected]),
  });

  const allConversations = conversationsQuery.data ?? [];
  const activeConversation = allConversations.find((c) => c.id === selected);

  const filteredConversations = React.useMemo(() => {
    return allConversations.filter((c) => {
      const matchChannel = channelFilter === "all" || c.channel === channelFilter;
      const q = searchQuery.toLowerCase().trim();
      const matchSearch =
        !q ||
        (c.customer_name && c.customer_name.toLowerCase().includes(q)) ||
        c.customer_id.toLowerCase().includes(q) ||
        c.channel.toLowerCase().includes(q);
      return matchChannel && matchSearch;
    });
  }, [allConversations, channelFilter, searchQuery]);

  const messages = messagesQuery.data ?? [];

  React.useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  function selectConversation(id: string) {
    setSelected(id);
    markRead.mutate(id);
  }

  function send() {
    const body = draft.trim();
    if (!selected || !body || sendMessage.isPending) return;
    setDraft("");
    sendMessage.mutate(body);
  }

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
        {/* conversations list */}
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

            {/* channel filter pills */}
            <div className="flex gap-1 overflow-x-auto pb-1 text-[11px]">
              {["all", "whatsapp", "telegram", "webchat"].map((ch) => (
                <button
                  key={ch}
                  type="button"
                  onClick={() => setChannelFilter(ch)}
                  className={cn(
                    "rounded-md px-2 py-0.5 capitalize transition-colors",
                    channelFilter === ch
                      ? "bg-primary text-white font-medium"
                      : "bg-muted text-muted-foreground hover:bg-muted/80",
                  )}
                >
                  {ch === "all" ? "الكل" : ch}
                </button>
              ))}
            </div>
          </div>

          <div className="flex-1 overflow-y-auto p-2 space-y-1">
            {conversationsQuery.isLoading ? (
              <ConversationsSkeleton />
            ) : filteredConversations.length === 0 ? (
              <EmptyState
                icon={<MessageCircleOff aria-hidden="true" />}
                title={t.noConversations}
                description={t.noConversationsHint}
              />
            ) : (
              filteredConversations.map((c) => (
                <ConversationRow
                  key={c.id}
                  convo={c}
                  active={selected === c.id}
                  onSelect={() => selectConversation(c.id)}
                />
              ))
            )}
          </div>
        </Card>

        {/* thread and optional customer sidebar */}
        <Card className="flex flex-col overflow-hidden p-0 border border-border">
          {!selected || !activeConversation ? (
            <EmptyState
              icon={<MessagesSquare aria-hidden="true" />}
              title={t.selectConversation}
              description={t.selectConversationHint}
              className="flex-1"
            />
          ) : (
            <div className={cn("grid flex-1 overflow-hidden", showCustomerSidebar ? "lg:grid-cols-[1fr_260px]" : "grid-cols-1")}>
              {/* Message thread container */}
              <div className="flex flex-col h-full overflow-hidden">
                {/* Thread Header */}
                <div className="flex items-center justify-between border-b border-border px-4 py-2.5 bg-muted/20">
                  <div className="flex items-center gap-3">
                    <div className="size-8 rounded-full bg-primary/10 text-primary flex items-center justify-center font-bold text-xs">
                      {activeConversation.channel.slice(0, 1).toUpperCase()}
                    </div>
                    <div>
                      <div className="text-sm font-bold leading-none" dir="ltr">
                        {activeConversation.customer_id}
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
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-8"
                      title={showCustomerSidebar ? "إخفاء لوحة العميل" : "إظهار لوحة العميل"}
                      onClick={() => setShowCustomerSidebar(!showCustomerSidebar)}
                    >
                      {showCustomerSidebar ? (
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
                        {m.media_url && (
                          <a
                            href={m.media_url}
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
                        )}
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

              {/* Customer 360 sidebar */}
              {showCustomerSidebar && (
                <CustomerSidebar
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
