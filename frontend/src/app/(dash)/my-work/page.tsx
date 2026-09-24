"use client";

/** §97 "My Work" — the question this page answers is "what do I need to do?",
 *  not "what is happening in the business" (that is Home). Four slices of the
 *  current user's queue, each with its own loading / empty / error state and a
 *  link through to the page where the work actually gets done (§113). */

import * as React from "react";
import Link from "next/link";
import {
  ArrowUpRight,
  Bookmark,
  Clock,
  ListChecks,
  MessagesSquare,
  ShieldAlert,
  TriangleAlert,
} from "lucide-react";
import {
  useApprovals,
  useConversations,
  useMe,
  useSavedViews,
  useSlaRisk,
  useTasks,
  type Approval,
  type Conversation,
  type SavedView,
  type SlaRiskItem,
  type Task,
} from "@/lib/queries";
import { t } from "@/lib/t";
import { getLang } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui/states";

/* ------------------------------------------------------------- formatting */

/** "12 دقيقة" / "متأخر 3 ساعات" — the human form of `minutes_remaining`. */
function formatRemaining(minutes: number): string {
  const overdue = minutes < 0;
  const abs = Math.abs(minutes);
  if (abs >= 60) {
    const hours = Math.round(abs / 60);
    return overdue ? t.slaOverdueHours(hours) : t.slaHoursLeft(hours);
  }
  return overdue ? t.slaOverdueMinutes(abs) : t.slaMinutesLeft(abs);
}

function formatDateTime(value: string): string {
  const locale = getLang() === "en" ? "en-GB" : "ar-EG";
  return new Date(value).toLocaleString(locale, { dateStyle: "short", timeStyle: "short" });
}

/** The API returns risk_level as "HIGH" / "LOW"; fall back to the raw value. */
function riskLabel(level: string): string {
  const key = level.toUpperCase();
  if (key === "HIGH") return t.riskHigh;
  if (key === "LOW") return t.riskLow;
  return level;
}

function riskVariant(level: string): "danger" | "default" {
  return level.toUpperCase() === "HIGH" ? "danger" : "default";
}

/** §95 — صفحات الجهات التي لها عروض محفوظة يمكن الوصول إليها من هنا.
 *  أي كيان آخر يظهر بلا رابط حتى تتوفر له صفحة قائمة. */
const VIEW_ENTITY_HREF: Record<string, string> = {
  customers: "/customers",
  orders: "/orders",
};

/* ---------------------------------------------------------------- sections */

function Section({
  title,
  hint,
  href,
  linkLabel,
  children,
}: {
  title: string;
  hint: string;
  href: string;
  linkLabel: string;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
        <div className="min-w-0">
          <CardTitle>{title}</CardTitle>
          <p className="mt-0.5 text-[13px] text-muted-foreground">{hint}</p>
        </div>
        <Link
          href={href}
          className="group inline-flex shrink-0 items-center gap-1 text-[13px] font-bold text-primary underline-offset-4 hover:underline"
        >
          {linkLabel}
          <ArrowUpRight
            aria-hidden="true"
            className="size-3.5 transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5"
          />
        </Link>
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

function RowsSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-2" aria-busy="true" aria-label={t.loading}>
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-12" />
      ))}
    </div>
  );
}

function RowShell({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        "flex items-center justify-between gap-3 rounded-lg border p-3 transition-colors",
        className,
      )}
    >
      {children}
    </div>
  );
}

/* ------------------------------------------------------------------- page */

export default function MyWorkPage() {
  const me = useMe();
  const slaQuery = useSlaRisk();
  const approvalsQuery = useApprovals("PENDING");
  const tasksQuery = useTasks();
  const conversationsQuery = useConversations();
  const savedViewsQuery = useSavedViews(null);
  const savedViews = savedViewsQuery.data ?? [];

  const myId = me.data?.id;

  // Sort by minutes_remaining ascending; rows with no deadline sink to the end.
  const slaItems = React.useMemo<SlaRiskItem[]>(() => {
    const items = slaQuery.data?.items ?? [];
    return [...items].sort((a, b) => {
      const av = a.minutes_remaining ?? Number.POSITIVE_INFINITY;
      const bv = b.minutes_remaining ?? Number.POSITIVE_INFINITY;
      return av - bv;
    });
  }, [slaQuery.data]);

  const approvals = approvalsQuery.data?.items ?? [];

  const myTasks = React.useMemo<Task[]>(() => {
    if (!myId) return [];
    return (tasksQuery.data ?? []).filter(
      (task) =>
        task.assignee_user_id === myId &&
        (task.status === "todo" || task.status === "in_progress"),
    );
  }, [tasksQuery.data, myId]);

  const myConversations = React.useMemo<Conversation[]>(() => {
    if (!myId) return [];
    return (conversationsQuery.data?.pages ?? [])
      .flatMap((page) => page.items)
      .filter((conversation) => conversation.assignee_user_id === myId);
  }, [conversationsQuery.data, myId]);

  return (
    <div>
      <PageHeader title={t.myWork} description={t.myWorkDescription} />

      <div className="grid gap-4 lg:grid-cols-2">
        {/* 1 — SLA risk */}
        <Section title={t.slaRisk} hint={t.slaRiskHint} href="/inbox" linkLabel={t.inbox}>
          {slaQuery.isLoading ? (
            <RowsSkeleton />
          ) : slaQuery.error ? (
            <ErrorState message={(slaQuery.error as Error).message} onRetry={() => slaQuery.refetch()} />
          ) : slaItems.length === 0 ? (
            <EmptyState
              icon={<Clock aria-hidden="true" />}
              title={t.slaRiskEmpty}
              description={t.slaRiskEmptyHint}
              className="py-8"
            />
          ) : (
            <div className="space-y-2">
              {slaItems.map((item) => {
                const overdue = item.minutes_remaining !== null && item.minutes_remaining < 0;
                return (
                  <Link
                    key={item.id}
                    href={`/inbox?conversation=${item.conversation_id}`}
                    className={cn(
                      "flex items-center justify-between gap-3 rounded-lg border p-3 transition-colors",
                      item.at_risk || overdue
                        ? "border-s-4 border-s-warning border-warning/40 bg-warning/5 hover:bg-warning/10"
                        : "border-border hover:bg-muted",
                    )}
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      <Clock
                        aria-hidden="true"
                        className={cn(
                          "size-4 shrink-0",
                          item.at_risk || overdue ? "text-warning" : "text-muted-foreground",
                        )}
                      />
                      <span className="truncate text-sm font-semibold" dir="ltr">
                        {item.conversation_id.slice(0, 8)}…
                      </span>
                    </span>
                    <span className="flex shrink-0 items-center gap-2">
                      {item.status === "breached" ? (
                        <Badge variant="danger">{t.slaBreached}</Badge>
                      ) : item.at_risk ? (
                        <Badge variant="warning">{t.slaAtRisk}</Badge>
                      ) : null}
                      {item.minutes_remaining !== null && (
                        <span
                          className={cn(
                            "text-[13px] font-semibold",
                            overdue
                              ? "text-danger"
                              : item.at_risk
                                ? "text-warning"
                                : "text-muted-foreground",
                          )}
                        >
                          {formatRemaining(item.minutes_remaining)}
                        </span>
                      )}
                    </span>
                  </Link>
                );
              })}
            </div>
          )}
        </Section>

        {/* 2 — My approvals */}
        <Section title={t.myApprovals} hint={t.myApprovalsHint} href="/ai" linkLabel={t.ai}>
          {approvalsQuery.isLoading ? (
            <RowsSkeleton />
          ) : approvalsQuery.error ? (
            <ErrorState
              message={(approvalsQuery.error as Error).message}
              onRetry={() => approvalsQuery.refetch()}
            />
          ) : approvals.length === 0 ? (
            <EmptyState
              icon={<ShieldAlert aria-hidden="true" />}
              title={t.myApprovalsEmpty}
              description={t.myApprovalsEmptyHint}
              className="py-8"
            />
          ) : (
            <div className="space-y-2">
              {approvals.map((approval: Approval) => (
                <RowShell key={approval.id} className="border-border">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-semibold">{approval.action}</div>
                    <div className="mt-0.5 text-xs text-muted-foreground">
                      {t.approvalExpires}:{" "}
                      {approval.expires_at ? formatDateTime(approval.expires_at) : t.approvalNoExpiry}
                    </div>
                  </div>
                  <Badge variant={riskVariant(approval.risk_level)}>
                    {t.approvalRisk}: {riskLabel(approval.risk_level)}
                  </Badge>
                </RowShell>
              ))}
            </div>
          )}
        </Section>

        {/* 3 — My tasks */}
        <Section title={t.myAssignedTasks} hint={t.myAssignedTasksHint} href="/tasks" linkLabel={t.myTasks}>
          {me.isLoading || tasksQuery.isLoading ? (
            <RowsSkeleton />
          ) : tasksQuery.error ? (
            <ErrorState message={(tasksQuery.error as Error).message} onRetry={() => tasksQuery.refetch()} />
          ) : myTasks.length === 0 ? (
            <EmptyState
              icon={<ListChecks aria-hidden="true" />}
              title={t.myAssignedTasksEmpty}
              description={t.myAssignedTasksEmptyHint}
              className="py-8"
            />
          ) : (
            <div className="space-y-2">
              {myTasks.map((task) => (
                <Link
                  key={task.id}
                  href="/tasks"
                  className="flex items-center justify-between gap-3 rounded-lg border border-border p-3 transition-colors hover:bg-muted"
                >
                  <div className="min-w-0">
                    <div className="truncate text-sm font-semibold">{task.title}</div>
                    <div className="mt-0.5 text-xs text-muted-foreground">
                      {t.dueDate}: {task.due_date ? formatDateTime(task.due_date) : "—"}
                    </div>
                  </div>
                  <Badge variant={task.status === "in_progress" ? "primary" : "default"}>
                    {task.status === "in_progress" ? t.taskInProgress : t.taskTodo}
                  </Badge>
                </Link>
              ))}
            </div>
          )}
        </Section>

        {/* 4 — My conversations */}
        <Section
          title={t.myAssignedConversations}
          hint={t.myAssignedConversationsHint}
          href="/inbox"
          linkLabel={t.inbox}
        >
          {me.isLoading || conversationsQuery.isLoading ? (
            <RowsSkeleton />
          ) : conversationsQuery.error ? (
            <ErrorState
              message={(conversationsQuery.error as Error).message}
              onRetry={() => conversationsQuery.refetch()}
            />
          ) : myConversations.length === 0 ? (
            <EmptyState
              icon={<MessagesSquare aria-hidden="true" />}
              title={t.myAssignedConversationsEmpty}
              description={t.myAssignedConversationsEmptyHint}
              className="py-8"
            />
          ) : (
            <div className="space-y-2">
              {myConversations.map((conversation) => (
                <Link
                  key={conversation.id}
                  href={`/inbox?conversation=${conversation.id}`}
                  className="flex items-center justify-between gap-3 rounded-lg border border-border p-3 transition-colors hover:bg-muted"
                >
                  <div className="min-w-0">
                    <div className="truncate text-sm font-semibold">
                      {conversation.customer_name ||
                        `${conversation.customer_id.slice(0, 8)}…`}
                    </div>
                    <div className="mt-0.5 text-xs text-muted-foreground">
                      {conversation.channel}
                    </div>
                  </div>
                  {conversation.unread_count > 0 && (
                    <Badge variant="primary">
                      {conversation.unread_count} {t.unread}
                    </Badge>
                  )}
                </Link>
              ))}
            </div>
          )}
        </Section>

        {/* 5 — My saved views (§95/§97) */}
        <Section
          title={t.mySavedViews}
          hint={t.mySavedViewsHint}
          href="/customers"
          linkLabel={t.customers}
        >
          {savedViewsQuery.isLoading ? (
            <RowsSkeleton />
          ) : savedViewsQuery.error ? (
            <ErrorState
              message={(savedViewsQuery.error as Error).message}
              onRetry={() => savedViewsQuery.refetch()}
            />
          ) : savedViews.length === 0 ? (
            <EmptyState
              icon={<Bookmark aria-hidden="true" />}
              title={t.mySavedViewsEmpty}
              description={t.mySavedViewsEmptyHint}
              className="py-8"
            />
          ) : (
            <div className="space-y-2">
              {savedViews.map((view: SavedView) => {
                const href = VIEW_ENTITY_HREF[view.entity];
                // التسمية داخل الرندر حتى تتبع اللغة النشطة
                const entityLabel =
                  view.entity === "customers"
                    ? t.customers
                    : view.entity === "orders"
                      ? t.orders
                      : view.entity;
                const body = (
                  <>
                    <div className="flex min-w-0 items-center gap-2">
                      <Bookmark
                        aria-hidden="true"
                        className="size-4 shrink-0 text-primary"
                      />
                      <div className="min-w-0">
                        <div className="truncate text-sm font-semibold">{view.name}</div>
                        <div className="mt-0.5 text-xs text-muted-foreground">
                          {entityLabel}
                        </div>
                      </div>
                    </div>
                    <Badge variant="outline">{entityLabel}</Badge>
                  </>
                );
                const className =
                  "flex items-center justify-between gap-3 rounded-lg border border-border p-3 transition-colors hover:bg-muted";
                return href ? (
                  <Link key={view.id} href={`${href}?view=${view.id}`} className={className}>
                    {body}
                  </Link>
                ) : (
                  <div key={view.id} className={className}>
                    {body}
                  </div>
                );
              })}
            </div>
          )}
        </Section>
      </div>

      {/* §107 — the page is never a dead end: an explicit next step. */}
      <div className="mt-4 flex flex-wrap gap-3">
        <Link
          href="/inbox"
          className="group inline-flex items-center gap-1.5 text-[13px] font-bold text-primary underline-offset-4 hover:underline"
        >
          <TriangleAlert aria-hidden="true" className="size-3.5" />
          {t.goInbox}
        </Link>
        <Link
          href="/tasks"
          className="group inline-flex items-center gap-1.5 text-[13px] font-bold text-primary underline-offset-4 hover:underline"
        >
          <ListChecks aria-hidden="true" className="size-3.5" />
          {t.myTasks}
        </Link>
      </div>
    </div>
  );
}
