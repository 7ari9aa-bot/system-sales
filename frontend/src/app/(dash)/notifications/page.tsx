"use client";

/** Spec W5 — the notifications centre.
 *
 *  The bell is a glance; this is the place where the queue actually gets
 *  cleared. Filters (all / unread / by kind) are applied server-side, so the
 *  counts in the chips come from the summary endpoint rather than from
 *  whatever page happens to be loaded.
 */

import * as React from "react";
import Link from "next/link";
import {
  Bell,
  BellOff,
  CheckCheck,
  ExternalLink,
  Inbox,
  Loader2,
} from "lucide-react";
import {
  useMarkAllRead,
  useMarkManyRead,
  useMarkRead,
  useNotificationSummary,
  useNotifications,
  type Notification,
} from "@/lib/queries";
import { Check } from "lucide-react";
import { t } from "@/lib/t";
import { getLang } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui/states";
import { toast } from "@/components/ui/toast";

/* ------------------------------------------------------------ formatting -- */

function formatDateTime(value: string): string {
  const locale = getLang() === "en" ? "en-GB" : "ar-EG";
  return new Date(value).toLocaleString(locale, { dateStyle: "short", timeStyle: "short" });
}

/** Kinds are open-ended (the column defaults to "system"), so never assume a
 *  closed set — humanise whatever arrives. */
function kindLabel(kind: string): string {
  return kind.replace(/[_.]/g, " ").trim() || kind;
}

type BadgeVariant = "default" | "primary" | "success" | "warning" | "danger";

function kindVariant(kind: string): BadgeVariant {
  const k = kind.toLowerCase();
  if (/(error|fail|breach|overdue|reject|block)/.test(k)) return "danger";
  if (/(approval|pending|warning|risk|low_stock)/.test(k)) return "warning";
  if (/(paid|created|success|delivered|resolved|met)/.test(k)) return "success";
  if (/(message|conversation|order|customer|task)/.test(k)) return "primary";
  return "default";
}

/* ----------------------------------------------------------------- pieces -- */

function RowSkeleton() {
  return (
    <div className="space-y-2" aria-busy="true" aria-label={t.loading}>
      {Array.from({ length: 5 }).map((_, i) => (
        <Skeleton key={i} className="h-16" />
      ))}
    </div>
  );
}

function FilterChip({
  active,
  onClick,
  label,
  count,
  testid,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  count?: number;
  testid?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      data-testid={testid}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[13px] font-semibold transition-colors",
        active
          ? "border-primary bg-primary-soft text-primary"
          : "border-border text-muted-foreground hover:bg-muted hover:text-foreground",
      )}
    >
      {label}
      {count !== undefined && (
        <span
          className={cn(
            "rounded-full px-1.5 text-[11px] tabular-nums",
            active ? "bg-primary/15" : "bg-muted",
          )}
          dir="ltr"
        >
          {count}
        </span>
      )}
    </button>
  );
}

/* ------------------------------------------------------------------- page -- */

export default function NotificationsPage() {
  const [unreadOnly, setUnreadOnly] = React.useState(false);
  const [kind, setKind] = React.useState<string | null>(null);
  const [selected, setSelected] = React.useState<Set<string>>(new Set());

  const listQuery = useNotifications({ unread_only: unreadOnly, kind, limit: 100 });
  const summaryQuery = useNotificationSummary();
  const summary = summaryQuery.data;
  const markRead = useMarkRead();
  const markAll = useMarkAllRead();
  const markMany = useMarkManyRead();
  const rawItems = listQuery.data;
  const items: Notification[] = React.useMemo(() => {
    if (Array.isArray(rawItems)) return rawItems;
    if (Array.isArray((rawItems as unknown as { items?: Notification[] })?.items))
      return (rawItems as unknown as { items: Notification[] }).items;
    return [];
  }, [rawItems]);
  const unreadTotal = summary?.unread ?? 0;

  // Drop selections that are no longer on screen so the bulk action never
  // fires for rows the user cannot see.
  React.useEffect(() => {
    setSelected((prev) => {
      if (prev.size === 0) return prev;
      const visible = new Set(items.map((n) => n.id));
      const next = new Set([...prev].filter((id) => visible.has(id)));
      return next.size === prev.size ? prev : next;
    });
  }, [items]);

  const allSelected = items.length > 0 && items.every((n) => selected.has(n.id));

  function toggleOne(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    setSelected(allSelected ? new Set() : new Set(items.map((n) => n.id)));
  }

  function openNotification(n: Notification) {
    if (!n.read_at) {
      markRead.mutate(n.id, {
        onError: () => toast({ title: t.somethingWentWrong, variant: "danger" }),
      });
    }
  }

  const busy = markAll.isPending || markMany.isPending;

  return (
    <div>
      <PageHeader
        title={t.notifications}
        description={t.notificationsHint}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {selected.size > 0 && (
              <Button
                variant="outline"
                size="sm"
                disabled={busy}
                data-testid="notifications-mark-selected"
                onClick={() =>
                  markMany.mutate([...selected], {
                    onSuccess: (res) => {
                      setSelected(new Set());
                      toast({
                        title: t.markSelectedRead,
                        description: `${res.marked}`,
                        variant: "success",
                      });
                    },
                    onError: (err) =>
                      toast({
                        title: t.somethingWentWrong,
                        description: (err as Error).message,
                        variant: "danger",
                      }),
                  })
                }
              >
                {markMany.isPending ? (
                  <Loader2 aria-hidden="true" className="size-3.5 me-1.5 animate-spin" />
                ) : (
                  <Check aria-hidden="true" className="size-3.5 me-1.5" />
                )}
                {t.markSelectedRead}
              </Button>
            )}
            <Button
              variant="outline"
              size="sm"
              disabled={busy || unreadTotal === 0}
              data-testid="notifications-mark-all"
              onClick={() =>
                markAll.mutate(undefined, {
                  onSuccess: (res: unknown) => {
                    const marked = (res as { marked?: number })?.marked ?? 0;
                    toast({
                      title: t.markAllRead,
                      description: marked ? `${marked}` : t.notificationsAllRead,
                      variant: "success",
                    });
                  },
                  onError: (err) =>
                    toast({
                      title: t.somethingWentWrong,
                      description: (err as Error).message,
                      variant: "danger",
                    }),
                })
              }
            >
              {markAll.isPending ? (
                <Loader2 aria-hidden="true" className="size-3.5 me-1.5 animate-spin" />
              ) : (
                <CheckCheck aria-hidden="true" className="size-3.5 me-1.5" />
              )}
              {t.markAllRead}
            </Button>
          </div>
        }
      />

      {/* --------------------------------------------------------- filters -- */}
      <div className="flex flex-wrap items-center gap-2">
        <FilterChip
          active={!unreadOnly && kind === null}
          onClick={() => {
            setUnreadOnly(false);
            setKind(null);
          }}
          label={t.filterAll}
          count={summary?.total}
          testid="notif-filter-all"
        />
        <FilterChip
          active={unreadOnly && kind === null}
          onClick={() => {
            setUnreadOnly(true);
            setKind(null);
          }}
          label={t.filterUnread}
          count={unreadTotal}
          testid="notif-filter-unread"
        />

        {(summary?.by_kind.length ?? 0) > 0 && (
          <>
            <span className="mx-1 h-5 w-px bg-border" aria-hidden="true" />
            <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              {t.filterByKind}
            </span>
            {summary!.by_kind.map((row) => (
              <FilterChip
                key={row.kind}
                active={kind === row.kind}
                onClick={() => {
                  setKind(kind === row.kind ? null : row.kind);
                  setUnreadOnly(false);
                }}
                label={kindLabel(row.kind)}
                count={row.unread || row.total}
                testid={`notif-kind-${row.kind}`}
              />
            ))}
          </>
        )}
      </div>

      {/* ------------------------------------------------------------ list -- */}
      <div className="mt-4">
        {listQuery.isLoading ? (
          <RowSkeleton />
        ) : listQuery.isError ? (
          <ErrorState
            message={(listQuery.error as Error).message}
            onRetry={() => listQuery.refetch()}
          />
        ) : items.length === 0 ? (
          <EmptyState
            icon={unreadOnly ? <BellOff aria-hidden="true" /> : <Inbox aria-hidden="true" />}
            title={unreadOnly ? t.allCaughtUp : t.noNotifications}
            description={unreadOnly ? t.notificationsAllRead : t.noNotificationsHint}
            testid="notifications-empty"
          />
        ) : (
          <Card>
            <CardContent className="space-y-2 pt-6">
              <div className="flex items-center gap-2 pb-1">
                <input
                  type="checkbox"
                  className="size-4 cursor-pointer accent-primary"
                  checked={allSelected}
                  onChange={toggleAll}
                  aria-label={t.selectAll}
                  data-testid="notif-select-all"
                />
                <span className="text-[11px] text-muted-foreground">
                  {selected.size > 0 ? t.selectedCount(selected.size) : t.selectAll}
                </span>
              </div>

              {items.map((n: Notification) => {
                const unread = !n.read_at;
                return (
                  <div
                    key={n.id}
                    data-testid={`notif-${n.id}`}
                    className={cn(
                      "flex items-start gap-3 rounded-lg border p-3 transition-colors",
                      unread
                        ? "border-s-4 border-s-primary border-primary/30 bg-primary/[0.03]"
                        : "border-border",
                    )}
                  >
                    <input
                      type="checkbox"
                      className="mt-1 size-4 cursor-pointer accent-primary"
                      checked={selected.has(n.id)}
                      onChange={() => toggleOne(n.id)}
                      aria-label={n.title || n.body}
                    />

                    <button
                      type="button"
                      onClick={() => openNotification(n)}
                      className="min-w-0 flex-1 text-start"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge variant={kindVariant(n.kind)}>{kindLabel(n.kind)}</Badge>
                        {unread && <span className="size-2 rounded-full bg-primary" aria-hidden="true" />}
                        <span className="text-[11px] text-muted-foreground">
                          {formatDateTime(n.created_at)}
                        </span>
                      </div>
                      {n.title && (
                        <div className="mt-1 truncate text-sm font-semibold">{n.title}</div>
                      )}
                      <div className="mt-0.5 text-[13px] text-muted-foreground">{n.body}</div>
                    </button>

                    <div className="flex shrink-0 items-center gap-1">
                      {unread && (
                        <Button
                          variant="ghost"
                          size="icon"
                          className="size-7"
                          aria-label={t.markAsRead}
                          data-testid={`notif-read-${n.id}`}
                          onClick={() =>
                            markRead.mutate(n.id, {
                              onError: () =>
                                toast({ title: t.somethingWentWrong, variant: "danger" }),
                            })
                          }
                        >
                          <Check aria-hidden="true" className="size-3.5" />
                        </Button>
                      )}
                      {n.action_url && (
                        <Button variant="ghost" size="icon" className="size-7" asChild>
                          <Link href={n.action_url} aria-label={t.viewAll}>
                            <ExternalLink aria-hidden="true" className="size-3.5" />
                          </Link>
                        </Button>
                      )}
                    </div>
                  </div>
                );
              })}
            </CardContent>
          </Card>
        )}
      </div>

      {/* §107 — never a dead end. */}
      <div className="mt-4">
        <Link
          href="/dashboard"
          className="inline-flex items-center gap-1.5 text-[13px] font-bold text-primary underline-offset-4 hover:underline"
        >
          <Bell aria-hidden="true" className="size-3.5" />
          {t.overview}
        </Link>
      </div>
    </div>
  );
}
