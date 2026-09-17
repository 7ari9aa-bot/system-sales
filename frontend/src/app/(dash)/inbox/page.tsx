"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { t } from "@/lib/t";

type Conversation = {
  id: string;
  customer_id: string;
  channel: string;
  status: string;
  unread_count: number;
  last_message_at: string | null;
};

type Message = {
  id: string;
  direction: "inbound" | "outbound";
  sender_type: string;
  body: string | null;
  media_url: string | null;
  media_type: string | null;
  status: string;
  created_at: string;
};

const CHANNEL_BADGE: Record<string, string> = {
  whatsapp: "badge-success",
  telegram: "badge-primary",
  webchat: "",
};

export default function InboxPage() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  const loadConversations = useCallback(async () => {
    try {
      const rows = await api<Conversation[]>("/conversations");
      setConversations(rows);
      return rows;
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطأ");
      return [];
    }
  }, []);

  const loadMessages = useCallback(async (conversationId: string) => {
    try {
      const rows = await api<Message[]>(`/conversations/${conversationId}/messages`);
      setMessages(rows);
      await api(`/conversations/${conversationId}/read`, { method: "POST" });
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطأ");
    }
  }, []);

  useEffect(() => {
    loadConversations();
    const timer = setInterval(loadConversations, 15000);
    return () => clearInterval(timer);
  }, [loadConversations]);

  useEffect(() => {
    if (!selected) return;
    loadMessages(selected);
    const timer = setInterval(() => loadMessages(selected), 8000);
    return () => clearInterval(timer);
  }, [selected, loadMessages]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function send() {
    if (!selected || !draft.trim()) return;
    const body = draft.trim();
    setDraft("");
    try {
      await api(`/conversations/${selected}/messages`, { method: "POST", body: { body } });
      await loadMessages(selected);
    } catch (err) {
      setError(err instanceof Error ? err.message : "خطأ");
    }
  }

  function time(iso: string | null) {
    if (!iso) return "";
    return new Intl.DateTimeFormat("ar-EG-u-nu-latn", {
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(iso));
  }

  return (
    <div>
      <h1 className="page-title">{t.inbox}</h1>
      {error && <p className="error-text">{error}</p>}
      <div className="inbox-grid">
        <div className="card convo-list">
          {conversations.length === 0 && <div className="empty">{t.noConversations}</div>}
          {conversations.map((c) => (
            <div
              key={c.id}
              className={`convo-item ${selected === c.id ? "active" : ""}`}
              onClick={() => setSelected(c.id)}
              data-testid={`convo-${c.id}`}
            >
              <div style={{ display: "flex", justifyContent: "space-between", gap: "0.5rem" }}>
                <strong style={{ fontSize: 14 }}>
                  {c.customer_id.slice(0, 8)}…
                </strong>
                <span className={`badge ${CHANNEL_BADGE[c.channel] ?? ""}`}>{c.channel}</span>
              </div>
              <div className="muted" style={{ display: "flex", justifyContent: "space-between" }}>
                <span>{time(c.last_message_at)}</span>
                {c.unread_count > 0 && <span className="badge badge-primary">{c.unread_count}</span>}
              </div>
            </div>
          ))}
        </div>

        <div className="card thread">
          {!selected ? (
            <div className="empty">{t.selectConversation}</div>
          ) : (
            <>
              <div className="thread-messages">
                {messages.map((m) => (
                  <div key={m.id} className={`bubble ${m.direction === "outbound" ? "outbound" : ""}`}>
                    {m.body}
                    {m.media_url && (
                      <a href={m.media_url} target="_blank" rel="noreferrer" dir="ltr" style={{ display: "block", fontSize: 12 }}>
                        {m.media_type ?? "media"}
                      </a>
                    )}
                    <span className="time">{time(m.created_at)}</span>
                  </div>
                ))}
                <div ref={bottomRef} />
              </div>
              <div className="thread-input">
                <input
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && send()}
                  placeholder={t.writeReply}
                  data-testid="reply-input"
                />
                <button className="btn" onClick={send} disabled={!draft.trim()} data-testid="send-reply">
                  {t.send}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
