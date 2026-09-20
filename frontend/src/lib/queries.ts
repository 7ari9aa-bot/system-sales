"use client";

/** TanStack Query hooks — كل حالة السيرفر من هنا (مفيش global store).
 *  Query keys موحدة + إعادة جلب في الخلفية + optimistic فقط للقراءة/التعليم كمقروء. */

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  keepPreviousData,
  type InfiniteData,
  type QueryKey,
} from "@tanstack/react-query";
import { api, getTokens } from "@/lib/api";
import { authPost, type AuthResult } from "@/lib/auth-api";
import { t } from "@/lib/t";
import { toast } from "@/components/ui/toast";

/* ------------------------------------------------------------------ types */

/** Server list envelope used by conversations / messages / customers / orders. */
export type Page<T> = { items: T[]; next_cursor: string | null };

export type Me = { id: string; email: string; tenants?: { id: string }[] };

export type DashboardData = {
  orders: { orders_count: number; revenue: number; aov: number };
  ai_orders_30d: number;
  conversations: { open: number; unread: number };
  customers: number;
  products_active: number;
  low_stock: number;
  daily_orders: { day: string; orders: number; revenue: number }[];
  revenue_by_source: { source: string; revenue: number; conversions: number }[];
};

export type Conversation = {
  id: string;
  customer_id: string;
  customer_name?: string | null;
  customer_phone?: string | null;
  channel: string;
  status: string;
  unread_count: number;
  /** من يسأل عن هذه المحادثة — يُستخدم في "شغلي". */
  assignee_user_id: string | null;
  last_message_at: string | null;
};

export type Message = {
  id: string;
  direction: "inbound" | "outbound";
  sender_type: string;
  body: string | null;
  media_url: string | null;
  media_type: string | null;
  status: string;
  created_at: string;
};

export type Variant = { id: string; title: string | null; sku: string | null; price: string };

export type Product = {
  id: string;
  title: string;
  slug: string;
  status: string;
  variants?: Variant[];
};

export type Customer = {
  id: string;
  name: string;
  phone: string | null;
  email: string | null;
  lifetime_value: string;
  is_blocked: boolean;
};

/* ---------------------------------------------------- Customer 360 (W5) -- */

export type CustomerTag = { id: string; name: string; color: string | null };
export type CustomerIdentity = { id: string; channel: string; external_id: string };

export type CustomerAddress = {
  id: string;
  label: string | null;
  line1: string | null;
  line2: string | null;
  city: string | null;
  region: string | null;
  postal_code: string | null;
  country: string | null;
  is_default: boolean;
};

export type CustomerNote = {
  id: string;
  body: string;
  author_user_id: string | null;
  created_at: string | null;
};

export type Customer360Order = {
  id: string;
  number: string;
  status: string;
  currency: string;
  grand_total: string;
  channel: string | null;
  placed_at: string | null;
  created_at: string | null;
};

export type Customer360Conversation = {
  id: string;
  channel: string;
  status: string;
  unread_count: number;
  assignee_user_id: string | null;
  last_message_at: string | null;
  created_at: string | null;
};

export type Customer360Task = {
  id: string;
  title: string;
  status: string;
  priority: number;
  source: string;
  assignee_user_id: string | null;
  due_date: string | null;
  created_at: string | null;
};

/** One merged, newest-first stream across every source. */
export type CustomerTimelineEntry = {
  kind: "event" | "order" | "conversation" | "note" | "task";
  at: string;
  title: string | null;
  subtitle: string | null;
  ref_id: string | null;
  meta: Record<string, unknown>;
};

export type CustomerPayments = {
  currency: string;
  orders_total: string;
  paid_total: string;
  refunded_total: string;
  net_collected: string;
  outstanding: string;
  payment_count: number;
};

export type Customer360Stats = {
  orders_shown: number;
  conversations_shown: number;
  tasks_shown: number;
  open_tasks: number;
  unread_messages: number;
  event_count: number;
  net_collected: string | null;
  outstanding: string | null;
  last_order_at: string | null;
  last_message_at: string | null;
};

export type Customer360 = {
  customer: Customer & {
    locale: string | null;
    extra: Record<string, unknown>;
    deleted_at: string | null;
    created_at: string | null;
    updated_at: string | null;
  };
  tags: CustomerTag[];
  identities: CustomerIdentity[];
  addresses: CustomerAddress[];
  notes: CustomerNote[];
  orders: Customer360Order[];
  conversations: Customer360Conversation[];
  tasks: Customer360Task[];
  payments: CustomerPayments;
  stats: Customer360Stats;
  timeline: CustomerTimelineEntry[];
};

export type Order = {
  id: string;
  number: string;
  customer_id: string;
  status: string;
  grand_total: string;
  currency: string;
  placed_at: string | null;
  created_at: string;
};

export type Balance = { variant_id: string; warehouse_id: string; on_hand: number; reserved: number };

export type Movement = {
  id: string;
  variant_id: string;
  direction: string;
  quantity: number;
  reason: string;
  balance_after: number;
  created_at: string;
};

export type Campaign = { id: string; name: string; provider: string; status: string; budget: string | null };

export type MarketingSummary = {
  orders_summary: { orders_count: number; revenue: number; aov: number };
  revenue_by_source: { source: string; revenue: number; conversions: number }[];
  revenue_by_campaign: { campaign_id: string; campaign_name: string; revenue: number; conversions: number }[];
  campaign_roas: { campaign_id: string; name: string; spend: number; revenue: number; roas: number | null }[];
};

export type KnowledgeItem = { id: string; title: string; status: string; created_at: string };
export type Agent = { id: string; name: string; model: string | null; is_active: boolean };
export type UsageRow = { date: string; tokens_in: number; tokens_out: number; cost: number };
export type SearchHit = { id: string; title: string; distance: number };
export type GlobalSearchHit = { entity_type: string; entity_id: string; title: string; snippet: string | null };
export type Invitation = { id: string; email: string; status: string; role_code: string | null; token?: string };
export type Integration = { id: string; provider: string; kind: string; status: string };
export type Task = {
  id: string;
  title: string;
  status: "todo" | "in_progress" | "done" | "cancelled";
  priority: number;
  assignee_user_id: string | null;
  due_date: string | null;
  source: string;
};

/** §46 — one conversation's first-response SLA clock (`GET /sla/risk`). */
export type SlaRiskItem = {
  id: string;
  conversation_id: string;
  kind: string;
  status: string;
  deadline_at: string | null;
  /** Minutes until the deadline; negative once breached, null if no deadline. */
  minutes_remaining: number | null;
  at_risk: boolean;
};

/** §135 — a parked HIGH-risk tool call awaiting a human decision. */
export type Approval = {
  id: string;
  status: string;
  action: string;
  risk_level: string;
  entity_type: string | null;
  entity_id: string | null;
  conversation_id: string | null;
  run_id: string | null;
  payload: Record<string, unknown>;
  requested_by: string | null;
  expires_at: string | null;
  decided_at: string | null;
  consumed_at: string | null;
  rejection_reason: string | null;
  created_at: string | null;
};

/** §103 — per-subsystem status. Worst status wins at the envelope level. */
export type HealthStatus = "healthy" | "degraded" | "down";

export type HealthSubsystem = {
  name: string;
  status: HealthStatus;
  /** Short, non-sensitive description (fixed strings plus counts and ages). */
  detail?: string;
  /** Present on the `integrations` row only: provider + rolled-up status. */
  integrations?: { provider: string; status: HealthStatus }[];
};

export type PlatformHealth = {
  status: HealthStatus;
  subsystems: HealthSubsystem[];
};

/* ------------------------------------------------------------------ keys */

export const qk = {
  me: ["me"] as QueryKey,
  dashboard: ["analytics", "dashboard"] as QueryKey,
  conversations: ["conversations"] as QueryKey,
  messages: (id: string) => ["conversations", id, "messages"] as QueryKey,
  orders: ["orders"] as QueryKey,
  products: ["products"] as QueryKey,
  customers: ["customers"] as QueryKey,
  customer360: (id: string) => ["customer", id, "360"] as QueryKey,
  balances: ["inventory", "balances"] as QueryKey,
  movements: ["inventory", "movements"] as QueryKey,
  campaigns: ["marketing", "campaigns"] as QueryKey,
  marketingSummary: ["analytics", "summary"] as QueryKey,
  knowledge: ["ai", "knowledge"] as QueryKey,
  agents: ["ai", "agents"] as QueryKey,
  usage: ["ai", "usage"] as QueryKey,
  invitations: ["invitations"] as QueryKey,
  integrations: ["integrations"] as QueryKey,
  tasks: ["operations", "tasks"] as QueryKey,
  slaRisk: ["operations", "sla", "risk"] as QueryKey,
  approvals: (status: string) => ["ai", "approvals", status] as QueryKey,
  health: ["platform", "health"] as QueryKey,
};

function errMessage(err: unknown) {
  return err instanceof Error ? err.message : t.somethingWentWrong;
}

/* ------------------------------------------------------------------ queries */

export function useMe() {
  return useQuery({
    queryKey: qk.me,
    queryFn: () => api<Me>("/auth/me"),
    enabled: typeof window !== "undefined" && !!getTokens(),
    staleTime: 60_000,
    retry: false,
  });
}

export function useDashboard() {
  return useQuery({
    queryKey: qk.dashboard,
    queryFn: () => api<DashboardData>("/analytics/dashboard"),
    refetchInterval: 20_000, // نفس سلوك التحديث التلقائي القديم
  });
}

/** Page size for the inbox list — the API caps `limit` at 200. */
export const CONVERSATIONS_PAGE_SIZE = 50;

function withCursor(path: string, limit: number, cursor: string | null) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (cursor) params.set("cursor", cursor);
  return `${path}?${params.toString()}`;
}

/** Server-paginated inbox list — pages accumulate via `fetchNextPage`. */
export function useConversations() {
  return useInfiniteQuery<Page<Conversation>, Error, InfiniteData<Page<Conversation>>, QueryKey, string | null>({
    queryKey: qk.conversations,
    queryFn: ({ pageParam }) =>
      api<Page<Conversation>>(withCursor("/conversations", CONVERSATIONS_PAGE_SIZE, pageParam)),
    initialPageParam: null,
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    refetchInterval: 15_000,
  });
}

export function useMessages(conversationId: string | null) {
  return useQuery({
    queryKey: qk.messages(conversationId ?? ""),
    queryFn: () =>
      api<{ items: Message[] }>(`/conversations/${conversationId}/messages`).then((r) => r.items),
    enabled: !!conversationId,
    refetchInterval: 8_000,
  });
}

export function useOrders() {
  return useQuery({
    queryKey: qk.orders,
    queryFn: () => api<{ items: Order[] }>("/orders").then((r) => r.items),
  });
}

/** Cursor-paginated orders page — fetches a single bounded page (no full list).
 *
 *  Pass `customerId` to scope the query server-side. Filtering a global page
 *  in the browser silently hides a customer's older orders. */
export function useOrdersPage(
  opts: {
    limit?: number;
    cursor?: string | null;
    customerId?: string | null;
    enabled?: boolean;
  } = {},
) {
  const limit = opts.limit ?? 50;
  const cursor = opts.cursor ?? null;
  const customerId = opts.customerId ?? null;
  return useQuery({
    queryKey: [...qk.orders, "page", { limit, cursor, customerId }] as QueryKey,
    queryFn: () => {
      const params = new URLSearchParams({ limit: String(limit) });
      if (cursor) params.set("cursor", cursor);
      if (customerId) params.set("customer_id", customerId);
      return api<Page<Order>>(`/orders?${params.toString()}`);
    },
    enabled: opts.enabled ?? true,
  });
}

export function useProducts() {
  return useQuery({
    queryKey: qk.products,
    queryFn: () => api<Product[]>("/products"),
  });
}

export function useCustomers() {
  return useQuery({
    queryKey: qk.customers,
    queryFn: () => api<{ items: Customer[] }>("/customers").then((r) => r.items),
  });
}

export function useCustomer(id: string | null | undefined) {
  return useQuery<Customer>({
    queryKey: ["customer", id],
    queryFn: () => api<Customer>(`/customers/${id}`),
    enabled: Boolean(id),
  });
}

/** Spec W5 — the composed Customer 360 record in a single round trip.
 *
 *  The drawer and the record page both read this. Fetching the sections
 *  separately would mean the timeline could not be merged or ordered
 *  correctly client-side, and the orders list could not page. */
export function useCustomer360(id: string | null | undefined) {
  return useQuery<Customer360>({
    queryKey: qk.customer360(String(id)),
    queryFn: () => api<Customer360>(`/customers/${id}/360`),
    enabled: Boolean(id),
  });
}

export function useBalances() {
  return useQuery({
    queryKey: qk.balances,
    queryFn: () => api<Balance[]>("/inventory/balances"),
  });
}

export function useMovements() {
  return useQuery({
    queryKey: qk.movements,
    queryFn: () => api<Movement[]>("/inventory/movements"),
  });
}

export function useCampaigns() {
  return useQuery({
    queryKey: qk.campaigns,
    queryFn: () => api<{ items: Campaign[] }>("/marketing/campaigns").then((r) => r.items),
  });
}

export function useMarketingSummary() {
  return useQuery({
    queryKey: qk.marketingSummary,
    queryFn: () => api<MarketingSummary>("/analytics/summary"),
  });
}

export function useKnowledge() {
  return useQuery({
    queryKey: qk.knowledge,
    queryFn: () => api<{ items: KnowledgeItem[] }>("/ai/knowledge").then((r) => r.items),
  });
}

export function useAgents() {
  return useQuery({
    queryKey: qk.agents,
    queryFn: () => api<Agent[]>("/ai/agents"),
  });
}

export function useUsageSummary() {
  return useQuery({
    queryKey: qk.usage,
    queryFn: () => api<{ summary: UsageRow[] }>("/ai/usage/summary").then((r) => r.summary ?? []),
  });
}

export function useInvitations() {
  return useQuery({
    queryKey: qk.invitations,
    queryFn: () => api<Invitation[]>("/invitations"),
  });
}

export function useIntegrations() {
  return useQuery({
    queryKey: qk.integrations,
    queryFn: () => api<Integration[]>("/integrations"),
  });
}

export function useTasks() {
  return useQuery({
    queryKey: qk.tasks,
    queryFn: () => api<Task[]>("/tasks"),
  });
}

/** §46 — conversations whose first-response SLA is running or breached. */
export function useSlaRisk() {
  return useQuery({
    queryKey: qk.slaRisk,
    queryFn: () => api<{ items: SlaRiskItem[]; timezone: string }>("/sla/risk"),
    refetchInterval: 30_000,
  });
}

/** §135 — approvals parked awaiting a decision (defaults to the pending queue). */
export function useApprovals(status = "PENDING") {
  return useQuery({
    queryKey: qk.approvals(status),
    queryFn: () =>
      api<{ items: Approval[] }>(`/ai/approvals?status=${encodeURIComponent(status)}`).then(
        (r) => r.items,
      ),
    refetchInterval: 30_000,
  });
}

/** §103 — subsystem health for the top-bar indicator.
 *  A failing check must read as "unknown", never crash the shell, so we do not
 *  retry and let the caller fall back on missing data. */
export function usePlatformHealth() {
  return useQuery({
    queryKey: qk.health,
    queryFn: () => api<PlatformHealth>("/platform/health"),
    refetchInterval: 60_000,
    staleTime: 30_000,
    retry: false,
  });
}

/* ------------------------------------------------------------------ mutations */

export function useMarkConversationRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (conversationId: string) =>
      api(`/conversations/${conversationId}/read`, { method: "POST" }),
    // Optimistic UI — مسموح فقط للتعليم كمقروء
    onMutate: async (conversationId: string) => {
      await qc.cancelQueries({ queryKey: qk.conversations });
      const previous = qc.getQueryData<InfiniteData<Page<Conversation>>>(qk.conversations);
      if (previous) {
        qc.setQueryData<InfiniteData<Page<Conversation>>>(qk.conversations, {
          ...previous,
          pages: previous.pages.map((page) => ({
            ...page,
            items: page.items.map((c) => (c.id === conversationId ? { ...c, unread_count: 0 } : c)),
          })),
        });
      }
      return { previous };
    },
    onError: (_err, _id, ctx) => {
      if (ctx?.previous) qc.setQueryData(qk.conversations, ctx.previous);
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: qk.conversations });
      // جرس الإشعارات كمان لازم يتحدث لما المحادثة تتقري
      qc.invalidateQueries({ queryKey: ["notifications", "unread-count"] });
    },
  });
}

export function useSendMessage(conversationId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: string) =>
      api(`/conversations/${conversationId}/messages`, { method: "POST", body: { body } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.messages(conversationId) });
      qc.invalidateQueries({ queryKey: qk.conversations });
    },
    onError: (err) => toast({ title: t.replyFailed, description: errMessage(err), variant: "danger" }),
  });
}

export function useCreateOrder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { customer_id: string; items: { variant_id: string; quantity: number }[]; channel: string }) =>
      api<{ number: string }>("/orders", { method: "POST", body }),
    onSuccess: (created) => {
      toast({ title: `${t.orderCreated} ${created.number}`, description: t.orderCreatedHint, variant: "success" });
      qc.invalidateQueries({ queryKey: qk.orders });
      qc.invalidateQueries({ queryKey: qk.dashboard });
    },
    onError: (err) => toast({ title: t.somethingWentWrong, description: errMessage(err), variant: "danger" }),
  });
}

export function useCreateProduct() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { title: string; slug: string; price: number }) =>
      api("/products", { method: "POST", body }),
    onSuccess: () => {
      toast({ title: t.addProduct, description: t.products, variant: "success" });
      qc.invalidateQueries({ queryKey: qk.products });
      qc.invalidateQueries({ queryKey: qk.dashboard });
    },
    onError: (err) => toast({ title: t.somethingWentWrong, description: errMessage(err), variant: "danger" }),
  });
}

export function useRecordMovement() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { variant_id: string; warehouse_id: string; direction: string; quantity: number; reason: string }) =>
      api("/inventory/movements", { method: "POST", body }),
    onSuccess: () => {
      toast({ title: t.movementRecorded, variant: "success" });
      qc.invalidateQueries({ queryKey: qk.balances });
      qc.invalidateQueries({ queryKey: qk.movements });
      qc.invalidateQueries({ queryKey: qk.dashboard });
    },
    onError: (err) => toast({ title: t.somethingWentWrong, description: errMessage(err), variant: "danger" }),
  });
}

export function useCreateCampaign() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; provider: string; budget: number | null }) =>
      api("/marketing/campaigns", { method: "POST", body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.campaigns });
      qc.invalidateQueries({ queryKey: qk.marketingSummary });
    },
    onError: (err) => toast({ title: t.somethingWentWrong, description: errMessage(err), variant: "danger" }),
  });
}

export function useAddKnowledge() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { title: string; content: string }) =>
      api("/ai/knowledge", { method: "POST", body }),
    onSuccess: () => {
      toast({ title: t.knowledgeAdded, variant: "success" });
      qc.invalidateQueries({ queryKey: qk.knowledge });
    },
    onError: (err) => toast({ title: t.somethingWentWrong, description: errMessage(err), variant: "danger" }),
  });
}

export function useKnowledgeSearch() {
  return useMutation({
    mutationFn: (q: string) =>
      api<SearchHit[]>(`/ai/knowledge/search?q=${encodeURIComponent(q)}`),
    onError: (err) => toast({ title: t.somethingWentWrong, description: errMessage(err), variant: "danger" }),
  });
}

export function useGlobalSearch() {
  return useMutation({
    mutationFn: (query: string) =>
      api<GlobalSearchHit[]>(`/search?q=${encodeURIComponent(query)}&limit=8`),
  });
}

export function useCreateInvitation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: { email: string; role_code: string }) => {
      // نقرأ الـme من الكاش بدل نداء إضافي لكل دعوة
      const me = qc.getQueryData<Me>(qk.me);
      const tenant_id = me?.tenants?.[0]?.id ?? me?.id;
      if (!tenant_id) {
        throw new Error("مساحة العمل مش معروفة — حدّث الصفحة وحاول تاني.");
      }
      return api<Invitation>(`/tenants/${tenant_id}/invitations`, {
        method: "POST",
        body: { email: input.email, role_code: input.role_code },
      });
    },
    onSuccess: () => {
      toast({ title: t.invitationCreated, description: t.invitationCreatedHint, variant: "success" });
      qc.invalidateQueries({ queryKey: qk.invitations });
    },
    onError: (err) => toast({ title: t.somethingWentWrong, description: errMessage(err), variant: "danger" }),
  });
}

/** قبول دعوة — صفحة عامة (بدون توكن)، لذلك authPost وليس api() */
export function useAcceptInvitation() {
  return useMutation({
    mutationFn: async (input: { token: string; password: string; full_name: string }) => {
      const res = await authPost<{ email?: string }>("/invitations/accept", input).catch(
        (): AuthResult<{ email?: string }> => ({ ok: false, status: 0 }),
      );
      if (res.ok) return res.data;
      if (res.status === 0) {
        throw new Error("مش قادرين نوصل للسيرفر. اتأكد من اتصالك وحاول تاني.");
      }
      if (res.status === 404) {
        throw new Error("رابط الدعوة غير صحيح أو انتهت صلاحيته.");
      }
      if (res.status === 409) {
        throw new Error("البريد ده متسجل بالفعل — سجّل الدخول بدل ما تقبل الدعوة تاني.");
      }
      if (res.status === 400) {
        throw new Error(res.message ?? "بيانات غير صحيحة — راجع الحقول وحاول تاني.");
      }
      throw new Error(res.message ?? "حصلت مشكلة غير متوقعة. حاول مرة تانية.");
    },
  });
}

export function useRevokeInvitation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (invitationId: string) =>
      api<void>(`/invitations/${invitationId}`, { method: "DELETE" }),
    onSuccess: () => {
      toast({ title: "تم إلغاء الدعوة", variant: "default" });
      qc.invalidateQueries({ queryKey: qk.invitations });
    },
    onError: (err) => toast({ title: t.somethingWentWrong, description: errMessage(err), variant: "danger" }),
  });
}

export function useCreateTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { title: string; description?: string; priority: number }) =>
      api<{ id: string; status: string }>("/tasks", { method: "POST", body }),
    onSuccess: () => {
      toast({ title: t.taskCreated, variant: "success" });
      qc.invalidateQueries({ queryKey: qk.tasks });
    },
    onError: (err) => toast({ title: t.somethingWentWrong, description: errMessage(err), variant: "danger" }),
  });
}

export function useUpdateTaskStatus() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ taskId, status }: { taskId: string; status: Task["status"] }) =>
      api(`/tasks/${taskId}/status`, { method: "POST", body: { status } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.tasks }),
    onError: (err) => toast({ title: t.somethingWentWrong, description: errMessage(err), variant: "danger" }),
  });
}

/* ---------------------------------------------------------------- notifications */

export type Notification = {
  id: string;
  kind: string;
  title: string | null;
  body: string;
  action_url: string | null;
  payload: Record<string, unknown>;
  read_at: string | null;
  created_at: string;
};

export function useNotifications(opts: { unread_only?: boolean; limit?: number } = {}) {
  const params = new URLSearchParams();
  if (opts.unread_only) params.set("unread_only", "true");
  if (opts.limit) params.set("limit", String(opts.limit));
  const qs = params.toString() ? `?${params}` : "";
  return useQuery<Notification[]>({
    queryKey: ["notifications", opts],
    queryFn: () => api<Notification[]>(`/notifications${qs}`),
    staleTime: 30_000,
  });
}

export function useUnreadCount() {
  return useQuery<{ count: number }>({
    queryKey: ["notifications", "unread-count"],
    queryFn: () => api<{ count: number }>("/notifications/unread-count"),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
}

export function useMarkRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      api(`/notifications/${id}/read`, { method: "PATCH" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notifications"] });
    },
  });
}

export function useMarkAllRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api("/notifications/mark-all-read", { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notifications"] });
    },
  });
}

export { keepPreviousData };
