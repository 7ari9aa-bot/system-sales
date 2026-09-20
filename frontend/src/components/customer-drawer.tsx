"use client";

/** Quick-preview drawer for a customer (spec W5: "Customer 360 record +
 *  quick preview drawer").
 *
 *  Reads the same composed `GET /customers/{id}/360` payload as the full
 *  record page. It previously pulled a tenant-wide page of orders and
 *  filtered them in the browser, which silently reported "no orders" for any
 *  customer whose orders fell outside that page — the server does the
 *  filtering now.
 */

import * as React from "react";
import Link from "next/link";
import {
  Ban,
  Clock,
  CreditCard,
  ExternalLink,
  Mail,
  MessageSquare,
  NotebookPen,
  Phone,
  Tags,
  UserCheck,
  Wallet,
} from "lucide-react";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useCustomer360, type Customer360Order } from "@/lib/queries";
import { getLang } from "@/lib/i18n";
import { formatMoney } from "@/lib/utils";
import { t } from "@/lib/t";

type CustomerDrawerProps = {
  customerId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const locale = getLang() === "en" ? "en-GB" : "ar-EG";
  return new Date(value).toLocaleString(locale, { dateStyle: "short", timeStyle: "short" });
}

function orderVariant(status: string): "default" | "primary" | "success" | "danger" {
  if (status === "delivered" || status === "completed" || status === "confirmed") return "success";
  if (status === "cancelled" || status === "refunded") return "danger";
  if (status === "shipped" || status === "processing") return "primary";
  return "default";
}

export function CustomerDrawer({ customerId, open, onOpenChange }: CustomerDrawerProps) {
  // Nothing is requested until the drawer is open.
  const query = useCustomer360(open ? customerId : null);
  const record = query.data;
  const customer = record?.customer;

  const customerOrders: Customer360Order[] = record?.orders ?? [];

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="end" className="w-full max-w-md overflow-y-auto p-6">
        <SheetHeader className="border-b border-border pb-4 text-start">
          <div className="flex items-center gap-3">
            <div className="flex size-12 items-center justify-center rounded-full bg-primary/10 text-lg font-bold text-primary">
              {customer?.name?.slice(0, 2) || "؟"}
            </div>
            <div className="min-w-0 flex-1">
              <SheetTitle className="truncate text-lg font-bold">
                {customer?.name || t.customer360}
              </SheetTitle>
              <SheetDescription className="mt-1 flex flex-wrap items-center gap-2">
                {customer?.is_blocked ? (
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
                  #{customerId?.slice(0, 8)}
                </span>
              </SheetDescription>
            </div>
          </div>
        </SheetHeader>

        {query.isLoading ? (
          <div className="space-y-4 py-8" aria-busy="true" aria-label={t.loading}>
            <Skeleton className="h-16" />
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-20" />
          </div>
        ) : !record ? (
          <div className="py-8 text-center text-sm text-muted-foreground">
            {t.customerNotFound}
          </div>
        ) : (
          <div className="space-y-6 pt-4">
            {/* Money at a glance — from the server, not a client-side sum. */}
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-xl border border-border bg-muted/40 p-3 text-start">
                <div className="flex items-center gap-1 text-xs text-muted-foreground">
                  <Wallet aria-hidden="true" className="size-3.5" />
                  {t.c360LifetimeValue}
                </div>
                <div className="mt-1 text-lg font-bold" dir="ltr">
                  {formatMoney(customer?.lifetime_value ?? 0, record.payments.currency)}
                </div>
              </div>
              <div className="rounded-xl border border-border bg-muted/40 p-3 text-start">
                <div className="flex items-center gap-1 text-xs text-muted-foreground">
                  <CreditCard aria-hidden="true" className="size-3.5" />
                  {t.c360Outstanding}
                </div>
                <div className="mt-1 text-lg font-bold" dir="ltr">
                  {formatMoney(record.payments.outstanding, record.payments.currency)}
                </div>
              </div>
            </div>

            {/* Contact */}
            <div className="space-y-3">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                {t.c360Contact}
              </h3>
              <div className="space-y-2 text-sm">
                <div className="flex items-center justify-between gap-3 rounded-lg border border-border p-2.5">
                  <span className="flex items-center gap-2 text-xs text-muted-foreground">
                    <Phone aria-hidden="true" className="size-4" />
                    {t.phone}
                  </span>
                  <span className="truncate font-medium text-xs" dir="ltr">
                    {customer?.phone || "—"}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-3 rounded-lg border border-border p-2.5">
                  <span className="flex items-center gap-2 text-xs text-muted-foreground">
                    <Mail aria-hidden="true" className="size-4" />
                    {t.email}
                  </span>
                  <span className="truncate font-medium text-xs" dir="ltr">
                    {customer?.email || "—"}
                  </span>
                </div>
              </div>
            </div>

            {/* Tags — the API always returned these; the drawer ignored them. */}
            {record.tags.length > 0 && (
              <div className="space-y-3">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  {t.c360Tags}
                </h3>
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
              </div>
            )}

            {/* Quick actions */}
            <div className="space-y-3">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                {t.c360Overview}
              </h3>
              <div className="grid grid-cols-2 gap-2">
                <Button variant="outline" size="sm" asChild className="justify-start text-xs">
                  <Link href={`/inbox?customer=${customerId}`}>
                    <MessageSquare aria-hidden="true" className="size-3.5 me-2" />
                    {t.c360OpenConversation}
                  </Link>
                </Button>
                <Button variant="outline" size="sm" asChild className="justify-start text-xs">
                  <Link href={`/customers/${customerId}`}>
                    <ExternalLink aria-hidden="true" className="size-3.5 me-2" />
                    {t.customer360}
                  </Link>
                </Button>
              </div>
            </div>

            {/* Recent orders — already scoped to this customer by the server. */}
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  {t.c360Orders}
                </h3>
                <Link
                  href={`/customers/${customerId}`}
                  className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
                >
                  {t.viewAll}
                  <ExternalLink aria-hidden="true" className="size-3" />
                </Link>
              </div>

              {customerOrders.length === 0 ? (
                <div className="rounded-lg border border-dashed border-border p-4 text-center text-xs text-muted-foreground">
                  {t.c360OrdersEmpty}
                </div>
              ) : (
                <div className="space-y-2">
                  {customerOrders.slice(0, 4).map((order) => (
                    <div
                      key={order.id}
                      className="flex items-center justify-between gap-3 rounded-lg border border-border p-2.5 text-xs"
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
                </div>
              )}
            </div>

            {/* Latest notes — also previously dropped on the floor. */}
            {record.notes.length > 0 && (
              <div className="space-y-3">
                <h3 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  <NotebookPen aria-hidden="true" className="size-3.5" />
                  {t.c360Notes}
                </h3>
                <div className="space-y-2">
                  {record.notes.slice(0, 3).map((note) => (
                    <div key={note.id} className="rounded-lg border border-border p-2.5">
                      <div className="text-xs">{note.body}</div>
                      <div className="mt-1 flex items-center gap-1 text-[11px] text-muted-foreground">
                        <Clock aria-hidden="true" className="size-3" />
                        {formatDateTime(note.created_at)}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
