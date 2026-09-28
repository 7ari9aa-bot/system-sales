"use client";

import * as React from "react";
import { useSearchParams, useRouter } from "next/navigation";
import type { ColumnDef } from "@tanstack/react-table";
import { Users, ChevronLeft } from "lucide-react";
import { useCustomers, useSavedViews, useTenantCurrency, type Customer } from "@/lib/queries";
import { t } from "@/lib/t";
import { formatMoney } from "@/lib/utils";
import { DataTable } from "@/components/data-table";
import { EmptyState, ErrorState, PageHeader } from "@/components/ui/states";
import { CustomerDrawer } from "@/components/customer-drawer";
import { SavedViewsSelector } from "@/components/saved-views-selector";
import { Badge } from "@/components/ui/badge";

export default function CustomersPage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  // §87: filters/sort/view/pagination are in the URL, not useState. This
  // makes every view deep-linkable, shareable, and survives a refresh.
  const selectedCustomerId = searchParams.get("customer") ?? null;
  const activeViewId = searchParams.get("view") ?? null;
  const urlQuery = searchParams.get("q") ?? "";
  // Owner IA 2026-09-27: Leads are a VIEW of Customers, not a second module —
  // ?filter=lead is the same server contract the old /leads page called.
  const leadFilter = searchParams.get("filter") === "lead";
  const customersQuery = useCustomers(leadFilter ? "lead" : undefined);
  const customers = customersQuery.data ?? [];
  // §47: the currency code is READ, never assumed — a customer's lifetime
  // value has no currency without it, and the old hard-coded "ج.م" label was
  // a bug for every tenant that trades in anything else.
  const currencyQuery = useTenantCurrency();
  const currency = currencyQuery.data?.currency ?? null;

  // §95 — العرض المحفوظ يحمل فلاتره؛ عند تفعيله نقود بها حالة الجدول
  const viewsQuery = useSavedViews("customers");
  const views = viewsQuery.data ?? [];
  const activeView = React.useMemo(
    () => views.find((v) => v.id === activeViewId) ?? null,
    [views, activeViewId],
  );
  /** البحث الفعّال: من فلاتر العرض المحفوظ إن كان مفعّلًا، وإلا من الـURL. */
  const activeQuery = activeView
    ? typeof activeView.filters.q === "string"
      ? activeView.filters.q
      : ""
    : urlQuery;

  const setUrlParams = (mutate: (params: URLSearchParams) => void) => {
    const params = new URLSearchParams(searchParams.toString());
    mutate(params);
    router.replace(`?${params.toString()}`, { scroll: false });
  };

  const setSelectedCustomerId = (id: string | null) =>
    setUrlParams((params) => {
      if (id) params.set("customer", id);
      else params.delete("customer");
    });

  /** تحرير البحث يدويًا يعني مغادرة العرض المحفوظ — نمسح view ونكتب q. */
  const handleSearchChange = (value: string) =>
    setUrlParams((params) => {
      if (value) params.set("q", value);
      else params.delete("q");
      params.delete("view");
    });

  /** اختيار عرض محفوظ: نفعّله ونطبّق فلاتره على الجدول (§95). */
  const handleSelectView = (view: {
    id: string;
    filters: Record<string, unknown>;
    sort: Record<string, unknown> | null;
    columns: string[] | null;
  }) => {
    setUrlParams((params) => {
      params.set("view", view.id);
      const q = typeof view.filters.q === "string" ? view.filters.q : "";
      if (q) params.set("q", q);
      else params.delete("q");
    });
  };

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
            {formatMoney(row.original.lifetime_value, currency)}
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
    [currency],
  );

  if (customersQuery.isError) {
    return (
      <div>
        <PageHeader title={t.customers} />
        <div className="mb-4 flex items-center gap-1 rounded-lg border border-border bg-muted/30 p-1 text-sm" role="tablist" aria-label={t.customers}>
          <button
            role="tab"
            aria-selected={!leadFilter}
            onClick={() => setUrlParams((params) => params.delete("filter"))}
            className={`rounded-md px-3 py-1.5 transition-colors ${!leadFilter ? "bg-surface font-semibold shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
            data-testid="customers-tab-all"
          >
            {t.customers}
          </button>
          <button
            role="tab"
            aria-selected={leadFilter}
            onClick={() => setUrlParams((params) => params.set("filter", "lead"))}
            className={`rounded-md px-3 py-1.5 transition-colors ${leadFilter ? "bg-surface font-semibold shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
            data-testid="customers-tab-leads"
            title={t.leadsViewHint}
          >
            {t.leadsView}
          </button>
        </div>
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
        <div className="mb-4 flex items-center gap-1 rounded-lg border border-border bg-muted/30 p-1 text-sm" role="tablist" aria-label={t.customers}>
          <button
            role="tab"
            aria-selected={!leadFilter}
            onClick={() => setUrlParams((params) => params.delete("filter"))}
            className={`rounded-md px-3 py-1.5 transition-colors ${!leadFilter ? "bg-surface font-semibold shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
            data-testid="customers-tab-all"
          >
            {t.customers}
          </button>
          <button
            role="tab"
            aria-selected={leadFilter}
            onClick={() => setUrlParams((params) => params.set("filter", "lead"))}
            className={`rounded-md px-3 py-1.5 transition-colors ${leadFilter ? "bg-surface font-semibold shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
            data-testid="customers-tab-leads"
            title={t.leadsViewHint}
          >
            {t.leadsView}
          </button>
        </div>
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
      <div className="mb-4 flex items-center gap-1 rounded-lg border border-border bg-muted/30 p-1 text-sm" role="tablist" aria-label={t.customers}>
        <button
          role="tab"
          aria-selected={!leadFilter}
          onClick={() => setUrlParams((params) => params.delete("filter"))}
          className={`rounded-md px-3 py-1.5 transition-colors ${!leadFilter ? "bg-surface font-semibold shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
          data-testid="customers-tab-all"
        >
          {t.customers}
        </button>
        <button
          role="tab"
          aria-selected={leadFilter}
          onClick={() => setUrlParams((params) => params.set("filter", "lead"))}
          className={`rounded-md px-3 py-1.5 transition-colors ${leadFilter ? "bg-surface font-semibold shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
          data-testid="customers-tab-leads"
          title={t.leadsViewHint}
        >
          {t.leadsView}
        </button>
      </div>
      <SavedViewsSelector
        entity="customers"
        currentFilters={{ q: activeQuery }}
        onSelect={handleSelectView}
        activeViewId={activeViewId}
        className="mb-3"
      />
      <DataTable
        columns={columns}
        data={customers}
        testid="customers-table"
        searchPlaceholder={t.searchCustomers}
        searchTestid="customer-search"
        globalFilter={activeQuery}
        onGlobalFilterChange={handleSearchChange}
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
