"use client";

import * as React from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { Package, Plus } from "lucide-react";
import { useCreateProduct, useProducts, type Product } from "@/lib/queries";
import { useCreateDialog } from "@/lib/use-create-dialog";
import { t } from "@/lib/t";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input, Label } from "@/components/ui/input";
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

const STATUS_VARIANT: Record<string, "success" | "default" | "danger"> = {
  active: "success",
  draft: "default",
  archived: "danger",
};

export default function ProductsPage() {
  const [open, setOpen] = useCreateDialog();
  const [title, setTitle] = React.useState("");
  const [price, setPrice] = React.useState("");

  const productsQuery = useProducts();
  const createProduct = useCreateProduct();
  const products = productsQuery.data ?? [];

  const columns = React.useMemo<ColumnDef<Product, unknown>[]>(
    () => [
      {
        accessorKey: "title",
        header: t.productTitle,
        cell: ({ row }) => <span className="font-semibold">{row.original.title}</span>,
      },
      {
        accessorFn: (row) => row.variants?.[0]?.sku ?? "",
        id: "sku",
        header: t.sku,
        cell: ({ row }) => (
          <span dir="ltr" className="text-[13px] text-muted-foreground">
            {row.original.variants?.[0]?.sku ?? "—"}
          </span>
        ),
      },
      {
        accessorFn: (row) => Number(row.variants?.[0]?.price ?? 0),
        id: "price",
        header: t.price,
        cell: ({ row }) => (
          <span dir="ltr" className="font-semibold">
            {row.original.variants?.[0]?.price ?? "—"}
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
    ],
    [],
  );

  function submit() {
    if (!title.trim() || !price) return;
    createProduct.mutate(
      {
        title,
        slug: `${title.trim().toLowerCase().replace(/\s+/g, "-")}-${Date.now().toString(36)}`,
        price: Number(price),
      },
      {
        onSuccess: () => {
          setOpen(false);
          setTitle("");
          setPrice("");
        },
      },
    );
  }

  return (
    <div>
      <PageHeader
        title={t.products}
        description="كتالوج منتجاتك وأسعارها"
        actions={
          <Button onClick={() => setOpen(true)} data-testid="open-product-form">
            <Plus aria-hidden="true" />
            {t.addProduct}
          </Button>
        }
      />

      {productsQuery.isError ? (
        <ErrorState
          message={(productsQuery.error as Error).message}
          onRetry={() => productsQuery.refetch()}
        />
      ) : productsQuery.isLoading ? (
        <div className="space-y-3 rounded-xl border border-border bg-card p-4" aria-busy="true" aria-label={t.loading}>
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-8 animate-pulse rounded-lg bg-muted" />
          ))}
        </div>
      ) : (
        <DataTable
          columns={columns}
          data={products}
          testid="products-table"
          empty={
            <EmptyState
              icon={<Package aria-hidden="true" />}
              title="لا توجد منتجات بعد"
              description="أضف أول منتج ليظهر للوكلاء في المحادثات."
              action={
                <Button size="sm" onClick={() => setOpen(true)}>
                  <Plus aria-hidden="true" />
                  {t.addProduct}
                </Button>
              }
            />
          }
        />
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.addProduct}</DialogTitle>
            <DialogDescription>أقل حقلين مطلوبين: الاسم والسعر.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label htmlFor="p-title">{t.productTitle}</Label>
              <Input id="p-title" value={title} onChange={(e) => setTitle(e.target.value)} />
            </div>
            <div>
              <Label htmlFor="p-price">{t.price}</Label>
              <Input
                id="p-price"
                type="number"
                dir="ltr"
                min="0"
                step="0.01"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              onClick={submit}
              disabled={createProduct.isPending || !title.trim() || !price}
              data-testid="create-product"
            >
              {t.addProduct}
            </Button>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              {t.cancel}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
