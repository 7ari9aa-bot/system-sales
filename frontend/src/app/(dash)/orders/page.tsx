"use client";

import * as React from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { Plus, ShoppingCart } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCustomers, useOrders, type Order } from "@/lib/queries";
import { useCreateDialog } from "@/lib/use-create-dialog";
import { t } from "@/lib/t";
import { formatDate, formatMoney } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui/states";
import { DataTable } from "@/components/data-table";
import { SavedViewsSelector } from "@/components/saved-views-selector";
import { CreateOrderDialog } from "@/components/orders/create-order-dialog";

const STATUS_VARIANT: Record<string, "warning" | "primary" | "success" | "danger" | "default"> = {
  pending: "warning",
  confirmed: "primary",
  processing: "primary",
  shipped: "primary",
  delivered: "success",
  completed: "success",
  cancelled: "danger",
  refunded: "danger",
};

export default function OrdersPage() {
  const [open, setOpen] = useCreateDialog();
  const router = useRouter();

  const ordersQuery = useOrders();
  const customersQuery = useCustomers();

  const orders = ordersQuery.data ?? [];
  // Memoised so the `columns` memo below has a stable dependency: `?? []` made
  // a fresh array on every render, which re-created the whole table definition.
  const customers = React.useMemo(() => customersQuery.data ?? [], [customersQuery.data]);

  const columns = React.useMemo<ColumnDef<Order, unknown>[]>(
    () => [
      {
        accessorKey: "number",
        header: t.orderNumber,
        cell: ({ row }) => (
          <span dir="ltr" className="font-semibold">
            {row.original.number}
          </span>
        ),
      },
      {
        accessorFn: (row) => customers.find((c) => c.id === row.customer_id)?.name ?? row.customer_id,
        id: "customer",
        header: t.customer,
        cell: ({ row }) => {
          const name = customers.find((c) => c.id === row.original.customer_id)?.name;
          return (
            <span dir="ltr" className="text-[13px] text-muted-foreground">
              {name ?? `${row.original.customer_id.slice(0, 8)}…`}
            </span>
          );
        },
      },
      {
        accessorKey: "grand_total",
        header: t.grandTotal,
        cell: ({ row }) => (
          <span dir="ltr" className="font-semibold">
            {formatMoney(row.original.grand_total, row.original.currency)}
          </span>
        ),
      },
      {
        accessorKey: "status",
        header: t.status,
        cell: ({ row }) => (
          <Badge variant={STATUS_VARIANT[row.original.status] ?? "default"}>{row.original.status}</Badge>
        ),
      },
      {
        accessorFn: (row) => new Date(row.placed_at ?? row.created_at).getTime(),
        id: "date",
        header: t.date,
        cell: ({ row }) => (
          <span dir="ltr" className="text-[13px] text-muted-foreground">
            {formatDate(row.original.placed_at ?? row.original.created_at)}
          </span>
        ),
      },
    ],
    [customers],
  );

  return (
    <div>
      <PageHeader
        title={t.orders}
        description="متابعة كل الطلبات وحالاتها"
        actions={
          <Button onClick={() => setOpen(true)} data-testid="toggle-order-form">
            <Plus aria-hidden="true" />
            {t.createOrder}
          </Button>
        }
      />

      <SavedViewsSelector
        entity="orders"
        currentFilters={{}}
        onSelect={() => {}}
        activeViewId={null}
        className="mb-3"
      />

      {ordersQuery.isError ? (
        <ErrorState
          message={(ordersQuery.error as Error).message}
          onRetry={() => ordersQuery.refetch()}
        />
      ) : ordersQuery.isLoading ? (
        <TableLoading />
      ) : (
        <DataTable
          columns={columns}
          data={orders}
          testid="orders-table"
          // The record page is where an order is operated on — the money
          // position, the payment ledger and the four writes live there, not on
          // this table.
          onRowClick={(order) => router.push(`/orders/${order.id}`)}
          empty={
            <EmptyState
              icon={<ShoppingCart aria-hidden="true" />}
              title={t.noOrders}
              description={t.noOrdersHint}
              testid="orders-empty"
              action={
                <Button size="sm" onClick={() => setOpen(true)}>
                  <Plus aria-hidden="true" />
                  {t.createOrder}
                </Button>
              }
            />
          }
        />
      )}

      {/* The create form: line items, the money terms the server has always
          accepted (`discount_total` / `shipping_total` / `tax_total`), the total
          computed the way `money.py:compute_totals` computes it, and the single
          Idempotency-Key this dialog open owns. It lives in its own component so
          the table above stays about reading. */}
      <CreateOrderDialog open={open} onOpenChange={setOpen} customers={customers} />
    </div>
  );
}

function TableLoading() {
  return (
    <Card className="space-y-3 p-4" aria-busy="true" aria-label={t.loading}>
      <div className="h-9 w-64 animate-pulse rounded-lg bg-muted" />
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="flex gap-3">
          <div className="h-8 flex-1 animate-pulse rounded-lg bg-muted" />
          <div className="h-8 flex-1 animate-pulse rounded-lg bg-muted" />
          <div className="h-8 flex-1 animate-pulse rounded-lg bg-muted" />
          <div className="h-8 w-24 animate-pulse rounded-lg bg-muted" />
        </div>
      ))}
    </Card>
  );
}
