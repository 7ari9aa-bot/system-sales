import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { readSignalBody, supportsReadSignal } from "@/components/inbox/whatsapp/readSignal";
import { visibleRows } from "@/components/inbox/whatsapp/chatListState";
import { CHANNELS, getChannel } from "@/lib/channels";
import { api } from "@/lib/api";
import { useInstagramPosts } from "@/hooks/useInstagramPosts";
import { useProfileBackfill } from "@/hooks/useProfileBackfill";
import { appendLocalMessage, sendReaction, sendReply, setMyReaction } from "@/lib/inboxSend";
import { previewLine } from "@/lib/inboxPreview";
import { useI18n, useT } from "@/lib/i18n";
import { useAuth } from "@/lib/AuthContext";
import { isDemoConversation, loadDemoFacebookPosts, loadDemoInbox, loadDemoInstagramPosts, saveDemoFacebookPosts, saveDemoInstagramPosts, saveDemoInbox } from "@/lib/inboxDemoData";


const INBOX_PAGE_SIZE = 50;
const MESSAGE_PAGE_SIZE = 50;
const CHAT_LIST_MIN_WIDTH = 280;
const CHAT_LIST_MAX_WIDTH = 560;
const CHAT_PANE_MIN_WIDTH = 360;
const CHAT_LIST_DEFAULT_WIDTH = 350;
const CHAT_LIST_WIDTH_STORAGE_KEY = "fihrist:inboxChatListWidth";
const MESSENGER_THEME_STORAGE_KEY = "fihrist:messengerChatThemes";
const WHATSAPP_AVATAR_COLORS = ["#f3d7c5", "#ddd9f2", "#d4e9dd", "#f2dce0", "#d6e6f4", "#efe8c9", "#dce2ef"];

function clampChatListWidth(value, max = CHAT_LIST_MAX_WIDTH) {
  return Math.min(max, Math.max(CHAT_LIST_MIN_WIDTH, Math.round(value)));
}

function isDemoConversationRow(row) {
  return isDemoConversation(row?.id);
}

function whatsappAvatarColor(value) {
  const key = String(value || "contact");
  let hash = 0;
  for (let index = 0; index < key.length; index += 1) hash = (hash * 31 + key.charCodeAt(index)) | 0;
  return WHATSAPP_AVATAR_COLORS[(hash >>> 0) % WHATSAPP_AVATAR_COLORS.length];
}

function displayTime(value) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? ""
    : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function toMessage(message) {
  return {
    id: message.id,
    side: message.direction === "outbound" ? "out" : "in",
    // A file sent without a caption has no text; `media_type` is a code ("audio"),
    // not something to show.
    text: message.body || "",
    fileName: message.filename || "",
    time: displayTime(message.created_at),
    createdAt: message.created_at,
    status: message.status,
    senderType: message.sender_type,
    ai: message.sender_type === "ai",
    mediaUrl: message.media_url,
    mediaType: message.media_type,
    contentType: message.content_type || "text",
    card: message.card || null,
    edited: Boolean(message.edited),
    deleted: Boolean(message.deleted),
    replyTo: message.reply_to || null,
    reactions: Array.isArray(message.reactions) ? message.reactions : [],
    myReaction: message.my_reaction || "",
  };
}

function toConversation(row, channel, t) {
  const status = String(row.status || "open").toLowerCase();
  const approvalStatus = status === "waiting_approval" || status === "approval";
  const viewStatus = approvalStatus
    ? "approval"
    : status === "waiting_ai"
      ? "ai"
      : status === "closed"
        ? "resolved"
        : "waiting";
  // Instagram names a customer only by a number until the profile is read: a real name wins,
  // then the @handle, and the bare number is the last resort.
  const bareNumber = /^\d{8,}$/.test(String(row.customer_name || "").trim());
  const handle = row.customer_handle ? `@${String(row.customer_handle).replace(/^@/, "")}` : "";
  const customer =
    (!bareNumber && row.customer_name) || handle || row.customer_name || row.customer_phone || row.customer_id || "—";
  return {
    id: row.id,
    customer,
    initials: String(customer).trim().slice(0, 2).toUpperCase() || "—",
    color: channel?.id === "whatsapp"
      ? whatsappAvatarColor(row.customer_id || customer)
      : channel?.accent || "hsl(var(--primary))",
    channel: row.channel,
    preview: previewLine(row, t),
    status: viewStatus,
    backendStatus: status,
    assigneeUserId: row.assignee_user_id || null,
    unread: Number(row.unread_count) || 0,
    time: displayTime(row.last_message_at),
    customerId: row.customer_id || null,
    lastAt: row.last_message_at || null,
    lastCustomerMessageAt: row.last_customer_message_at || null,
    phone: row.customer_phone || "",
    handle,
    needsProfile: row.channel === "instagram" && (bareNumber || !row.customer_avatar_url),
    lastDirection: row.last_message_direction || null,
    lastContentType: row.last_message_content_type || null,
    lastStatus: row.last_message_status || null,
    pinnedAt: row.pinned_at || null,
    mutedUntil: row.muted_until || null,
    archivedAt: row.archived_at || null,
    markedUnread: Boolean(row.marked_unread),
    avatarUrl: row.customer_avatar_url || row.profile_photo_url || row.avatar_url || null,
    hasStory: Boolean(row.has_story || row.story_available || row.story?.available),
    folder: row.folder || row.inbox_folder || row.category || (channel?.id === "instagram" ? "primary" : undefined),
    messages: [],
  };
}


const InboxContext = createContext(null);

export function useInbox() {
  const value = useContext(InboxContext);
  if (!value) throw new Error("useInbox must be used inside <InboxProvider>");
  return value;
}

export { CHAT_LIST_MIN_WIDTH, CHAT_LIST_MAX_WIDTH };

/** Owns every piece of inbox state (conversations, channels, approvals, sending).
 *  Mounted once above /inbox and /instagram/* so switching page keeps the data. */
export function InboxProvider({ children }) {
  const t = useT();
  const { lang } = useI18n();
  const { user } = useAuth();
  const demoAccount = String(user?.email || "").toLowerCase() === "dmin@revenueosapp.com";
  const location = useLocation();
  const navigate = useNavigate();
  const forcedChannel = location.pathname.startsWith("/instagram") ? "instagram" : null;
  const [storedChannel, setStoredChannel] = useState("whatsapp");
  const activeChannel = forcedChannel || storedChannel;
  const setActiveChannel = (id) => {
    if (id === "instagram" && !forcedChannel) { setStoredChannel("instagram"); navigate("/instagram/direct/inbox"); return; }
    if (forcedChannel && id !== "instagram") { setStoredChannel(id); navigate("/inbox"); return; }
    setStoredChannel(id);
  };
  const [facebookPosts, setFacebookPosts] = useState([]);
  const [instagramPosts, setInstagramPosts] = useState([]);
  const [instagramMode, setInstagramMode] = useState("comments");
  const [chatListWidth, setChatListWidth] = useState(() => {
    if (typeof window === "undefined") return CHAT_LIST_DEFAULT_WIDTH;
    try {
      const saved = Number(window.localStorage.getItem(CHAT_LIST_WIDTH_STORAGE_KEY));
      return Number.isFinite(saved) && saved >= CHAT_LIST_MIN_WIDTH
        ? clampChatListWidth(saved)
        : CHAT_LIST_DEFAULT_WIDTH;
    } catch {
      return CHAT_LIST_DEFAULT_WIDTH;
    }
  });
  const [isResizingChatList, setIsResizingChatList] = useState(false);
  const [messengerThemes, setMessengerThemes] = useState(() => {
    if (typeof window === "undefined") return {};
    try {
      const saved = JSON.parse(window.localStorage.getItem(MESSENGER_THEME_STORAGE_KEY) || "{}");
      return saved && typeof saved === "object" && !Array.isArray(saved) ? saved : {};
    } catch {
      return {};
    }
  });
  const inboxSplitRef = useRef(null);
  const resizePointerRef = useRef(null);
  const [mobileChatOpen, setMobileChatOpen] = useState(false);
  const [localActiveId, setLocalActiveId] = useState(null);
  const urlConversationId = (location.pathname.match(/^\/instagram\/direct\/t\/([^/]+)/) || [])[1] || null;
  const activeId = urlConversationId || localActiveId;
  const setActiveId = (id) => {
    setLocalActiveId(id);
    // On the Instagram pages the open chat lives in the address, so back/refresh keep your place.
    if (forcedChannel && location.pathname.startsWith("/instagram/direct")) {
      navigate(id ? `/instagram/direct/t/${encodeURIComponent(id)}` : "/instagram/direct/inbox");
    }
  };
  const [instagramFolder, setInstagramFolder] = useState("primary");
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [telegramListScrolling, setTelegramListScrolling] = useState(false);
  const telegramListScrollTimerRef = useRef(null);
  const [convMap, setConvMap] = useState(() => Object.fromEntries(CHANNELS.map((ch) => [ch.id, []])));
  const [channelStatus, setChannelStatus] = useState(null);
  const [channelStatusFailed, setChannelStatusFailed] = useState(false);
  const [approvals, setApprovals] = useState([]);
  const [approvalLoadError, setApprovalLoadError] = useState("");
  const [loadingInbox, setLoadingInbox] = useState(true);
  const [inboxLoadError, setInboxLoadError] = useState("");
  const [inboxMoreError, setInboxMoreError] = useState("");
  const [inboxCursor, setInboxCursor] = useState(null);
  const [loadingMoreInbox, setLoadingMoreInbox] = useState(false);
  const loadingMoreInboxRef = useRef(false);
  const [inboxRetryAttempt, setInboxRetryAttempt] = useState(0);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [loadingOlderMessages, setLoadingOlderMessages] = useState(false);
  const loadingOlderMessagesRef = useRef(false);
  const [messageCursor, setMessageCursor] = useState(null);
  const [messagesError, setMessagesError] = useState(null);
  const [messageRetryAttempt, setMessageRetryAttempt] = useState(0);
  const [sending, setSending] = useState(false);
  const [pendingDecision, setPendingDecision] = useState(false);
  const [error, setError] = useState(null);
  const activeMessageRequestRef = useRef({ conversationId: null, channelId: null });

  const updateChatListWidth = (nextWidth) => {
    const containerWidth = inboxSplitRef.current?.getBoundingClientRect().width || window.innerWidth;
    const maxWidth = Math.max(CHAT_LIST_MIN_WIDTH, Math.min(CHAT_LIST_MAX_WIDTH, containerWidth - CHAT_PANE_MIN_WIDTH - 5));
    const next = clampChatListWidth(nextWidth, maxWidth);
    setChatListWidth(next);
    try { window.localStorage.setItem(CHAT_LIST_WIDTH_STORAGE_KEY, String(next)); } catch {}
  };

  const handleResizePointerDown = (event) => {
    if (event.button !== 0 || window.innerWidth < 1024) return;
    event.preventDefault();
    resizePointerRef.current = event.pointerId;
    event.currentTarget.setPointerCapture(event.pointerId);
    setIsResizingChatList(true);
  };

  const handleResizePointerMove = (event) => {
    if (resizePointerRef.current !== event.pointerId || !inboxSplitRef.current) return;
    const bounds = inboxSplitRef.current.getBoundingClientRect();
    updateChatListWidth(event.clientX - bounds.left);
  };

  const finishChatListResize = (event) => {
    if (event && resizePointerRef.current !== event.pointerId) return;
    resizePointerRef.current = null;
    setIsResizingChatList(false);
  };

  const handleResizeKeyDown = (event) => {
    const step = event.shiftKey ? 40 : 16;
    if (event.key === "ArrowRight") {
      event.preventDefault();
      updateChatListWidth(chatListWidth + step);
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      updateChatListWidth(chatListWidth - step);
    } else if (event.key === "Home") {
      event.preventDefault();
      updateChatListWidth(CHAT_LIST_MIN_WIDTH);
    } else if (event.key === "End") {
      event.preventDefault();
      updateChatListWidth(CHAT_LIST_MAX_WIDTH);
    }
  };

  useEffect(() => {
    try { window.localStorage.setItem(MESSENGER_THEME_STORAGE_KEY, JSON.stringify(messengerThemes)); } catch {}
  }, [messengerThemes]);

  const loadInboxPage = useCallback(async ({ cursor = null, replace = false } = {}) => {
    const params = new URLSearchParams({ limit: String(INBOX_PAGE_SIZE) });
    if (cursor) params.set("cursor", cursor);
    const response = await api(`/inbox?${params.toString()}`);
    // The default list hides archived chats; the first page also fetches them so
    // the Archived entry and its view are complete.
    const archivedResponse = cursor ? null : await api(`/inbox?${new URLSearchParams({ limit: String(INBOX_PAGE_SIZE), archived: "true" }).toString()}`).catch(() => null);
    const page = Object.fromEntries(CHANNELS.map((channel) => [channel.id, []]));
    const seenIds = new Set();
    for (const row of [...(response?.items ?? []), ...(archivedResponse?.items ?? [])]) {
      // One row can only be in one of the two answers, but never trust that.
      if (seenIds.has(row.id)) continue;
      seenIds.add(row.id);
      const channel = row.channel || "webchat";
      if (!page[channel]) continue;
      page[channel].push(toConversation(row, getChannel(channel), t));
    }
    setConvMap((previous) => Object.fromEntries(CHANNELS.map((channel) => {
      const existing = replace
        ? (demoAccount ? loadDemoInbox()[channel.id] || [] : [])
        : previous[channel.id] || [];
      const seen = new Set(existing.map((conversation) => conversation.id));
      return [channel.id, [...existing, ...(page[channel.id] || []).filter((conversation) => !seen.has(conversation.id))]];
    })));
    const nextCursor = response?.next_cursor ?? null;
    setInboxCursor(nextCursor);
    return nextCursor;
  }, [demoAccount, t]);

  const reloadInbox = useCallback(async () => loadInboxPage({ replace: true }), [loadInboxPage]);

  useEffect(() => {
    if (demoAccount) setConvMap(loadDemoInbox());
  }, [demoAccount]);

  useEffect(() => {
    setFacebookPosts(demoAccount ? loadDemoFacebookPosts() : []);
  }, [demoAccount]);

  useEffect(() => {
    setInstagramPosts(demoAccount ? loadDemoInstagramPosts() : []);
  }, [demoAccount]);

  useEffect(() => () => clearTimeout(telegramListScrollTimerRef.current), []);

  const loadMoreConversations = useCallback(async () => {
    if (!inboxCursor || loadingMoreInboxRef.current) return;
    loadingMoreInboxRef.current = true;
    setLoadingMoreInbox(true);
    setInboxMoreError("");
    try {
      await loadInboxPage({ cursor: inboxCursor });
    } catch (e) {
      setInboxMoreError(e?.message || "Could not load more conversations.");
    } finally {
      loadingMoreInboxRef.current = false;
      setLoadingMoreInbox(false);
    }
  }, [inboxCursor, loadInboxPage]);

  const reloadApprovals = useCallback(async () => {
    const response = await api("/ai/approvals?status=PENDING");
    setApprovals(Array.isArray(response?.items) ? response.items : []);
    setApprovalLoadError("");
  }, []);

  useEffect(() => {
    let alive = true;
    setLoadingInbox(true);
    setInboxLoadError("");
    setError(null);
    api("/channels/status")
      .then((rows) => {
        if (!alive) return;
        setChannelStatusFailed(false);
        setChannelStatus(Array.isArray(rows) ? rows : []);
      })
      .catch(() => {
        // Degraded, NOT locked: when the status service is unreachable
        // (session still settling on a first visit, timeout, transient 5xx)
        // the inbox must fall back to what the conversations themselves
        // prove — the pre-owner-console behavior. Locking every tile hid
        // real messages (regression reported 2026-11-04).
        if (!alive) return;
        setChannelStatusFailed(true);
        setChannelStatus([]);
      });
    api("/ai/approvals?status=PENDING")
      .then((response) => {
        if (!alive) return;
        setApprovals(Array.isArray(response?.items) ? response.items : []);
        setApprovalLoadError("");
      })
      .catch((e) => alive && setApprovalLoadError(e?.message || "Could not load pending approvals."));
    setInboxCursor(null);
    setInboxMoreError("");
    loadInboxPage({ replace: true })
      .then(() => { if (alive) setInboxLoadError(""); })
      .catch((e) => alive && setInboxLoadError(e?.message || "Could not load the inbox."))
      .finally(() => alive && setLoadingInbox(false));
    return () => { alive = false; };
  }, [inboxRetryAttempt, loadInboxPage]);

  const channels = useMemo(() => {
    if (demoAccount) return CHANNELS.map((channel) => ({ ...channel, connected: true, locked: false }));
    const byProvider = new Map((channelStatus || []).map((row) => [row.provider, row]));
    const haveConversations = new Set(
      Object.entries(convMap).filter(([, rows]) => rows.length > 0).map(([channelId]) => channelId)
    );
    return CHANNELS.map((channel) => {
      const status = byProvider.get(channel.id);
      if (channelStatusFailed && !status) {
        // Status service unreachable — degrade to conversation-derived truth.
        return {
          ...channel,
          connected: haveConversations.has(channel.id),
          locked: false,
          lifecycle: "unknown",
          webhookStatus: "unknown",
        };
      }
      const connected = Boolean(status?.connected && status?.enabled_for_me);
      return {
        ...channel,
        connected,
        locked: status ? Boolean(status.locked) : true,
        lifecycle: status?.lifecycle || "not_connected",
        webhookStatus: status?.webhook_status || "not_connected",
      };
    });
  }, [channelStatus, channelStatusFailed, convMap, demoAccount]);

  useEffect(() => {
    if (channelStatus === null) return;
    const selected = channels.find((channel) => channel.id === activeChannel);
    if (selected?.connected) return;
    const firstConnected = channels.find((channel) => channel.connected);
    if (firstConnected) {
      setActiveChannel(firstConnected.id);
      setActiveId(null);
    }
  }, [activeChannel, channels, channelStatus]);

  const channel = getChannel(activeChannel);
  const isWhatsApp = activeChannel === "whatsapp";
  const isTelegram = activeChannel === "telegram";
  const isMessenger = activeChannel === "messenger";
  const isFacebook = activeChannel === "facebook";
  const isInstagram = activeChannel === "instagram";
  // Real posts and comments for a real account; the demo account keeps its local sample data.
  const igLive = useInstagramPosts({ enabled: isInstagram && !demoAccount, lang });
  useProfileBackfill({ rows: convMap.instagram, enabled: isInstagram && !demoAccount, reload: reloadInbox });
  const allConversations = convMap[activeChannel] || [];
  const approvalsByConversation = useMemo(() => {
    const map = new Map();
    for (const approval of approvals || []) {
      if (approval.conversation_id && !map.has(approval.conversation_id)) {
        map.set(approval.conversation_id, approval);
      }
    }
    return map;
  }, [approvals]);

  const conversations = useMemo(() => allConversations.map((conversation) => ({
    ...conversation,
    approval: approvalsByConversation.get(conversation.id) || null,
    status: approvalsByConversation.has(conversation.id) ? "approval" : conversation.status,
  })), [allConversations, approvalsByConversation]);

  const FILTERS = [
    { id: "all", label: t("inbox.filter.all") },
    { id: "waiting", label: t("inbox.filter.waiting") },
    { id: "approvals", label: t("inbox.filter.approvals") },
  ];

  const filtered = conversations.filter((conversation) => {
    const matchesFilter = isTelegram || filter === "all"
      || (filter === "waiting" && conversation.status !== "resolved" && conversation.status !== "approval")
      || (filter === "approvals" && (Boolean(conversation.approval) || conversation.status === "approval"));
    const needle = query.trim().toLowerCase();
    const matchesQuery = !needle || `${conversation.customer} ${conversation.preview}`.toLowerCase().includes(needle);
    return matchesFilter && matchesQuery;
  });
  const instagramFolders = [
    { id: "primary", label: lang === "ar" ? "رئيسي" : "Primary" },
    { id: "general", label: lang === "ar" ? "عام" : "General" },
    { id: "requests", label: lang === "ar" ? "طلبات" : "Requests" },
  ];
  const visibleWhatsAppRows = useMemo(() => visibleRows(conversations, { tab: "all", query: "", archived: false }), [conversations]);
  const visibleConversations = isInstagram
    ? filtered.filter((conversation) => (conversation.folder || "primary") === instagramFolder)
    : filtered;
  // WhatsApp lists are ordered pinned-first and hide archived chats, so the
  // fallback "first row" must be the first row the person can actually see.
  const currentPool = isWhatsApp ? visibleWhatsAppRows : visibleConversations;
  // On the Instagram pages the open chat comes from the address only: no address, no chat,
  // and a chat in another folder (General, Requests) is still the one that opens.
  const current = forcedChannel
    ? (activeId ? conversations.find((conversation) => conversation.id === activeId) || null : null)
    : currentPool.find((conversation) => conversation.id === activeId)
      || (isWhatsApp ? conversations.find((conversation) => conversation.id === activeId) : null)
      || currentPool[0] || null;
  activeMessageRequestRef.current = { conversationId: current?.id ?? null, channelId: activeChannel };
  const pendingApproval = current?.approval || null;
  const connectedCount = channels.filter((item) => item.connected).length;
  const unreadByChannel = Object.fromEntries(
    Object.entries(convMap).map(([id, rows]) => [id, rows.reduce((count, row) => count + row.unread, 0)])
  );
  const instagramAccountIdentity = channelStatus?.find((row) => row.provider === "instagram" && row.connected)?.account_name?.trim() || "";

  useEffect(() => {
    if (activeChannel === "facebook") {
      setLoadingMessages(false);
      return undefined;
    }
    if (!current?.id) {
      setLoadingMessages(false);
      setMessagesError(null);
      return undefined;
    }
    let alive = true;
    const conversationId = current.id;
    const channelId = activeChannel;
    if (isDemoConversation(conversationId)) {
      setLoadingMessages(false);
      setConvMap((previous) => ({
        ...previous,
        [channelId]: (previous[channelId] || []).map((row) =>
          row.id === conversationId ? { ...row, messages: row.messages || [] } : row
        ),
      }));
      return () => { alive = false; };
    }
    setLoadingMessages(true);
    setLoadingOlderMessages(false);
    loadingOlderMessagesRef.current = false;
    setMessageCursor(null);
    setMessagesError(null);
    api(`/conversations/${conversationId}/messages?limit=${MESSAGE_PAGE_SIZE}`)
      .then((response) => {
        if (!alive) return;
        const messages = (response?.items || []).map(toMessage);
        setMessageCursor(response?.next_cursor ?? null);
        setConvMap((previous) => ({
          ...previous,
          [channelId]: (previous[channelId] || []).map((row) =>
            row.id === conversationId ? { ...row, messages } : row
          ),
        }));
      })
      .catch((e) => alive && setMessagesError({
        conversationId,
        channelId,
        message: e?.message || "Could not load conversation messages.",
      }))
      .finally(() => alive && setLoadingMessages(false));
    return () => { alive = false; };
  }, [activeChannel, current?.id, messageRetryAttempt]);

  const loadOlderMessages = useCallback(async () => {
    if (!current?.id || !messageCursor || loadingOlderMessagesRef.current) return false;
    if (isDemoConversation(current.id)) return false;
    const conversationId = current.id;
    const channelId = activeChannel;
    loadingOlderMessagesRef.current = true;
    setLoadingOlderMessages(true);
    try {
      const params = new URLSearchParams({ limit: String(MESSAGE_PAGE_SIZE), cursor: messageCursor });
      const response = await api(`/conversations/${conversationId}/messages?${params.toString()}`);
      if (activeMessageRequestRef.current.conversationId !== conversationId || activeMessageRequestRef.current.channelId !== channelId) return false;
      const older = (response?.items || []).map(toMessage);
      setMessageCursor(response?.next_cursor ?? null);
      setConvMap((previous) => ({
        ...previous,
        [channelId]: (previous[channelId] || []).map((row) => {
          if (row.id !== conversationId) return row;
          const existingIds = new Set((row.messages || []).map((message) => message.id));
          return { ...row, messages: [...older.filter((message) => !existingIds.has(message.id)), ...(row.messages || [])] };
        }),
      }));
      return true;
    } catch (e) {
      setMessagesError({ conversationId, channelId, message: e?.message || "Could not load earlier messages." });
      return false;
    } finally {
      loadingOlderMessagesRef.current = false;
      setLoadingOlderMessages(false);
    }
  }, [activeChannel, current?.id, messageCursor]);

  function selectConversation(conversation) {
    setActiveId(conversation.id);
    if (conversation.unread <= 0) return;
    if (isDemoConversation(conversation.id)) {
      setConvMap((previous) => {
        const next = {
          ...previous,
          [activeChannel]: (previous[activeChannel] || []).map((row) =>
            row.id === conversation.id ? { ...row, unread: 0 } : row
          ),
        };
        saveDemoInbox(Object.fromEntries(CHANNELS.map((channel) => [
          channel.id,
          (next[channel.id] || []).filter(isDemoConversationRow),
        ])));
        return next;
      });
      return;
    }
    // The customer sees blue ticks only when the business really read their message.
    // A courtesy: a failure is silent and never blocks opening the chat.
    if (supportsReadSignal(conversation) && !conversation.markedUnread) {
      api(`/conversations/${conversation.id}/read-signal`, {
        method: "POST",
        body: readSignalBody(false),
      }).catch(() => {});
    }
    api(`/conversations/${conversation.id}/read`, { method: "POST" })
      .then(() => {
        setConvMap((previous) => ({
          ...previous,
          [activeChannel]: (previous[activeChannel] || []).map((row) =>
            row.id === conversation.id ? { ...row, unread: 0 } : row
          ),
        }));
      })
      .catch((e) => setError(e?.message || "Could not mark the conversation as read."));
  }

  // Pin, mute, archive or mark unread. The server answers with the new state;
  // the list changes only after it confirms, never on a guess.
  async function changeListState(conversation, body) {
    if (isDemoConversation(conversation.id)) return;
    try {
      const saved = await api(`/conversations/${conversation.id}/list-state`, { method: "POST", body });
      setConvMap((previous) => ({
        ...previous,
        [activeChannel]: (previous[activeChannel] || []).map((row) => row.id === conversation.id ? {
          ...row,
          pinnedAt: saved.pinned_at || null,
          mutedUntil: saved.muted_until || null,
          archivedAt: saved.archived_at || null,
          markedUnread: Boolean(saved.marked_unread),
        } : row),
      }));
    } catch (e) {
      setError(e?.message || "Could not update the conversation.");
    }
  }

  async function handleSend(conversationId, text, opts = {}) {
    if (isDemoConversation(conversationId)) {
      const createdAt = new Date().toISOString();
      const localMessage = {
        id: `${conversationId}:m${Date.now()}`,
        side: "out",
        text,
        time: displayTime(createdAt),
        createdAt,
        status: "sent",
        senderType: "agent",
      };
      setConvMap((previous) => {
        const next = {
          ...previous,
          [activeChannel]: (previous[activeChannel] || []).map((row) => row.id === conversationId
            ? { ...row, preview: text, time: displayTime(createdAt), createdAt, messages: [...(row.messages || []), localMessage] }
            : row),
        };
        saveDemoInbox(Object.fromEntries(CHANNELS.map((channel) => [
          channel.id,
          (next[channel.id] || []).filter(isDemoConversationRow),
        ])));
        return next;
      });
      return true;
    }
    // Captured BEFORE the await: the user may switch channel while the request
    // is in flight, and the local echo must land in the channel it was sent from.
    const channelId = activeChannel;
    setSending(true);
    setError(null);
    try {
      const result = await sendReply(conversationId, text, { replyToId: opts.replyTo?.id || null, mediaId: opts.mediaId || null });
      if (!result.ok) {
        setError(result.error);
        return false;
      }
      const sent = result.sent;
      const createdAt = sent?.created_at || new Date().toISOString();
      // A file the agent just sent shows from the local copy (the server's link
      // is signed and arrives with the next load), as its own kind of message.
      const sentFile = opts.mediaId
        ? {
            mediaType: opts.mediaKind,
            contentType: { image: "image", sticker: "image", audio: "voice", video: "video", document: "file" }[opts.mediaKind],
            mediaUrl: opts.previewFile ? URL.createObjectURL(opts.previewFile) : undefined,
            fileName: opts.filename,
          }
        : {};
      const localMessage = {
        id: sent?.id || `${conversationId}-${Date.now()}`,
        // No server id yet: this echo cannot be reacted to until the list reloads.
        unsaved: !sent?.id,
        side: "out",
        ...sentFile,
        text,
        time: displayTime(createdAt),
        createdAt,
        status: sent?.status || "queued",
        // The quote is shown straight away, built from the message being answered.
        replyTo: opts.replyTo
          ? {
              id: opts.replyTo.id,
              available: true,
              direction: opts.replyTo.side === "out" ? "outbound" : "inbound",
              content_type: opts.replyTo.contentType || "text",
              body: opts.replyTo.text || "",
            }
          : null,
      };
      setConvMap((previous) => appendLocalMessage(previous, channelId, conversationId, localMessage, text || opts.filename || ""));
      return true;
    } finally {
      setSending(false);
    }
  }

  // Show the reaction at once, then ask the server; if it refuses, put it back
  // and say why, so the screen never claims a reaction that was not sent.
  async function handleReact(conversationId, messageId, emoji, previous = "") {
    const channelId = activeChannel;
    if (demoAccount) {
      setConvMap((prev) => setMyReaction(prev, channelId, conversationId, messageId, emoji, previous));
      return true;
    }
    setConvMap((prev) => setMyReaction(prev, channelId, conversationId, messageId, emoji, previous));
    const result = await sendReaction(conversationId, messageId, emoji);
    if (!result.ok) {
      setConvMap((prev) => setMyReaction(prev, channelId, conversationId, messageId, previous, emoji));
      setError(result.error);
      return false;
    }
    return true;
  }

  async function decideApproval(approval, decision) {
    if (!approval) return false;
    setPendingDecision(true);
    setError(null);
    try {
      await api(`/ai/approvals/${approval.id}/decide`, {
        method: "POST",
        body: { decision },
      });
      setApprovals((previous) => previous.filter((item) => item.id !== approval.id));
      await Promise.all([reloadApprovals(), reloadInbox()]);
      return true;
    } catch (e) {
      setError(e?.message || "Could not record the approval decision.");
      return false;
    } finally {
      setPendingDecision(false);
    }
  }

  function addFacebookPageReply(commentId, text) {
    if (!demoAccount) return;
    setFacebookPosts((previous) => {
      const createdAt = new Date();
      const timeLabel = lang === "ar" ? "الآن" : "Just now";
      const updated = previous.map((post) => ({
        ...post,
        comments: (post.comments || []).map((comment) => comment.id === commentId
          ? { ...comment, replies: [...(comment.replies || []), {
            id: `demo:facebook-reply:${createdAt.getTime()}`,
            author: post.pageName,
            avatarUrl: post.pageAvatarUrl || "/fihrist-mark.svg",
            timeLabel,
            text,
            isPage: true,
          }] }
          : comment),
      }));
      saveDemoFacebookPosts(updated);
      return updated;
    });
  }

  function addFacebookPageComment(postId, text) {
    if (!demoAccount) return;
    setFacebookPosts((previous) => {
      const createdAt = new Date();
      const updated = previous.map((post) => post.id === postId ? {
        ...post,
        comments: [...(post.comments || []), {
          id: `demo:facebook-comment:${createdAt.getTime()}`,
          author: post.pageName,
          avatarUrl: post.pageAvatarUrl || "/fihrist-mark.svg",
          timeLabel: lang === "ar" ? "الآن" : "Just now",
          text,
          likes: 0,
          replies: [],
          isPage: true,
        }],
      } : post);
      saveDemoFacebookPosts(updated);
      return updated;
    });
  }

  function addInstagramPageReply(commentId, postId, text) {
    if (!demoAccount) return;
    setInstagramPosts((previous) => {
      const createdAt = new Date();
      const reply = {
        id: `demo:instagram-reply:${createdAt.getTime()}`,
        author: "fihrist.store",
        handle: "fihrist.store",
        avatarUrl: "/fihrist-mark.svg",
        timeLabel: lang === "ar" ? "الآن" : "Just now",
        text,
        likes: 0,
        isPage: true,
        isAgent: false,
        replies: [],
      };
      const updated = previous.map((post) => {
        if (post.id !== postId) return post;
        if (!commentId) return { ...post, comments: [...(post.comments || []), { ...reply, id: `demo:instagram-comment:${createdAt.getTime()}` }] };
        const addReply = (comments) => (comments || []).map((comment) => {
          if (comment.id === commentId) return { ...comment, replies: [...(comment.replies || []), reply] };
          return comment.replies?.some((nested) => nested.id === commentId)
            ? { ...comment, replies: addReply(comment.replies) }
            : comment;
        });
        return { ...post, comments: addReply(post.comments) };
      });
      saveDemoInstagramPosts(updated);
      return updated;
    });
  }

  const value = {
    t,
    lang,
    user,
    demoAccount,
    activeChannel,
    setActiveChannel,
    facebookPosts,
    instagramPosts,
    instagramMode,
    setInstagramMode,
    chatListWidth,
    isResizingChatList,
    messengerThemes,
    setMessengerThemes,
    mobileChatOpen,
    setMobileChatOpen,
    activeId,
    setActiveId,
    instagramFolder,
    setInstagramFolder,
    filter,
    setFilter,
    query,
    setQuery,
    telegramListScrolling,
    setTelegramListScrolling,
    convMap,
    channelStatus,
    channelStatusFailed,
    approvals,
    approvalLoadError,
    setApprovalLoadError,
    loadingInbox,
    inboxLoadError,
    inboxMoreError,
    inboxCursor,
    loadingMoreInbox,
    setInboxRetryAttempt,
    loadingMessages,
    loadingOlderMessages,
    messageCursor,
    messagesError,
    setMessageRetryAttempt,
    sending,
    pendingDecision,
    error,
    setError,
    inboxSplitRef,
    telegramListScrollTimerRef,
    handleResizePointerDown,
    handleResizePointerMove,
    finishChatListResize,
    handleResizeKeyDown,
    loadMoreConversations,
    reloadApprovals,
    reloadInbox,
    channels,
    channel,
    isWhatsApp,
    isTelegram,
    isInstagram,
    isMessenger,
    isFacebook,
    igLive,
    conversations,
    FILTERS,
    filtered,
    instagramFolders,
    visibleConversations,
    current,
    pendingApproval,
    connectedCount,
    unreadByChannel,
    instagramAccountIdentity,
    loadOlderMessages,
    selectConversation,
    changeListState,
    handleSend,
    handleReact,
    decideApproval,
    addFacebookPageReply,
    addFacebookPageComment,
    addInstagramPageReply,
  };
  return <InboxContext.Provider value={value}>{children}</InboxContext.Provider>;
}
