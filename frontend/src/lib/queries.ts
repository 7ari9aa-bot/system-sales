"use client";

/** TanStack Query hooks — كل حالة السيرفر من هنا (مفيش global store).
 *  Query keys موحدة + إعادة جلب في الخلفية + optimistic فقط للقراءة/التعليم كمقروء. */

import {
  useMutation,
  useQuery,
  useQueryClient,
  keepPreviousData,
  type QueryKey,
} from "@tanstack/react-query";
import { api, getTokens } from "@/lib/api";
import { t } from "@/lib/t";
import { toast } from "@/components/ui/toast";

/* ------------------------------------------------------------------ types */

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

/* ------------------------------------------------------------------ keys */

export const qk = {
  me: ["me"] as QueryKey,
  dashboard: ["analytics", "dashboard"] as QueryKey,
  conversations: ["conversations"] as QueryKey,
  messages: (id: string) => ["conversations", id, "messages"] as QueryKey,
  orders: ["orders"] as QueryKey,
  products: ["products"] as QueryKey,
  customers: ["customers"] as QueryKey,
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

export function useConversations() {
  return useQuery({
    queryKey: qk.conversations,
    queryFn: () => api<{ items: Conversation[] }>("/conversations").then((r) => r.items),
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

/* ------------------------------------------------------------------ mutations */

export function useMarkConversationRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (conversationId: string) =>
      api(`/conversations/${conversationId}/read`, { method: "POST" }),
    // Optimistic UI — مسموح فقط للتعليم كمقروء
    onMutate: async (conversationId: string) => {
      await qc.cancelQueries({ queryKey: qk.conversations });
      const previous = qc.getQueryData<Conversation[]>(qk.conversations);
      if (previous) {
        qc.setQueryData<Conversation[]>(
          qk.conversations,
          previous.map((c) => (c.id === conversationId ? { ...c, unread_count: 0 } : c)),
        );
      }
      return { previous };
    },
    onError: (_err, _id, ctx) => {
      if (ctx?.previous) qc.setQueryData(qk.conversations, ctx.previous);
    },
    onSettled: () => qc.invalidateQueries({ queryKey: qk.conversations }),
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
      const me = await api<Me>("/auth/me");
      const tenant_id = me.tenants?.[0]?.id ?? me.id;
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
