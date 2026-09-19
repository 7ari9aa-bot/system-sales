"use client";

import * as React from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { Users, ChevronLeft } from "lucide-react";
import { useCustomers, type Customer } from "@/lib/queries";
import { t } from "@/lib/t";
import { DataTable } from "@/components/data-table";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui/states";
import { CustomerDrawer } from "@/components/customer-drawer";
import { Badge } from "@/components/ui/badge";

export default function CustomersPage() {
  const [selectedCustomerId, setSelectedCustomerId] = React.useState<string | null>(null);
  const customersQuery = useCustomers();
  const customers = customersQuery.data ?? [];

  const columns = React.useMemo<ColumnDef<Customer, unknown>[]>(
    () => [
      {
        accessorKey: "name",
        header: t.name,
        cell: ({ row }) => (
          <div className="flex items-center gap-2">
            <span className="font-semibold text-foreground hover:text-primary transition-colors">
              {row.original.name}
            </span>
            {row.original.is_blocked && (
              <Badge variant="danger" className="text-[10px] px-1.5 py-0">
                محظور
              </Badge>
            )}
          </div>
        ),
      },
      {
        accessorFn: (row) => row.phone ?? "",
        id: "phone",
        header: t.phone,
        cell: ({ row }) => (
          <span dir="ltr" className="text-[13px]">
            {row.original.phone ?? "—"}
          </span>
        ),
      },
      {
        accessorFn: (row) => row.email ?? "",
        id: "email",
        header: t.email,
        cell: ({ row }) => (
          <span dir="ltr" className="text-[13px] text-muted-foreground">
            {row.original.email ?? "—"}
          </span>
        ),
      },
      {
        accessorKey: "lifetime_value",
        header: t.totalSpent,
        cell: ({ row }) => (
          <span dir="ltr" className="font-semibold">
            {Number(row.original.lifetime_value).toFixed(2)} ج.م
          </span>
        ),
      },
      {
        id: "actions",
        header: "",
        cell: () => (
          <div className="flex justify-end">
            <ChevronLeft className="size-4 text-muted-foreground" />
          </div>
        ),
      },
    ],
    [],
  );

  if (customersQuery.isError) {
    return (
      <div>
        <PageHeader title={t.customers} />
        <ErrorState
          message={(customersQuery.error as Error).message}
          onRetry={() => customersQuery.refetch()}
        />
      </div>
    );
  }

  if (customersQuery.isLoading) {
    return (
      <div>
        <PageHeader title={t.customers} />
        <div className="space-y-3 rounded-xl border border-border bg-card p-4" aria-busy="true" aria-label={t.loading}>
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-8 animate-pulse rounded-lg bg-muted" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div>
      <PageHeader title={t.customers} description="قاعدة عملائك، سجل الشراء، ومعلومات العميل الكاملة (360°)" />
      <DataTable
        columns={columns}
        data={customers}
        testid="customers-table"
        searchPlaceholder={t.searchCustomers}
        searchTestid="customer-search"
        onRowClick={(c) => setSelectedCustomerId(c.id)}
        empty={
          <EmptyState
            icon={<Users aria-hidden="true" />}
            title={t.noCustomers}
            description={t.noCustomersHint}
          />
        }
      />

      <CustomerDrawer
        customerId={selectedCustomerId}
        open={Boolean(selectedCustomerId)}
        onOpenChange={(open) => {
          if (!open) setSelectedCustomerId(null);
        }}
      />
    </div>
  );
}
