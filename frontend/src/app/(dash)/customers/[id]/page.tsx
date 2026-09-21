"use client";

/** Spec W5 §97-104 — the Customer 360 record.
 *
 *  One composed request (`GET /customers/{id}/360`) drives the whole page:
 *  profile, orders, conversations, tasks, payments and a merged timeline.
 *  Every tab has its own loading / empty / error state so a partial outage
 *  never blanks the record (§113).
 */

import * as React from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import {
  ArrowRight,
  Ban,
  Calendar,
  ChevronLeft,
  Clock,
  CreditCard,
  ExternalLink,
  Mail,
  MapPin,
  MessageSquare,
  NotebookPen,
  Package,
  Phone,
  ShieldCheck,
  ShoppingBag,
  Tags,
  UserCheck,
  Wallet,
} from "lucide-react";
import {
  useCustomer360,
  type Customer360Conversation,
  type Customer360Order,
  type Customer360Task,
  type CustomerTimelineEntry,
} from "@/lib/queries";
import { t } from "@/lib/t";
import { getLang } from "@/lib/i18n";
import { cn, formatMoney } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { EmptyState, ErrorState } from "@/components/ui/states";

/* ------------------------------------------------------------ formatting -- */

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const locale = getLang() === "en" ? "en-GB" : "ar-EG";
  return new Date(value).toLocaleString(locale, { dateStyle: "medium", timeStyle: "short" });
}

function formatDay(value: string | null | undefined): string {
  if (!value) return "—";
  const locale = getLang() === "en" ? "en-GB" : "ar-EG";
  return new Date(value).toLocaleDateString(locale, { dateStyle: "medium" });
}

type BadgeVariant = "default" | "primary" | "success" | "warning" | "danger" | "outline";

/** Money that never went through: cancelled and refunded orders. */
const LOST_ORDER_STATUSES = new Set(["cancelled", "refunded"]);

function orderVariant(status: string): BadgeVariant {
  if (status === "delivered" || status === "completed" || status === "confirmed") return "success";
  if (LOST_ORDER_STATUSES.has(status)) return "danger";
  if (status === "shipped" || status === "processing") return "primary";
  return "default";
}

function taskVariant(status: string): BadgeVariant {
  if (status === "done") return "success";
  if (status === "in_progress") return "primary";
  if (status === "cancelled") return "default";
  return "outline";
}

function taskStatusLabel(status: string): string {
  if (status === "in_progress") return t.taskInProgress;
  if (status === "done") return t.taskDone;
  if (status === "cancelled") return t.taskCancelled;
  return t.taskTodo;
}

function timelineKindLabel(kind: CustomerTimelineEntry["kind"]): string {
  switch (kind) {
    case "order":
      return t.c360TimelineOrder;
    case "conversation":
      return t.c360TimelineConversation;
    case "note":
      return t.c360TimelineNote;
    case "task":
      return t.c360TimelineTask;
    default:
      return t.c360TimelineEvent;
  }
}

function timelineVariant(kind: CustomerTimelineEntry["kind"]): BadgeVariant {
  switch (kind) {
    case "order":
      return "primary";
    case "conversation":
      return "success";
    case "task":
      return "warning";
    case "note":
      return "outline";
    default:
      return "default";
  }
}

function TimelineIcon({ kind }: { kind: CustomerTimelineEntry["kind"] }) {
  const className = "size-3.5";
  if (kind === "order") return <ShoppingBag aria-hidden="true" className={className} />;
  if (kind === "conversation") return <MessageSquare aria-hidden="true" className={className} />;
  if (kind === "task") return <Clock aria-hidden="true" className={className} />;
  if (kind === "note") return <NotebookPen aria-hidden="true" className={className} />;
  return <Calendar aria-hidden="true" className={className} />;
}

/* --------------------------------------------------------------- pieces --- */

function Stat({
  icon,
  label,
  value,
  tone = "default",
}: {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
  tone?: "default" | "danger" | "success";
}) {
  return (
    <div className="rounded-xl border border-border bg-muted/40 p-3 text-start">
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
        {icon}
        <span className="truncate">{label}</span>
      </div>
      <div
        className={cn(
          "mt-1 text-lg font-bold",
          tone === "danger" && "text-danger",
          tone === "success" && "text-success",
        )}
        dir="ltr"
      >
        {value}
      </div>
    </div>
  );
}

function SectionCard({
  title,
  action,
  children,
}: {
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-3 space-y-0">
        <CardTitle className="text-sm">{title}</CardTitle>
        {action}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

function InlineEmpty({ text }: { text: string }) {
  return (
    <div className="rounded-lg border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
      {text}
    </div>
  );
}

function RecordSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true" aria-label={t.loading}>
      <Skeleton className="h-20" />
      <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-20" />
        ))}
      </div>
      <Skeleton className="h-64" />
    </div>
  );
}

/* ------------------------------------------------------------------ page -- */

/** التبويبات المتاحة في سجل العميل — مصدر الحقيقة لمعامل الـURL ?tab= (§87). */
const C360_TABS = ["overview", "orders", "conversations", "tasks", "timeline"] as const;
type C360Tab = (typeof C360_TABS)[number];

export default function Customer360Page() {
  // useSearchParams يحتاج حدود Suspense أثناء التصيير المسبق
  return (
    <React.Suspense fallback={null}>
      <Customer360Content />
    </React.Suspense>
  );
}

function Customer360Content() {
  const params = useParams<{ id: string }>();
  const customerId = typeof params?.id === "string" ? params.id : "";
  const query = useCustomer360(customerId);
  const record = query.data;

  // §87 — التبويب النشط في الـURL (?tab=) حتى يكون السجل deep-linkable
  const searchParams = useSearchParams();
  const router = useRouter();
  const tabParam = searchParams.get("tab");
  const activeTab: C360Tab = C360_TABS.includes(tabParam as C360Tab)
    ? (tabParam as C360Tab)
    : "overview";

  function setTab(tab: string) {
    const next = new URLSearchParams(searchParams.toString());
    next.set("tab", tab);
    router.replace(`/customers/${customerId}?${next.toString()}`, { scroll: false });
  }

  const backLink = (
    <Link
      href="/customers"
      className="inline-flex items-center gap-1 text-[13px] font-semibold text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
    >
      <ArrowRight aria-hidden="true" className="size-3.5" />
      {t.backToCustomers}
    </Link>
  );

  if (query.isLoading) {
    return (
      <div>
        {backLink}
        <div className="mt-3">
          <RecordSkeleton />
        </div>
      </div>
    );
  }

  if (query.isError || !record) {
    return (
      <div>
        {backLink}
        <div className="mt-4">
          <ErrorState
            message={(query.error as Error)?.message ?? t.customerNotFound}
            onRetry={() => query.refetch()}
          />
        </div>
      </div>
    );
  }

  const { customer, payments, stats } = record;
  const currency = payments.currency || "EGP";

  return (
    <div>
      {backLink}

      {/* ------------------------------------------------------- header -- */}
      <div className="mt-3 flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex size-14 shrink-0 items-center justify-center rounded-full bg-primary/10 text-lg font-bold text-primary">
            {customer.name?.slice(0, 2) || "؟"}
          </div>
          <div className="min-w-0">
            <h1 className="truncate text-xl font-bold">{customer.name || t.customer360}</h1>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              {customer.is_blocked ? (
                <Badge variant="danger" className="gap-1">
                  <Ban aria-hidden="true" className="size-3" />
                  {t.c360Blocked}
                </Badge>
              ) : (
                <Badge variant="success" className="gap-1">
                  <UserCheck aria-hidden="true" className="size-3" />
                  {t.c360Active}
                </Badge>
              )}
              <span className="text-xs text-muted-foreground" dir="ltr">
                #{customer.id.slice(0, 8)}
              </span>
              <span className="text-xs text-muted-foreground">
                {t.c360CustomerSince}: {formatDay(customer.created_at)}
              </span>
            </div>
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" asChild>
            <Link href={`/inbox?customer=${customer.id}`}>
              <MessageSquare aria-hidden="true" className="size-3.5 me-1.5" />
              {t.c360OpenConversation}
            </Link>
          </Button>
          <Button variant="outline" size="sm" asChild>
            <Link href="/orders">
              <ShoppingBag aria-hidden="true" className="size-3.5 me-1.5" />
              {t.c360NewOrder}
            </Link>
          </Button>
        </div>
      </div>

      {/* --------------------------------------------------------- stats -- */}
      <div className="mt-4 grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Stat
          icon={<Wallet aria-hidden="true" className="size-3.5" />}
          label={t.c360LifetimeValue}
          value={formatMoney(customer.lifetime_value, currency)}
        />
        <Stat
          icon={<ShoppingBag aria-hidden="true" className="size-3.5" />}
          label={t.c360OrdersCount}
          value={stats.orders_shown}
        />
        <Stat
          icon={<CreditCard aria-hidden="true" className="size-3.5" />}
          label={t.c360OrdersValue}
          value={formatMoney(payments.orders_total, currency)}
        />
        <Stat
          icon={<Wallet aria-hidden="true" className="size-3.5" />}
          label={t.c360NetCollected}
          value={formatMoney(payments.net_collected, currency)}
          tone="success"
        />
        <Stat
          icon={<CreditCard aria-hidden="true" className="size-3.5" />}
          label={t.c360Outstanding}
          value={formatMoney(payments.outstanding, currency)}
          tone={Number(payments.outstanding) > 0 ? "danger" : "default"}
        />
        <Stat
          icon={<Clock aria-hidden="true" className="size-3.5" />}
          label={t.c360OpenTasks}
          value={stats.open_tasks}
        />
      </div>

      {/* ---------------------------------------------------------- tabs -- */}
      <Tabs value={activeTab} onValueChange={setTab} className="mt-4">
        <TabsList className="flex-wrap">
          <TabsTrigger value="overview">{t.c360Overview}</TabsTrigger>
          <TabsTrigger value="orders">
            {t.c360Orders} ({record.orders.length})
          </TabsTrigger>
          <TabsTrigger value="conversations">
            {t.c360Conversations} ({record.conversations.length})
          </TabsTrigger>
          <TabsTrigger value="tasks">
            {t.c360Tasks} ({record.tasks.length})
          </TabsTrigger>
          <TabsTrigger value="timeline">
            {t.c360Timeline} ({record.timeline.length})
          </TabsTrigger>
        </TabsList>

        {/* --------------------------------------------------- overview -- */}
        <TabsContent value="overview" className="mt-4 grid gap-4 lg:grid-cols-2">
          <SectionCard title={t.c360Contact}>
            <div className="space-y-2 text-sm">
              <div className="flex items-center justify-between gap-3 rounded-lg border border-border p-2.5">
                <span className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Phone aria-hidden="true" className="size-4" />
                  {t.phone}
                </span>
                <span className="truncate font-medium text-xs" dir="ltr">
                  {customer.phone || "—"}
                </span>
              </div>
              <div className="flex items-center justify-between gap-3 rounded-lg border border-border p-2.5">
                <span className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Mail aria-hidden="true" className="size-4" />
                  {t.email}
                </span>
                <span className="truncate font-medium text-xs" dir="ltr">
                  {customer.email || "—"}
                </span>
              </div>
              <div className="flex items-center justify-between gap-3 rounded-lg border border-border p-2.5">
                <span className="flex items-center gap-2 text-xs text-muted-foreground">
                  <ShieldCheck aria-hidden="true" className="size-4" />
                  {t.c360Identity}
                </span>
                <span className="truncate font-medium text-xs">{customer.locale || "—"}</span>
              </div>
            </div>
          </SectionCard>

          <SectionCard title={t.c360Identities}>
            {record.identities.length === 0 ? (
              <InlineEmpty text={t.c360IdentitiesEmpty} />
            ) : (
              <div className="space-y-2">
                {record.identities.map((identity) => (
                  <div
                    key={identity.id}
                    className="flex items-center justify-between gap-3 rounded-lg border border-border p-2.5"
                  >
                    <Badge variant="primary">{identity.channel}</Badge>
                    <span className="truncate text-xs" dir="ltr">
                      {identity.external_id}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </SectionCard>

          <SectionCard title={t.c360Tags}>
            {record.tags.length === 0 ? (
              <InlineEmpty text={t.c360TagsEmpty} />
            ) : (
              <div className="flex flex-wrap gap-2">
                {record.tags.map((tag) => (
                  <Badge
                    key={tag.id}
                    variant="outline"
                    className="gap-1"
                    style={tag.color ? { borderColor: tag.color, color: tag.color } : undefined}
                  >
                    <Tags aria-hidden="true" className="size-3" />
                    {tag.name}
                  </Badge>
                ))}
              </div>
            )}
          </SectionCard>

          <SectionCard title={t.c360Addresses}>
            {record.addresses.length === 0 ? (
              <InlineEmpty text={t.c360AddressesEmpty} />
            ) : (
              <div className="space-y-2">
                {record.addresses.map((address) => (
                  <div key={address.id} className="rounded-lg border border-border p-2.5 text-xs">
                    <div className="flex items-center gap-2">
                      <MapPin aria-hidden="true" className="size-3.5 text-muted-foreground" />
                      <span className="font-semibold">{address.label || t.c360Addresses}</span>
                      {address.is_default && <Badge variant="primary">{t.c360Default}</Badge>}
                    </div>
                    <div className="mt-1 text-muted-foreground">
                      {[address.line1, address.line2, address.city, address.region, address.country]
                        .filter(Boolean)
                        .join(", ") || "—"}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </SectionCard>

          <SectionCard title={t.c360Notes}>
            {record.notes.length === 0 ? (
              <InlineEmpty text={t.c360NotesEmpty} />
            ) : (
              <div className="space-y-2">
                {record.notes.slice(0, 5).map((note) => (
                  <div key={note.id} className="rounded-lg border border-border p-2.5">
                    <div className="text-xs">{note.body}</div>
                    <div className="mt-1 text-[11px] text-muted-foreground">
                      {formatDateTime(note.created_at)}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </SectionCard>

          <SectionCard title={t.c360Paid}>
            <div className="grid grid-cols-2 gap-2">
              <Stat
                icon={<Wallet aria-hidden="true" className="size-3.5" />}
                label={t.c360Paid}
                value={formatMoney(payments.paid_total, currency)}
              />
              <Stat
                icon={<Wallet aria-hidden="true" className="size-3.5" />}
                label={t.c360Refunded}
                value={formatMoney(payments.refunded_total, currency)}
              />
              <Stat
                icon={<CreditCard aria-hidden="true" className="size-3.5" />}
                label={t.c360PaymentsCount}
                value={payments.payment_count}
              />
              <Stat
                icon={<MessageSquare aria-hidden="true" className="size-3.5" />}
                label={t.c360Unread}
                value={stats.unread_messages}
              />
            </div>
          </SectionCard>
        </TabsContent>

        {/* ----------------------------------------------------- orders -- */}
        <TabsContent value="orders" className="mt-4">
          <SectionCard
            title={t.c360Orders}
            action={
              <Link
                href="/orders"
                className="inline-flex items-center gap-1 text-xs font-bold text-primary underline-offset-4 hover:underline"
              >
                {t.orders}
                <ExternalLink aria-hidden="true" className="size-3" />
              </Link>
            }
          >
            {record.orders.length === 0 ? (
              <EmptyState
                icon={<Package aria-hidden="true" />}
                title={t.c360OrdersEmpty}
                description={t.c360OrdersEmptyHint}
                className="py-8"
              />
            ) : (
              <div className="space-y-2">
                {record.orders.map((order: Customer360Order) => (
                  <div
                    key={order.id}
                    className="flex items-center justify-between gap-3 rounded-lg border border-border p-3 text-xs transition-colors hover:bg-muted"
                  >
                    <div className="min-w-0">
                      <div className="font-bold" dir="ltr">
                        {order.number}
                      </div>
                      <div className="mt-0.5 text-[11px] text-muted-foreground">
                        {formatDateTime(order.placed_at || order.created_at)}
                        {order.channel ? ` · ${order.channel}` : ""}
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <span className="font-bold" dir="ltr">
                        {formatMoney(order.grand_total, order.currency)}
                      </span>
                      <Badge variant={orderVariant(order.status)}>{order.status}</Badge>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </SectionCard>
        </TabsContent>

        {/* ---------------------------------------------- conversations -- */}
        <TabsContent value="conversations" className="mt-4">
          <SectionCard title={t.c360Conversations}>
            {record.conversations.length === 0 ? (
              <EmptyState
                icon={<MessageSquare aria-hidden="true" />}
                title={t.c360ConversationsEmpty}
                description={t.c360ConversationsEmptyHint}
                className="py-8"
              />
            ) : (
              <div className="space-y-2">
                {record.conversations.map((conversation: Customer360Conversation) => (
                  <Link
                    key={conversation.id}
                    href={`/inbox?conversation=${conversation.id}`}
                    className="flex items-center justify-between gap-3 rounded-lg border border-border p-3 text-xs transition-colors hover:bg-muted"
                  >
                    <div className="min-w-0">
                      <div className="font-semibold">{conversation.channel}</div>
                      <div className="mt-0.5 text-[11px] text-muted-foreground">
                        {formatDateTime(conversation.last_message_at || conversation.created_at)}
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      {conversation.unread_count > 0 && (
                        <Badge variant="primary">
                          {conversation.unread_count} {t.unread}
                        </Badge>
                      )}
                      <Badge variant={conversation.status === "closed" ? "default" : "success"}>
                        {conversation.status}
                      </Badge>
                      <ChevronLeft aria-hidden="true" className="size-4 text-muted-foreground" />
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </SectionCard>
        </TabsContent>

        {/* ------------------------------------------------------ tasks -- */}
        <TabsContent value="tasks" className="mt-4">
          <SectionCard
            title={t.c360Tasks}
            action={
              <Link
                href="/tasks"
                className="inline-flex items-center gap-1 text-xs font-bold text-primary underline-offset-4 hover:underline"
              >
                {t.myTasks}
                <ExternalLink aria-hidden="true" className="size-3" />
              </Link>
            }
          >
            {record.tasks.length === 0 ? (
              <EmptyState
                icon={<Clock aria-hidden="true" />}
                title={t.c360TasksEmpty}
                className="py-8"
              />
            ) : (
              <div className="space-y-2">
                {record.tasks.map((task: Customer360Task) => (
                  <div
                    key={task.id}
                    className="flex items-center justify-between gap-3 rounded-lg border border-border p-3 text-xs"
                  >
                    <div className="min-w-0">
                      <div className="truncate font-semibold">{task.title}</div>
                      <div className="mt-0.5 text-[11px] text-muted-foreground">
                        {t.dueDate}: {task.due_date ? formatDateTime(task.due_date) : "—"}
                        {" · "}
                        {task.source}
                      </div>
                    </div>
                    <Badge variant={taskVariant(task.status)}>{taskStatusLabel(task.status)}</Badge>
                  </div>
                ))}
              </div>
            )}
          </SectionCard>
        </TabsContent>

        {/* --------------------------------------------------- timeline -- */}
        <TabsContent value="timeline" className="mt-4">
          <SectionCard title={t.c360Timeline}>
            {record.timeline.length === 0 ? (
              <EmptyState
                icon={<Calendar aria-hidden="true" />}
                title={t.c360TimelineEmpty}
                className="py-8"
              />
            ) : (
              <ol className="relative space-y-2 border-s border-border ps-4">
                {record.timeline.map((entry, index) => (
                  <li
                    key={`${entry.kind}-${entry.ref_id}-${index}`}
                    className="rounded-lg border border-border p-3"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="flex min-w-0 items-center gap-2">
                        <Badge variant={timelineVariant(entry.kind)} className="gap-1">
                          <TimelineIcon kind={entry.kind} />
                          {timelineKindLabel(entry.kind)}
                        </Badge>
                        <span className="truncate text-xs font-semibold" dir="auto">
                          {entry.title || "—"}
                        </span>
                        {entry.subtitle && (
                          <span className="text-[11px] text-muted-foreground">
                            {entry.subtitle}
                          </span>
                        )}
                      </span>
                      <span className="shrink-0 text-[11px] text-muted-foreground">
                        {formatDateTime(entry.at)}
                      </span>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </SectionCard>
        </TabsContent>
      </Tabs>

      {/* §107 — never a dead end. */}
      <div className="mt-4">
        <Link
          href="/customers"
          className="inline-flex items-center gap-1.5 text-[13px] font-bold text-primary underline-offset-4 hover:underline"
        >
          {t.backToCustomers}
        </Link>
      </div>
    </div>
  );
}
