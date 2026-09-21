"use client";

import * as React from "react";
import {
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type RowSelectionState,
  type SortingState,
} from "@tanstack/react-table";
import { ChevronLeft, ChevronRight, ChevronsUpDown, Search, ArrowUp, ArrowDown } from "lucide-react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/input";
import { t } from "@/lib/t";
import { cn } from "@/lib/utils";

type DataTableProps<TData> = {
  columns: ColumnDef<TData, unknown>[];
  data: TData[];
  /** testid أساسي للجدول */
  testid?: string;
  searchPlaceholder?: string;
  searchTestid?: string;
  initialPageSize?: number;
  enableSelection?: boolean;
  /** حالة فارغة كاملة تُعرض عندما لا توجد بيانات أصلًا */
  empty?: React.ReactNode;
  onRowClick?: (row: TData) => void;
  className?: string;
  /** §95/§87 — بحث مُتحكَّم فيه اختياريًا: للصفحات التي تربط البحث بالـURL
   *  أو بفلاتر عرض محفوظ. بدون هذين الخصائين يظل البحث حالة داخلية. */
  globalFilter?: string;
  onGlobalFilterChange?: (value: string) => void;
};

export function DataTable<TData>({
  columns,
  data,
  testid,
  searchPlaceholder = t.searchTable,
  searchTestid,
  initialPageSize = 10,
  enableSelection = true,
  empty,
  onRowClick,
  className,
  globalFilter: globalFilterProp,
  onGlobalFilterChange,
}: DataTableProps<TData>) {
  const [sorting, setSorting] = React.useState<SortingState>([]);
  const [internalFilter, setInternalFilter] = React.useState("");
  const [rowSelection, setRowSelection] = React.useState<RowSelectionState>({});
  const [pagination, setPagination] = React.useState({ pageIndex: 0, pageSize: initialPageSize });

  // بحث مُتحكَّم فيه عند تمرير onGlobalFilterChange، وإلا حالة داخلية كما كان.
  const isControlled = typeof onGlobalFilterChange === "function";
  const globalFilter = isControlled ? (globalFilterProp ?? "") : internalFilter;

  // تغيير الفلتر من الخارج (عرض محفوظ / رابط) يعيد الترقيم لأول صفحة.
  const previousExternal = React.useRef(globalFilterProp);
  React.useEffect(() => {
    if (!isControlled || globalFilterProp === previousExternal.current) return;
    previousExternal.current = globalFilterProp;
    setPagination((p) => (p.pageIndex === 0 ? p : { ...p, pageIndex: 0 }));
  }, [isControlled, globalFilterProp]);

  const tableColumns = React.useMemo<ColumnDef<TData, unknown>[]>(() => {
    if (!enableSelection) return columns;
    const selectionColumn: ColumnDef<TData, unknown> = {
      id: "__select",
      enableSorting: false,
      enableGlobalFilter: false,
      size: 40,
      header: ({ table }) => (
        <input
          type="checkbox"
          aria-label={t.selectAll}
          className="size-4 cursor-pointer accent-[var(--color-primary)]"
          checked={table.getIsAllPageRowsSelected()}
          ref={(el) => {
            if (el) el.indeterminate = table.getIsSomePageRowsSelected();
          }}
          onChange={(e) => table.toggleAllPageRowsSelected(e.target.checked)}
        />
      ),
      cell: ({ row }) => (
        <input
          type="checkbox"
          aria-label={t.selectRow}
          className="size-4 cursor-pointer accent-[var(--color-primary)]"
          checked={row.getIsSelected()}
          disabled={!row.getCanSelect()}
          onChange={(e) => row.toggleSelected(e.target.checked)}
        />
      ),
    };
    return [selectionColumn, ...columns];
  }, [columns, enableSelection]);

  const table = useReactTable({
    data,
    columns: tableColumns,
    state: { sorting, globalFilter, rowSelection, pagination },
    onSortingChange: setSorting,
    onGlobalFilterChange: (updater) => {
      const next = typeof updater === "function" ? updater(globalFilter) : updater;
      if (isControlled) onGlobalFilterChange(next);
      else setInternalFilter(next);
    },
    onRowSelectionChange: setRowSelection,
    onPaginationChange: setPagination,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    globalFilterFn: "includesString",
    initialState: {},
  });

  const rows = table.getRowModel().rows;
  const totalRows = table.getFilteredRowModel().rows.length;
  const selectedCount = table.getSelectedRowModel().rows.length;
  const pageCount = Math.max(1, table.getPageCount());

  return (
    <div className={cn("flex flex-col gap-3", className)}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="relative w-full max-w-xs">
          <Search
            aria-hidden="true"
            className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
          />
          <Input
            value={globalFilter}
            onChange={(e) => {
              if (isControlled) onGlobalFilterChange(e.target.value);
              else setInternalFilter(e.target.value);
              setPagination((p) => ({ ...p, pageIndex: 0 }));
            }}
            placeholder={searchPlaceholder}
            className="ps-9"
            data-testid={searchTestid}
          />
        </div>
        {enableSelection && selectedCount > 0 && (
          <span className="text-[13px] font-semibold text-primary" data-testid={testid ? `${testid}-selected-count` : undefined}>
            {selectedCount} {t.rowsSelected}
          </span>
        )}
      </div>

      <div className="overflow-hidden rounded-xl border border-border bg-card shadow-xs" data-testid={testid}>
        <Table>
          <TableHeader>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id} className="bg-muted/50 hover:bg-muted/50">
                {headerGroup.headers.map((header) => {
                  const canSort = header.column.getCanSort();
                  const sorted = header.column.getIsSorted();
                  return (
                    <TableHead key={header.id} style={{ width: header.getSize() !== 150 ? header.getSize() : undefined }}>
                      {header.isPlaceholder ? null : canSort ? (
                        <button
                          type="button"
                          onClick={header.column.getToggleSortingHandler()}
                          className="inline-flex items-center gap-1 transition-colors duration-150 hover:text-foreground"
                          aria-label={
                            sorted === "asc" ? t.sortDesc : sorted === "desc" ? t.sortAsc : t.sortAsc
                          }
                        >
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          {sorted === "asc" ? (
                            <ArrowUp className="size-3.5 text-primary" aria-hidden="true" />
                          ) : sorted === "desc" ? (
                            <ArrowDown className="size-3.5 text-primary" aria-hidden="true" />
                          ) : (
                            <ChevronsUpDown className="size-3.5 opacity-50" aria-hidden="true" />
                          )}
                        </button>
                      ) : (
                        flexRender(header.column.columnDef.header, header.getContext())
                      )}
                    </TableHead>
                  );
                })}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {rows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={tableColumns.length} className="p-0 hover:bg-card">
                  {data.length === 0 && empty ? (
                    empty
                  ) : (
                    <p className="px-4 py-10 text-center text-[13px] text-muted-foreground">{t.noTableResults}</p>
                  )}
                </TableCell>
              </TableRow>
            ) : (
              rows.map((row) => (
                <TableRow
                  key={row.id}
                  data-state={row.getIsSelected() ? "selected" : undefined}
                  className={cn(onRowClick && "cursor-pointer hover:bg-muted/70 transition-colors")}
                  onClick={(e) => {
                    if ((e.target as HTMLElement).closest("input, button, a")) return;
                    onRowClick?.(row.original);
                  }}
                >
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 text-[13px] text-muted-foreground">
        <span dir="ltr">
          {totalRows.toLocaleString("en-US")}
        </span>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2">
            {t.rowsPerPage}
            <Select
              value={String(pagination.pageSize)}
              onChange={(e) => table.setPageSize(Number(e.target.value))}
              className="h-8 w-18"
              aria-label={t.rowsPerPage}
            >
              {[10, 20, 50].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </Select>
          </label>
          <span>{t.pageOf(pagination.pageIndex + 1, pageCount)}</span>
          <div className="flex items-center gap-1">
            <Button
              variant="outline"
              size="icon-sm"
              onClick={() => table.previousPage()}
              disabled={!table.getCanPreviousPage()}
              aria-label={t.prevPage}
            >
              <ChevronRight aria-hidden="true" />
            </Button>
            <Button
              variant="outline"
              size="icon-sm"
              onClick={() => table.nextPage()}
              disabled={!table.getCanNextPage()}
              aria-label={t.nextPage}
            >
              <ChevronLeft aria-hidden="true" />
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
