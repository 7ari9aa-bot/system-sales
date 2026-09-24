"use client";

/** The order record — Wave 4's operations surface on the client.
 *
 *  Two things this screen is careful about, and they are the whole reason it is
 *  one file rather than more buttons on the list:
 *
 *  1. THE TWO AXES SIDE BY SIDE. `status` answers where the parcel is;
 *     `refund_state` answers how much of the money came back, and it is DERIVED
 *     from the ledger by the server (`orders/money.py:refund_state`), never
 *     stored as a status. The record shows both because a partially refunded
 *     order is still `delivered` — collapsing them is the mistake the backend
 *     spent ADR-053 making sure it never makes.
 *  2. MONEY IS NEVER COMPUTED HERE. `grand_total`, `refunded_total` and
 *     `net_collected` are three figures the server already added, rendered as
 *     read: string in, string out, `formatMoney` for display and no `Number()`
 *     anywhere on the money path (§47). A refund that lands re-reads them; the
 *     dialog never decrements them locally.
 *
 *  `GET /orders/{id}` carries no `customer_id`, so the link to the customer is
 *  resolved from the list query this route links back to (cached, and omitted
 *  when the row is not in it) rather than invented.
 */

import * as React from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowRight, Package, ShoppingCart } from "lucide-react";
import { useOrderDetail, useOrders, type OrderDetail } from "@/lib/queries";
import { t } from "@/lib/t";
import { formatMoney } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { OrderOpsPanel } from "@/components/orders/order-ops-panel";
import { ot } from "@/components/orders/labels";

const STATUS_VARIANT: Record<string, "warning" | "primary" | "success" | "danger" | "default"> = {
  pending: "warning",
  confirmed: "primary",
  processing: "primary",
  shipped: "primary",
  delivered: "success",
  completed: "success",
  cancelled: "danger",
  refunded: "danger",
  returned: "danger",
};

const REFUND_VARIANT: Record<string, "success" | "warning" | "danger" | "default"> = {
  none: "success",
  partial: "warning",
  full: "danger",
};

function MoneyFigure({ label, value, currency, testid }: { label: string; value: string; currency: string; testid: string }) {
  return (
    <div className="min-w-0">
      <p className="text-[11px] text-muted-foreground">{label}</p>
      {/* `dir=ltr`: digits and a currency code inside an RTL layout, so the amount
          reads the way the ledger wrote it. */}
      <strong dir="ltr" data-testid={testid} className="text-[15px] font-bold">
        {formatMoney(value, currency)}
      </strong>
    </div>
  );
}

function RecordSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true" aria-label={t.loading}>
      <Skeleton className="h-24" />
      <Skeleton className="h-32" />
      <Skeleton className="h-64" />
    </div>
  );
}

function OrderItems({ order }: { order: OrderDetail }) {
  const items = order.items ?? [];
  if (items.length === 0) {
    return (
      <EmptyState
        icon={<Package aria-hidden="true" />}
        title={ot.lineItems}
        testid="order-items-empty"
        className="py-6"
      />
    );
  }
  return (
    <ul className="space-y-2" data-testid="order-items-list">
      {items.map((item) => (
        <li
          key={item.id}
          data-testid={`order-item-${item.id}`}
          className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border p-2 text-[13px]"
        >
          <span className="min-w-0 truncate">
            {item.title ?? "—"}
            {item.sku ? (
              <span dir="ltr" className="ms-2 text-[11px] text-muted-foreground">
                {item.sku}
              </span>
            ) : null}
          </span>
          <span className="flex items-center gap-3">
            <span dir="ltr" className="text-muted-foreground">
              ×{item.quantity}
            </span>
            <span dir="ltr" className="text-muted-foreground">
              {formatMoney(item.unit_price, order.currency)}
            </span>
            <strong dir="ltr" data-testid="order-item-total">
              {formatMoney(item.total, order.currency)}
            </strong>
          </span>
        </li>
      ))}
    </ul>
  );
}

export default function OrderDetailPage() {
  const params = useParams<{ id: string }>();
  const orderId = typeof params?.id === "string" ? params.id : "";
  const detailQuery = useOrderDetail(orderId);
  // The detail route does not answer `customer_id`; the list this page links back
  // to does, and it is already cached. An order opened directly (deep link) may
  // not be in that page of results, so the link is omitted — never guessed.
  const ordersQuery = useOrders();
  const row = (ordersQuery.data ?? []).find((o) => o.id === orderId);

  const backLink = (
    <Link
      href="/orders"
      className="inline-flex items-center gap-1 text-[13px] font-semibold text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
    >
      <ArrowRight aria-hidden="true" className="size-3.5" />
      {ot.backToOrders}
    </Link>
  );

  if (!orderId || detailQuery.isLoading) {
    return (
      <div>
        {backLink}
        <div className="mt-3">
          <RecordSkeleton />
        </div>
      </div>
    );
  }

  if (detailQuery.isError || !detailQuery.data) {
    return (
      <div>
        {backLink}
        <div className="mt-4" data-testid="order-detail-error">
          <ErrorState
            message={detailQuery.error instanceof Error ? detailQuery.error.message : ot.orderNotFound}
            onRetry={() => void detailQuery.refetch()}
          />
        </div>
      </div>
    );
  }

  const order = detailQuery.data;
  // §47: the code is the one THIS order carries. No fallback, no symbol — the
  // order was priced in it, and the refund follows it.
  const currency = order.currency;

  return (
    <div data-testid="order-detail">
      {backLink}

      {/* ------------------------------------------------------- header -- */}
      <div className="mt-3 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="flex flex-wrap items-center gap-2 text-xl font-bold">
            <ShoppingCart aria-hidden="true" className="size-5 text-primary" />
            <span dir="ltr">{order.number}</span>
            {/* Two badges, two facts. Neither one is the other's synonym. */}
            <Badge variant={STATUS_VARIANT[order.status] ?? "default"} data-testid="order-status">
              {order.status}
            </Badge>
            <Badge variant={REFUND_VARIANT[order.refund_state] ?? "default"} data-testid="order-refund-state">
              {order.refund_state}
            </Badge>
          </h1>
          <p className="mt-1 text-[12px] text-muted-foreground">{ot.refundStateHint}</p>
          {row?.customer_id && (
            <Link
              href={`/customers/${row.customer_id}`}
              dir="ltr"
              className="mt-1 inline-block text-[12px] font-semibold text-primary underline-offset-4 hover:underline"
              data-testid="order-customer-link"
            >
              {t.customer}
            </Link>
          )}
        </div>
      </div>

      {/* ------------------------------------------------- money position -- */}
      <Card className="mt-4">
        <CardHeader className="space-y-0">
          <CardTitle className="text-sm">{ot.moneyPosition}</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-1 gap-4 sm:grid-cols-3" data-testid="order-money-position">
          <MoneyFigure label={ot.collectedGross} value={order.grand_total} currency={currency} testid="order-grand-total" />
          <MoneyFigure label={ot.refundedTotal} value={order.refunded_total} currency={currency} testid="order-refunded-total" />
          <MoneyFigure label={ot.netCollected} value={order.net_collected} currency={currency} testid="order-net-collected" />
        </CardContent>
      </Card>

      <Card className="mt-4">
        <CardHeader className="space-y-0">
          <CardTitle className="text-sm">{ot.lineItems}</CardTitle>
        </CardHeader>
        <CardContent>
          <OrderItems order={order} />
        </CardContent>
      </Card>

      {/* ------------------------------------------- payments, history, writes -- */}
      <div className="mt-4">
        <OrderOpsPanel order={order} />
      </div>
    </div>
  );
}
