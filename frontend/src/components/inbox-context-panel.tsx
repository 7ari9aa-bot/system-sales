"use client";

/** §99 — the inbox context panel: the right-hand rail is now tabbed
 *  (العميل / الطلبات / الجدول الزمني / الذكاء / ملاحظات) instead of a single
 *  static customer card.
 *
 *  Data-source honesty:
 *  - العميل      → GET /customers/{id} (lightweight, always loaded).
 *  - الطلبات     → GET /customers/{id}/360 (orders section, server-scoped).
 *  - الجدول الزمني → the same 360 payload's merged timeline.
 *  - ملاحظات      → the same 360 payload's notes (read-only; POST
 *    /customers/{id}/notes exists but adding notes is out of §99 scope).
 *  - الذكاء      → DISABLED (قريبًا): there is no customer-scoped AI-runs
 *    endpoint yet (only run/correlation-scoped /ai/trace/*), so rendering the
 *    tab would mean faking data.
 *
 *  The 360 query mounts only when a 360-backed tab is first opened (Radix
 *  unmounts inactive content), so opening a conversation costs one light
 *  request, not the full record. */

import * as React from "react";
import Link from "next/link";
import {
  Clock,
  History,
  Mail,
  MessageSquare,
  NotebookPen,
  Phone,
  ShoppingBag,
  Sparkles,
  StickyNote,
  User,
  Wallet,
  ClipboardList,
} from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useCustomer, useCustomer360, useTenantCurrency, type CustomerTimelineEntry } from "@/lib/queries";
import { formatMoney } from "@/lib/utils";
import { t } from "@/lib/t";
import { cn } from "@/lib/utils";

const CHANNEL_VARIANT: Record<string, "success" | "primary" | "default"> = {
  whatsapp: "success",
  telegram: "primary",
  webchat: "default",
};

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("ar-EG-u-nu-latn", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value));
}

function orderVariant(status: string): "default" | "primary" | "success" | "danger" {
  if (status === "delivered" || status === "completed" || status === "confirmed") return "success";
  if (status === "cancelled" || status === "refunded") return "danger";
  if (status === "shipped" || status === "processing") return "primary";
  return "default";
}

function timelineIcon(kind: CustomerTimelineEntry["kind"]) {
  switch (kind) {
    case "order":
      return <ShoppingBag className="size-3.5" />;
    case "conversation":
      return <MessageSquare className="size-3.5" />;
    case "note":
      return <StickyNote className="size-3.5" />;
    case "task":
      return <ClipboardList className="size-3.5" />;
    default:
      return <History className="size-3.5" />;
  }
}

function PanelEmpty({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
      {children}
    </div>
  );
}

/** العميل — the original card, unchanged in substance. */
function CustomerTab({
  customerId,
  channel,
}: {
  customerId: string;
  channel: string;
}) {
  const customerQuery = useCustomer(customerId);
  const customer = customerQuery.data;
  // §47: no hard-coded currency. The lifetime value is a Decimal string from
  // the backend; the currency comes from the tenant read, not from a literal.
  const currencyQuery = useTenantCurrency();
  const currency = currencyQuery.data?.currency ?? null;

  if (customerQuery.isLoading) {
    return (
      <div className="space-y-3" aria-busy="true" aria-label={t.loading}>
        <Skeleton className="mx-auto h-14 w-14 rounded-full" />
        <Skeleton className="mx-auto h-4 w-28" />
        <Skeleton className="h-16" />
      </div>
    );
  }

  return (
    <div className="space-y-3 text-xs">
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

      <div className="rounded-lg border border-border bg-muted/40 p-2.5 space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-muted-foreground flex items-center gap-1.5">
            <Phone className="size-3.5" /> {t.phone}
          </span>
          <span dir="ltr" className="font-medium">
            {customer?.phone || "—"}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-muted-foreground flex items-center gap-1.5">
            <Mail className="size-3.5" /> {t.email}
          </span>
          <span dir="ltr" className="font-medium truncate max-w-[140px]">
            {customer?.email || "—"}
          </span>
        </div>
      </div>

      <div className="rounded-lg border border-border bg-muted/40 p-2.5">
        <span className="text-muted-foreground">{t.c360LifetimeValue}</span>
        <div className="mt-1 text-base font-bold text-foreground" dir="ltr">
          {formatMoney(customer?.lifetime_value, currency)}
        </div>
      </div>

      <Button variant="outline" size="sm" asChild className="w-full text-xs justify-start">
        <Link href="/orders">
          <ShoppingBag className="size-3.5 me-2" />
          إنشاء طلب جديد
        </Link>
      </Button>
    </div>
  );
}

export function InboxContextPanel({
  customerId,
  channel,
  onOpenCustomerDrawer,
}: {
  customerId: string;
  channel: string;
  onOpenCustomerDrawer: () => void;
}) {
  return (
    <div className="flex flex-col border-s border-border bg-card/50 p-4 gap-3 overflow-y-auto">
      <div className="flex items-center justify-between border-b border-border pb-3">
        <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
          {t.customer360}
        </h3>
        <Button
          size="sm"
          variant="ghost"
          onClick={onOpenCustomerDrawer}
          className="text-xs text-primary gap-1 h-7 px-2"
        >
          عرض كامل
        </Button>
      </div>

      <Tabs defaultValue="customer" className="flex-1">
        <TabsList className="w-full">
          <TabsTrigger value="customer" className="text-xs px-2" data-testid="ctx-tab-customer">
            <User className="size-3.5" />
            {t.ctxCustomer}
          </TabsTrigger>
          <TabsTrigger value="orders" className="text-xs px-2" data-testid="ctx-tab-orders">
            <ShoppingBag className="size-3.5" />
            {t.ctxOrders}
          </TabsTrigger>
          <TabsTrigger value="timeline" className="text-xs px-2" data-testid="ctx-tab-timeline">
            <Clock className="size-3.5" />
            {t.ctxTimeline}
          </TabsTrigger>
          {/* §99: لا مصدر بيانات AI على مستوى العميل بعد — التبويب معطّل ولا
              يُزيّف أي بيانات (same honesty rule as the views rail). */}
          <TabsTrigger
            value="ai"
            disabled
            title={t.comingSoon}
            className="text-xs px-2"
            data-testid="ctx-tab-ai"
          >
            <Sparkles className="size-3.5" />
            {t.ctxAi}
          </TabsTrigger>
          <TabsTrigger value="notes" className="text-xs px-2" data-testid="ctx-tab-notes">
            <NotebookPen className="size-3.5" />
            {t.ctxNotes}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="customer" className="mt-3">
          <CustomerTab customerId={customerId} channel={channel} />
        </TabsContent>

        {/* الطلبات — server-scoped orders from the 360 read model. */}
        <TabsContent value="orders" className="mt-3">
          <OrdersTabContent customerId={customerId} />
        </TabsContent>

        {/* الجدول الزمني — merged newest-first stream from the 360 read model. */}
        <TabsContent value="timeline" className="mt-3">
          <TimelineTabContent customerId={customerId} />
        </TabsContent>

        {/* ملاحظات — read-only view of the customer's notes. */}
        <TabsContent value="notes" className="mt-3">
          <NotesTabContent customerId={customerId} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

/** Renders inside the active tab; the shared 360 query loads once for all three. */
function OrdersTabContent({ customerId }: { customerId: string }) {
  const query = useCustomer360(customerId);
  const orders = query.data?.orders ?? [];
  const payments = query.data?.payments;

  if (query.isLoading) {
    return (
      <div className="space-y-2" aria-busy="true" aria-label={t.loading}>
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-12" />
        ))}
      </div>
    );
  }
  if (!query.data) return <PanelEmpty>{t.customerNotFound}</PanelEmpty>;
  if (orders.length === 0) return <PanelEmpty>{t.c360OrdersEmpty}</PanelEmpty>;

  return (
    <div className="space-y-2 text-xs">
      {payments && (
        <div className="flex items-center justify-between rounded-lg border border-border bg-muted/40 p-2.5">
          <span className="flex items-center gap-1.5 text-muted-foreground">
            <Wallet className="size-3.5" />
            {t.c360Outstanding}
          </span>
          <span className="font-bold" dir="ltr">
            {formatMoney(payments.outstanding, payments.currency)}
          </span>
        </div>
      )}
      {orders.slice(0, 8).map((order) => (
        <div
          key={order.id}
          className="flex items-center justify-between gap-3 rounded-lg border border-border p-2.5"
        >
          <div className="min-w-0">
            <div className="font-bold" dir="ltr">
              {order.number}
            </div>
            <div className="text-[11px] text-muted-foreground">
              {formatDateTime(order.placed_at || order.created_at)}
            </div>
          </div>
          <div className="shrink-0 text-end">
            <div className="font-bold" dir="ltr">
              {formatMoney(order.grand_total, order.currency)}
            </div>
            <Badge variant={orderVariant(order.status)} className="mt-0.5 px-1.5 py-0 text-[10px]">
              {order.status}
            </Badge>
          </div>
        </div>
      ))}
      <Button variant="outline" size="sm" asChild className="w-full text-xs">
        <Link href={`/customers/${customerId}`}>{t.viewAll}</Link>
      </Button>
    </div>
  );
}

function TimelineTabContent({ customerId }: { customerId: string }) {
  const query = useCustomer360(customerId);
  const timeline = query.data?.timeline ?? [];

  if (query.isLoading) {
    return (
      <div className="space-y-2" aria-busy="true" aria-label={t.loading}>
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-10" />
        ))}
      </div>
    );
  }
  if (!query.data) return <PanelEmpty>{t.customerNotFound}</PanelEmpty>;
  if (timeline.length === 0) return <PanelEmpty>{t.c360TimelineEmpty}</PanelEmpty>;

  return (
    <ol className="relative space-y-3 border-s border-border ps-4 text-xs">
      {timeline.slice(0, 20).map((entry, i) => (
        <li key={`${entry.kind}-${entry.ref_id ?? i}-${entry.at}`} className="relative">
          <span
            className={cn(
              "absolute -start-[21.5px] top-0.5 flex size-4 items-center justify-center rounded-full border border-border bg-card text-muted-foreground",
            )}
            aria-hidden="true"
          >
            {timelineIcon(entry.kind)}
          </span>
          <div className="font-medium">{entry.title || "—"}</div>
          {entry.subtitle && (
            <div className="text-[11px] text-muted-foreground">{entry.subtitle}</div>
          )}
          <div className="mt-0.5 text-[10px] text-muted-foreground">
            {formatDateTime(entry.at)}
          </div>
        </li>
      ))}
    </ol>
  );
}

function NotesTabContent({ customerId }: { customerId: string }) {
  const query = useCustomer360(customerId);
  const notes = query.data?.notes ?? [];

  if (query.isLoading) {
    return (
      <div className="space-y-2" aria-busy="true" aria-label={t.loading}>
        {Array.from({ length: 2 }).map((_, i) => (
          <Skeleton key={i} className="h-14" />
        ))}
      </div>
    );
  }
  if (!query.data) return <PanelEmpty>{t.customerNotFound}</PanelEmpty>;
  if (notes.length === 0) return <PanelEmpty>{t.c360NotesEmpty}</PanelEmpty>;

  return (
    <div className="space-y-2 text-xs">
      {notes.map((note) => (
        <div key={note.id} className="rounded-lg border border-border p-2.5">
          <div>{note.body}</div>
          <div className="mt-1 flex items-center gap-1 text-[11px] text-muted-foreground">
            <Clock className="size-3" />
            {formatDateTime(note.created_at)}
          </div>
        </div>
      ))}
    </div>
  );
}
