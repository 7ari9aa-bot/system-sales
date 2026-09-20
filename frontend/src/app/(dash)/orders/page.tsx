"use client";

import * as React from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { Plus, ShoppingCart, Trash2 } from "lucide-react";
import { useCreateOrder, useCustomers, useOrders, useProducts, type Order } from "@/lib/queries";
import { t } from "@/lib/t";
import { formatDate, formatMoney } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/input";
import { Select } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui/states";
import { DataTable } from "@/components/data-table";

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

type Line = { variant_id: string; quantity: number };

export default function OrdersPage() {
  const [open, setOpen] = React.useState(false);
  const [customerId, setCustomerId] = React.useState("");
  const [lines, setLines] = React.useState<Line[]>([{ variant_id: "", quantity: 1 }]);

  const ordersQuery = useOrders();
  const productsQuery = useProducts();
  const customersQuery = useCustomers();
  const createOrder = useCreateOrder();

  const orders = ordersQuery.data ?? [];
  const customers = customersQuery.data ?? [];

  // فتح النموذج من قائمة "إنشاء" في الشريط العلوي (?new=1) أو من لوحة الأوامر
  React.useEffect(() => {
    if (typeof window !== "undefined" && new URLSearchParams(window.location.search).get("new") === "1") {
      setOpen(true);
    }
  }, []);

  const allVariants = React.useMemo(
    () =>
      (productsQuery.data ?? []).flatMap((p) =>
        (p.variants ?? []).map((v) => ({
          ...v,
          label: `${p.title}${v.title ? ` — ${v.title}` : ""}${v.sku ? ` (${v.sku})` : ""}`,
          price: Number(v.price),
        })),
      ),
    [productsQuery.data],
  );

  const total = lines.reduce((sum, line) => {
    const variant = allVariants.find((v) => v.id === line.variant_id);
    return sum + (variant ? variant.price * line.quantity : 0);
  }, 0);

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

  function submit() {
    const items = lines
      .filter((l) => l.variant_id)
      .map((l) => ({ variant_id: l.variant_id, quantity: l.quantity }));
    if (!customerId || items.length === 0) return;
    createOrder.mutate(
      { customer_id: customerId, items, channel: "dashboard" },
      {
        onSuccess: () => {
          setOpen(false);
          setLines([{ variant_id: "", quantity: 1 }]);
          setCustomerId("");
        },
      },
    );
  }

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

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>{t.createOrder}</DialogTitle>
            <DialogDescription>اختر العميل والأصناف — سيُسجَّل الطلب فورًا.</DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div>
              <Label htmlFor="o-customer">{t.customer}</Label>
              <Select id="o-customer" value={customerId} onChange={(e) => setCustomerId(e.target.value)}>
                <option value="">{t.chooseCustomer}</option>
                {customers.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} {c.phone ? `(${c.phone})` : ""}
                  </option>
                ))}
              </Select>
            </div>

            <div className="space-y-2">
              <Label>{t.lineItems}</Label>
              {lines.map((line, index) => (
                <div key={index} className="flex items-end gap-2">
                  <div className="flex-1">
                    <Select
                      aria-label={`${t.products} ${index + 1}`}
                      value={line.variant_id}
                      onChange={(e) =>
                        setLines(lines.map((l, i) => (i === index ? { ...l, variant_id: e.target.value } : l)))
                      }
                    >
                      <option value="">{t.chooseProduct}</option>
                      {allVariants.map((v) => (
                        <option key={v.id} value={v.id}>
                          {v.label} — {v.price.toFixed(2)}
                        </option>
                      ))}
                    </Select>
                  </div>
                  <Input
                    type="number"
                    dir="ltr"
                    min={1}
                    aria-label={t.quantity}
                    className="w-20"
                    value={line.quantity}
                    onChange={(e) =>
                      setLines(
                        lines.map((l, i) =>
                          i === index ? { ...l, quantity: Math.max(1, Number(e.target.value) || 1) } : l,
                        ),
                      )
                    }
                  />
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label="حذف السطر"
                    onClick={() => setLines(lines.filter((_, i) => i !== index))}
                    disabled={lines.length === 1}
                  >
                    <Trash2 aria-hidden="true" className="text-danger" />
                  </Button>
                </div>
              ))}
              <Button variant="outline" size="sm" onClick={() => setLines([...lines, { variant_id: "", quantity: 1 }])}>
                {t.addLine}
              </Button>
            </div>
          </div>

          <DialogFooter className="items-center justify-between gap-3 sm:justify-between">
            <strong dir="ltr">{formatMoney(total)}</strong>
            <Button
              onClick={submit}
              disabled={createOrder.isPending || !customerId || total === 0}
              data-testid="submit-order"
            >
              {t.createOrder}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
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
