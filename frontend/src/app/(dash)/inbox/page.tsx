"use client";

import * as React from "react";
import { MessagesSquare, MessageCircleOff } from "lucide-react";
import { useConversations, useMarkConversationRead, useMessages, useSendMessage, type Conversation } from "@/lib/queries";
import { t } from "@/lib/t";
import { formatTime } from "@/lib/utils";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui/states";
import { cn } from "@/lib/utils";

const CHANNEL_VARIANT: Record<string, "success" | "primary" | "default"> = {
  whatsapp: "success",
  telegram: "primary",
  webchat: "default",
};

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

function ConversationRow({ convo, active, onSelect }: { convo: Conversation; active: boolean; onSelect: () => void }) {
  return (
    <button
      type="button"
      onClick={onSelect}
      data-testid={`convo-${convo.id}`}
      className={cn(
        "w-full rounded-lg border p-3 text-start transition-all duration-150 ease-smooth",
        active
          ? "border-primary-soft-border bg-primary-soft"
          : "border-transparent hover:bg-muted",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-sm font-bold" dir="ltr">
          {convo.customer_id.slice(0, 8)}…
        </span>
        <Badge variant={CHANNEL_VARIANT[convo.channel] ?? "default"}>{convo.channel}</Badge>
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

export default function InboxPage() {
  const [selected, setSelected] = React.useState<string | null>(null);
  const [draft, setDraft] = React.useState("");
  const bottomRef = React.useRef<HTMLDivElement>(null);

  const conversationsQuery = useConversations();
  const messagesQuery = useMessages(selected);
  const markRead = useMarkConversationRead();
  const sendMessage = useSendMessage(selected ?? "");

  const conversations = conversationsQuery.data ?? [];
  const messages = messagesQuery.data ?? [];

  React.useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  function selectConversation(id: string) {
    setSelected(id);
    // Optimistic mark-read — مسموح فقط هنا (§109)
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
      <PageHeader title={t.inbox} description="كل محادثات العملاء من كل القنوات في مكان واحد" />

      {conversationsQuery.isError && (
        <ErrorState
          message={(conversationsQuery.error as Error).message}
          onRetry={() => conversationsQuery.refetch()}
          className="mb-4"
        />
      )}

      <div className="grid flex-1 gap-4 lg:grid-cols-[320px_1fr] lg:min-h-[calc(100dvh-13rem)]">
        {/* conversations list */}
        <Card className="flex flex-col overflow-hidden p-0">
          <div className="border-b border-border px-4 py-3">
            <h2 className="text-sm font-bold">{t.conversations}</h2>
          </div>
          <div className="flex-1 overflow-y-auto p-2">
            {conversationsQuery.isLoading ? (
              <ConversationsSkeleton />
            ) : conversations.length === 0 ? (
              <EmptyState
                icon={<MessageCircleOff aria-hidden="true" />}
                title={t.noConversations}
                description={t.noConversationsHint}
              />
            ) : (
              conversations.map((c) => (
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

        {/* thread */}
        <Card className="flex flex-col overflow-hidden p-0">
          {!selected ? (
            <EmptyState
              icon={<MessagesSquare aria-hidden="true" />}
              title={t.selectConversation}
              description={t.selectConversationHint}
              className="flex-1"
            />
          ) : (
            <>
              <div className="flex-1 space-y-2 overflow-y-auto p-4">
                {messagesQuery.isLoading ? (
                  <div className="space-y-3" aria-busy="true" aria-label={t.loading}>
                    {Array.from({ length: 4 }).map((_, i) => (
                      <Skeleton key={i} className={cn("h-10 w-2/3", i % 2 ? "ms-auto" : "")} />
                    ))}
                  </div>
                ) : (
                  messages.map((m) => (
                    <div
                      key={m.id}
                      className={cn(
                        "max-w-[70%] rounded-2xl px-4 py-2 text-sm",
                        m.direction === "outbound"
                          ? "ms-auto bg-primary text-white"
                          : "me-auto bg-muted",
                      )}
                    >
                      {m.body}
                      {m.media_url && (
                        <a
                          href={m.media_url}
                          target="_blank"
                          rel="noreferrer"
                          dir="ltr"
                          className={cn("block text-xs underline", m.direction === "outbound" ? "text-white/80" : "text-primary")}
                        >
                          {m.media_type ?? "media"}
                        </a>
                      )}
                      <span className={cn("mt-0.5 block text-[11px]", m.direction === "outbound" ? "text-white/70" : "text-muted-foreground/70")}>
                        {formatTime(m.created_at)}
                      </span>
                    </div>
                  ))
                )}
                <div ref={bottomRef} />
              </div>
              <div className="flex gap-2 border-t border-border p-3">
                <Input
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && send()}
                  placeholder={t.writeReply}
                  data-testid="reply-input"
                  className="flex-1"
                />
                <Button onClick={send} disabled={!draft.trim() || sendMessage.isPending} data-testid="send-reply">
                  {t.send}
                </Button>
              </div>
            </>
          )}
        </Card>
      </div>
    </div>
  );
}
