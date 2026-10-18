import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Search } from "lucide-react";
import ChannelSwitcher from "@/components/inbox/ChannelSwitcher";
import ChannelChat from "@/components/inbox/ChannelChat";
import ConversationAvatar from "@/components/inbox/ConversationAvatar";
import FacebookPostsWorkspace from "@/components/inbox/FacebookPostsWorkspace";
import InstagramModeTabs from "@/components/inbox/InstagramModeTabs";
import InstagramPostsWorkspace from "@/components/inbox/InstagramPostsWorkspace";
import { CHANNELS, getChannel } from "@/lib/channels";
import { api } from "@/lib/api";
import { useI18n, useT } from "@/lib/i18n";
import { useAuth } from "@/lib/AuthContext";
import { isDemoConversation, loadDemoFacebookPosts, loadDemoInbox, loadDemoInstagramPosts, saveDemoFacebookPosts, saveDemoInstagramPosts, saveDemoInbox } from "@/lib/inboxDemoData";
import { cn } from "@/lib/utils";

const INBOX_PAGE_SIZE = 50;
const MESSAGE_PAGE_SIZE = 50;
const CHAT_LIST_MIN_WIDTH = 280;
const CHAT_LIST_MAX_WIDTH = 560;
const CHAT_PANE_MIN_WIDTH = 360;
const CHAT_LIST_DEFAULT_WIDTH = 330;
const CHAT_LIST_WIDTH_STORAGE_KEY = "fihrist:inboxChatListWidth";
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
    text: message.body || message.media_type || "",
    time: displayTime(message.created_at),
    createdAt: message.created_at,
    status: message.status,
    senderType: message.sender_type,
    ai: message.sender_type === "ai",
    mediaUrl: message.media_url,
    mediaType: message.media_type,
  };
}

function toConversation(row, channel) {
  const status = String(row.status || "open").toLowerCase();
  const approvalStatus = status === "waiting_approval" || status === "approval";
  const viewStatus = approvalStatus
    ? "approval"
    : status === "waiting_ai"
      ? "ai"
      : status === "closed"
        ? "resolved"
        : "waiting";
  const customer = row.customer_name || row.customer_phone || row.customer_id || "—";
  return {
    id: row.id,
    customer,
    initials: String(customer).trim().slice(0, 2).toUpperCase() || "—",
    color: channel?.id === "whatsapp"
      ? whatsappAvatarColor(row.customer_id || customer)
      : channel?.accent || "hsl(var(--primary))",
    channel: row.channel,
    preview: row.last_message_preview || "",
    status: viewStatus,
    backendStatus: status,
    assigneeUserId: row.assignee_user_id || null,
    unread: Number(row.unread_count) || 0,
    time: displayTime(row.last_message_at),
    avatarUrl: row.customer_avatar_url || row.profile_photo_url || row.avatar_url || null,
    hasStory: Boolean(row.has_story || row.story_available || row.story?.available),
    folder: row.folder || row.inbox_folder || row.category || (channel?.id === "instagram" ? "primary" : undefined),
    messages: [],
  };
}

export default function Inbox() {
  const t = useT();
  const { lang } = useI18n();
  const { user } = useAuth();
  const demoAccount = String(user?.email || "").toLowerCase() === "dmin@revenueosapp.com";
  const [activeChannel, setActiveChannel] = useState("whatsapp");
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
  const inboxSplitRef = useRef(null);
  const resizePointerRef = useRef(null);
  const [mobileChatOpen, setMobileChatOpen] = useState(false);
  const [activeId, setActiveId] = useState(null);
  const [instagramFolder, setInstagramFolder] = useState("primary");
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [telegramListScrolling, setTelegramListScrolling] = useState(false);
  const telegramListScrollTimerRef = useRef(null);
  const [convMap, setConvMap] = useState(() => Object.fromEntries(CHANNELS.map((ch) => [ch.id, []])));
  const [integrations, setIntegrations] = useState(null);
  const [integrationAccess, setIntegrationAccess] = useState(null);
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

  const loadInboxPage = useCallback(async ({ cursor = null, replace = false } = {}) => {
    const params = new URLSearchParams({ limit: String(INBOX_PAGE_SIZE) });
    if (cursor) params.set("cursor", cursor);
    const response = await api(`/inbox?${params.toString()}`);
    const page = Object.fromEntries(CHANNELS.map((channel) => [channel.id, []]));
    for (const row of response?.items ?? []) {
      const channel = row.channel || "webchat";
      if (!page[channel]) continue;
      page[channel].push(toConversation(row, getChannel(channel)));
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
  }, [demoAccount]);

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
    api("/integrations")
      .then((rows) => {
        if (!alive) return;
        setIntegrations(Array.isArray(rows) ? rows : []);
        setIntegrationAccess(true);
      })
      .catch(() => {
        // Integration status is settings-scoped. Inbox-only roles can still
        // work with channels represented by conversations they can access.
        if (!alive) return;
        setIntegrations([]);
        setIntegrationAccess(false);
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
    if (demoAccount) return CHANNELS.map((channel) => ({ ...channel, connected: true }));
    const connected = integrationAccess
      ? new Set((integrations || [])
        .filter((row) => ["connected", "active"].includes(String(row.status || "").toLowerCase()))
        .map((row) => row.provider))
      : new Set(Object.entries(convMap).filter(([, rows]) => rows.length > 0).map(([channelId]) => channelId));
    return CHANNELS.map((channel) => ({ ...channel, connected: connected.has(channel.id) }));
  }, [convMap, demoAccount, integrationAccess, integrations]);

  useEffect(() => {
    if (integrationAccess === null) return;
    const selected = channels.find((channel) => channel.id === activeChannel);
    if (selected?.connected) return;
    const firstConnected = channels.find((channel) => channel.connected);
    if (firstConnected) {
      setActiveChannel(firstConnected.id);
      setActiveId(null);
    }
  }, [activeChannel, channels, integrationAccess]);

  const channel = getChannel(activeChannel);
  const isWhatsApp = activeChannel === "whatsapp";
  const isTelegram = activeChannel === "telegram";
  const isFacebook = activeChannel === "facebook";
  const isInstagram = activeChannel === "instagram";
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
  const visibleConversations = isInstagram
    ? filtered.filter((conversation) => (conversation.folder || "primary") === instagramFolder)
    : filtered;
  const current = visibleConversations.find((conversation) => conversation.id === activeId) || visibleConversations[0] || null;
  activeMessageRequestRef.current = { conversationId: current?.id ?? null, channelId: activeChannel };
  const pendingApproval = current?.approval || null;
  const connectedCount = channels.filter((item) => item.connected).length;
  const unreadByChannel = Object.fromEntries(
    Object.entries(convMap).map(([id, rows]) => [id, rows.reduce((count, row) => count + row.unread, 0)])
  );
  const instagramAccountIdentity = integrations?.find((integration) => integration.provider === "instagram" && ["active", "connected"].includes(String(integration.status || "").toLowerCase()))?.display_name?.trim() || "";

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

  async function handleSend(conversationId, text) {
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
    setSending(true);
    setError(null);
    try {
      const sent = await api(`/conversations/${conversationId}/messages`, {
        method: "POST",
        body: { body: text },
      });
      const createdAt = sent?.created_at || new Date().toISOString();
      const localMessage = {
        id: sent?.id || `${conversationId}-${Date.now()}`,
        side: "out",
        text,
        time: displayTime(createdAt),
        createdAt,
        status: sent?.status || "queued",
      };
      setConvMap((previous) => ({
        ...previous,
        [activeChannel]: (previous[activeChannel] || []).map((row) => row.id === conversationId
          ? { ...row, preview: text, messages: [...(row.messages || []), localMessage] }
          : row),
      }));
      return true;
    } catch (e) {
      setError(e?.message || "Could not send the message.");
      return false;
    } finally {
      setSending(false);
    }
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

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      {error && (
        <div role="alert" className="mb-3 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          {error}
        </div>
      )}
      {approvalLoadError && (
        <div role="alert" className="mb-3 flex items-center justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          <span>{approvalLoadError}</span>
          <button type="button" onClick={() => void reloadApprovals().catch((e) => setApprovalLoadError(e?.message || "Could not load pending approvals."))} className="shrink-0 underline">{t("common.retry", "Retry")}</button>
        </div>
      )}

      <div dir="ltr" className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_52px] overflow-hidden">
      <div className="flex h-full min-h-0 min-w-0 flex-col">
      {isInstagram && <InstagramModeTabs active={instagramMode} lang={lang} onChange={setInstagramMode} />}
      {isInstagram && instagramMode === "comments" ? (
        <InstagramPostsWorkspace posts={instagramPosts} lang={lang} onReply={addInstagramPageReply} />
      ) : isFacebook ? (
        <FacebookPostsWorkspace posts={facebookPosts} lang={lang} onReply={addFacebookPageReply} onComment={addFacebookPageComment} />
      ) : (
      <div
        ref={inboxSplitRef}
        dir="ltr"
        style={isWhatsApp ? { "--inbox-chat-list-width": `${chatListWidth}px` } : undefined}
        className={cn(
          "grid min-h-0 flex-1 grid-cols-1",
          isWhatsApp
            ? "grid-rows-[minmax(0,1fr)] lg:grid-cols-[var(--inbox-chat-list-width)_5px_minmax(0,1fr)] lg:gap-0"
            : isTelegram
              ? "gap-0 lg:grid-cols-[clamp(285px,17vw,330px)_minmax(0,1fr)] lg:grid-rows-1 grid-rows-[minmax(180px,30dvh)_minmax(0,1fr)] sm:grid-rows-[minmax(240px,32dvh)_minmax(0,1fr)]"
              : isInstagram
                ? "gap-0 lg:grid-cols-[350px_minmax(0,1fr)] lg:grid-rows-1 grid-rows-[minmax(180px,30dvh)_minmax(0,1fr)] sm:grid-rows-[minmax(240px,32dvh)_minmax(0,1fr)]"
            : "gap-3 lg:grid-cols-[clamp(320px,28vw,440px)_minmax(0,1fr)] lg:grid-rows-1 lg:gap-3 grid-rows-[minmax(180px,30dvh)_minmax(0,1fr)] sm:grid-rows-[minmax(240px,32dvh)_minmax(0,1fr)]"
        )}
      >
        <div className={cn(
          "bg-card border flex-col min-h-0 overflow-hidden",
          isWhatsApp ? "rounded-none border-0 bg-white" : isTelegram ? "rounded-none border-0 border-r border-[#e4e9ec] bg-white" : isInstagram ? "rounded-none border-0 border-r border-[#dbdbdb] bg-white" : "rounded-2xl border-border",
          isWhatsApp && mobileChatOpen ? "hidden lg:flex" : "flex"
        )}>
          <div className={cn(isTelegram ? "space-y-0 p-2" : isInstagram ? "space-y-3 px-4 pb-3 pt-4" : "space-y-2.5 p-3", isWhatsApp ? "border-b border-[#d1d7db]" : isTelegram ? "border-b border-[#e4e9ec]" : isInstagram ? "border-b border-[#dbdbdb]" : "border-b border-border")}>
            {isInstagram && <div className="flex items-center justify-between"><h2 className="text-[19px] font-semibold tracking-tight text-[#262626]">{lang === "ar" ? "الرسائل" : "Messages"}</h2>{instagramAccountIdentity && <span dir="ltr" className="text-[12px] font-semibold text-[#8e8e8e]">{instagramAccountIdentity.startsWith("@") ? instagramAccountIdentity : `@${instagramAccountIdentity}`}</span>}</div>}
            <div className="relative">
              <Search className={cn("absolute top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground", (isWhatsApp || isInstagram) && lang === "ar" ? "right-3" : "left-3")} />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                dir={isWhatsApp || isInstagram ? (lang === "ar" ? "rtl" : "ltr") : undefined}
                aria-label={t("inbox.search")}
                placeholder={t("inbox.search")}
                className={cn(
                  "w-full h-9 text-[13px] placeholder:text-muted-foreground focus:outline-hidden focus:ring-2 focus:ring-ring/30",
                  isTelegram ? "h-9 rounded-full border border-transparent bg-[#f1f1f1]" : "rounded-lg",
                  isWhatsApp && lang === "ar" ? "pr-9 pl-3 text-right" : isInstagram && lang === "ar" ? "pr-9 pl-3 text-right" : "pl-9 pr-3",
                  isWhatsApp ? "bg-[#f0f2f5] border border-[#f0f2f5]" : isInstagram ? "bg-[#efefef] border border-[#efefef] rounded-lg" : !isTelegram && "bg-surface border border-border"
                )}
              />
            </div>
            {isInstagram ? (
              <div role="tablist" aria-label={lang === "ar" ? "مجلدات الرسائل" : "Message folders"} className="flex items-center justify-between gap-1">
                {instagramFolders.map((folder) => <button key={folder.id} type="button" role="tab" aria-selected={instagramFolder === folder.id} onClick={() => { setInstagramFolder(folder.id); setActiveId(null); }} className={cn("whitespace-nowrap px-2 py-1.5 text-[12px] font-semibold", instagramFolder === folder.id ? "border-b-2 border-[#262626] text-[#262626]" : "border-b-2 border-transparent text-[#8e8e8e] hover:text-[#262626]")}>{folder.label}</button>)}
              </div>
            ) : !isTelegram && <div className={cn("flex gap-1", isWhatsApp && "-mb-3 border-b border-[#d1d7db]")}>
              {FILTERS.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  aria-pressed={filter === item.id}
                  onClick={() => setFilter(item.id)}
                  className={cn(
                    "whitespace-nowrap transition-colors",
                    isWhatsApp
                      ? cn("px-2.5 py-2 text-[12px]", filter === item.id ? "border-b-2 border-[#00a884] font-semibold text-[#008f72]" : "border-b-2 border-transparent text-[#667781] hover:text-[#111b21]")
                      : cn("px-2.5 py-1 rounded-md text-[12px] font-medium", filter === item.id ? "bg-primary text-primary-foreground" : "bg-surface text-muted-foreground hover:text-foreground")
                  )}
                >
                  {item.label}
                </button>
              ))}
            </div>}
          </div>
          <div
            className={cn(
              "flex-1 overflow-y-auto scrollbar-thin",
              (isWhatsApp || isInstagram) && "bg-white",
              isTelegram && "telegram-transient-scrollbar",
              isTelegram && telegramListScrolling && "is-scrolling"
            )}
            onScroll={(event) => {
              const node = event.currentTarget;
              if (isTelegram) {
                setTelegramListScrolling(true);
                clearTimeout(telegramListScrollTimerRef.current);
                telegramListScrollTimerRef.current = setTimeout(() => setTelegramListScrolling(false), 800);
              }
              if (node.scrollHeight - node.scrollTop - node.clientHeight < 120) void loadMoreConversations();
            }}
          >
            {loadingInbox ? (
              <div className="py-10 text-center px-4 text-[13px] text-muted-foreground">{t("common.loading")}</div>
            ) : inboxLoadError ? (
              <div role="alert" className="m-3 rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-center text-[12.5px] text-destructive">
                <p>{inboxLoadError}</p>
                <button type="button" onClick={() => setInboxRetryAttempt((attempt) => attempt + 1)} className="mt-2 font-medium underline">
                  {t("common.retry", "Retry")}
                </button>
              </div>
            ) : visibleConversations.length === 0 ? (
              <div className="py-8 text-center px-4">
                <p className="text-[13px] text-muted-foreground">{t("inbox.noConversations")}</p>
              </div>
            ) : visibleConversations.map((conversation) => (
              <button
                key={conversation.id}
                type="button"
                aria-pressed={current?.id === conversation.id}
                onClick={() => { selectConversation(conversation); if (isWhatsApp) setMobileChatOpen(true); }}
                className={cn(
                  "w-full flex border-b transition-colors",
                  isTelegram ? "min-h-[58px] gap-2 px-2 py-1.5" : isInstagram ? "min-h-[68px] gap-3 px-4 py-2" : "gap-3 px-3 py-2.5",
                  isWhatsApp ? "border-[#e9edef] hover:bg-[#f5f6f6]" : isTelegram ? "border-[#edf0f2] hover:bg-[#f4f7f9]" : isInstagram ? "border-transparent hover:bg-[#fafafa]" : "border-border/60 hover:bg-surface/60",
                  isWhatsApp || isTelegram || isInstagram ? (lang === "ar" ? "text-right" : "text-left") : "text-left",
                  current?.id === conversation.id && (isWhatsApp ? "bg-[#f0f2f5]" : isTelegram ? "bg-[#419fd9] text-white hover:bg-[#419fd9]" : isInstagram ? "bg-[#efefef]" : "bg-primary/5")
                )}
              >
                <div className="relative shrink-0">
                  {isInstagram ? (
                    <div className={cn("rounded-full p-[2px]", (conversation.hasStory || conversation.story?.available || conversation.story_available) ? "bg-[conic-gradient(from_45deg,#feda75,#fa7e1e,#d62976,#962fbf,#4f5bd5,#feda75)]" : "border border-[#dbdbdb]")}><ConversationAvatar conversation={conversation} className={cn("h-11 w-11 text-[13px]", (conversation.hasStory || conversation.story?.available || conversation.story_available) && "border-2 border-white")} /></div>
                  ) : isTelegram ? (
                    <ConversationAvatar conversation={conversation} className="h-10 w-10 text-[12px]" />
                  ) : (
                    <div className={cn("rounded-full grid place-items-center text-[12px] font-semibold text-white", isWhatsApp ? "h-12 w-12 text-[#54656f]" : "h-11 w-11")} style={{ background: conversation.color, color: isWhatsApp ? "#54656f" : "#fff" }}>
                      {conversation.initials}
                    </div>
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <span dir={isWhatsApp || isTelegram ? "auto" : undefined} className={cn("truncate", isWhatsApp ? "text-[14px] font-medium text-[#111b21]" : isTelegram ? "text-[14px] font-medium" : "text-[13px] font-medium")}>{conversation.customer}</span>
                    <span dir={isWhatsApp || isTelegram || isInstagram ? "ltr" : undefined} className={cn("shrink-0", isWhatsApp ? "text-[11px] text-[#667781]" : isTelegram ? current?.id === conversation.id ? "text-[11px] text-white/85" : "text-[11px] text-[#7f9db8]" : isInstagram ? "text-[10.5px] text-[#8e8e8e]" : "text-[11px] text-muted-foreground")}>{conversation.time}</span>
                  </div>
                  {isInstagram ? (
                    <div className="mt-0.5 flex min-w-0 items-center gap-2"><p dir="auto" className="min-w-0 flex-1 truncate text-[11.5px] text-[#8e8e8e]">{conversation.preview}</p>{conversation.unread > 0 && <span aria-label={lang === "ar" ? "رسائل غير مقروءة" : "Unread message"} className="h-1.5 w-1.5 shrink-0 rounded-full bg-[#0095f6]" />}</div>
                  ) : isTelegram ? (
                    <div className="mt-0.5 flex min-w-0 items-center gap-1.5">
                      <p dir="auto" className={cn("min-w-0 flex-1 truncate text-[11.5px]", current?.id === conversation.id ? "text-white/90" : "text-[#7b8d9b]")}>{conversation.preview}</p>
                      {conversation.unread > 0 && <span className="min-w-5 rounded-full bg-[#2aabee] px-1.5 py-0.5 text-center text-[10px] font-semibold tabular-nums text-white">{conversation.unread}</span>}
                    </div>
                  ) : <p dir={isWhatsApp ? "auto" : undefined} className={cn("truncate mt-0.5", isWhatsApp ? "text-[12px] text-[#667781]" : "text-[12px] text-muted-foreground")}>{conversation.preview}</p>}
                  {!isTelegram && !isInstagram && <div className="mt-1 flex items-center gap-1.5">
                    <span className={cn("px-1.5 py-0.5 text-[10px]", isWhatsApp ? "rounded-full bg-[#f0f2f5] text-[#667781]" : "rounded-md bg-surface text-muted-foreground")}>
                      {t(`inbox.status.${conversation.status}`)}
                    </span>
                    {conversation.unread > 0 && (
                      <span className={cn("ml-auto text-[10px] font-semibold px-1.5 py-0.5 tabular-nums", isWhatsApp ? "min-w-5 rounded-full bg-[#25d366] text-center text-white" : isTelegram ? "min-w-5 rounded-full bg-[#2aabee] text-center text-white" : "rounded-md bg-primary text-primary-foreground")}>
                        {conversation.unread}
                      </span>
                    )}
                  </div>}
                </div>
              </button>
            ))}
            {(loadingMoreInbox || inboxMoreError || inboxCursor) && (
              <div className="px-3 py-2 text-center text-[11.5px] text-muted-foreground">
                {inboxMoreError ? (
                  <button type="button" onClick={() => void loadMoreConversations()} className="text-primary hover:underline">{t("common.retry", "Retry")}</button>
                ) : loadingMoreInbox ? t("common.loading") : (
                  <button type="button" onClick={() => void loadMoreConversations()} className="text-primary hover:underline">{t("inbox.loadMore", "Load more conversations")}</button>
                )}
              </div>
            )}
          </div>
          {integrations && connectedCount === 0 && (
            <p className="shrink-0 border-t border-border px-3 py-2 text-[11px] leading-relaxed text-muted-foreground">
              {t("inbox.noConnectedChannels", "Connect a channel in Settings → Channels to start receiving messages.")}
            </p>
          )}
        </div>

        {isWhatsApp && (
          <div
            role="separator"
            aria-label={lang === "ar" ? "تغيير عرض قائمة المحادثات" : "Resize conversation list"}
            aria-orientation="vertical"
            aria-valuemin={CHAT_LIST_MIN_WIDTH}
            aria-valuemax={CHAT_LIST_MAX_WIDTH}
            aria-valuenow={chatListWidth}
            tabIndex={0}
            className={cn(
              "group relative hidden cursor-col-resize touch-none select-none border-x border-[#d1d7db] bg-[#f7f5f3] outline-none transition-colors hover:bg-[#e8f5ef] focus-visible:bg-[#e8f5ef] lg:block",
              isResizingChatList && "bg-[#e8f5ef]"
            )}
            onPointerDown={handleResizePointerDown}
            onPointerMove={handleResizePointerMove}
            onPointerUp={finishChatListResize}
            onPointerCancel={finishChatListResize}
            onLostPointerCapture={() => finishChatListResize()}
            onKeyDown={handleResizeKeyDown}
          >
            <span className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-[#d1d7db] transition-colors group-hover:bg-[#00a884] group-focus-visible:bg-[#00a884]" />
          </div>
        )}

        <ChannelChat
          channel={channel}
          lang={lang}
          className={isWhatsApp && !mobileChatOpen ? "hidden lg:flex" : ""}
          onBack={isWhatsApp ? () => setMobileChatOpen(false) : undefined}
          conversation={current}
          approval={pendingApproval}
          loadingMessages={loadingMessages}
          loadingOlderMessages={loadingOlderMessages}
          hasOlderMessages={Boolean(messageCursor)}
          onLoadOlderMessages={loadOlderMessages}
          messagesError={messagesError?.conversationId === current?.id && messagesError?.channelId === activeChannel ? messagesError.message : ""}
          onRetryMessages={() => setMessageRetryAttempt((attempt) => attempt + 1)}
          sending={sending}
          pendingDecision={pendingDecision}
          error={null}
          t={t}
          onSend={handleSend}
          onApprove={() => decideApproval(pendingApproval, "APPROVED")}
          onDecline={() => decideApproval(pendingApproval, "REJECTED")}
        />
      </div>
      )}
      </div>
      <aside className="z-10 flex min-h-0 min-w-0 flex-col items-center border-l border-border/80 bg-card" aria-label={t("inbox.title")}>
        <ChannelSwitcher
          channels={channels}
          active={activeChannel}
          unreadByChannel={unreadByChannel}
          onSelect={(id) => { setActiveChannel(id); setActiveId(null); setMobileChatOpen(false); setFilter("all"); }}
        />
      </aside>
      </div>
    </div>
  );
}
