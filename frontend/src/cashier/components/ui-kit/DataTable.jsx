import { ArrowDown, ArrowUp, ArrowUpDown, Inbox } from "lucide-react";
import { useState } from "react";
import { Button } from "@/cashier/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/cashier/components/ui/table";
import { cn } from "@/cashier/lib/utils";
import EmptyState from "@/cashier/components/ui-kit/EmptyState";

// جدول احترافي قابل للفرز والصفحات مع حالة فارغة واضحة.
// columns: [{ key, header, render?, sortValue?, align?, className?, headerClassName? }]
export default function DataTable({
  columns,
  rows,
  rowKey = (row) => row.id,
  pageSize = 8,
  initialSort = null,
  emptyTitle = "لا توجد نتائج مطابقة",
  emptyDescription = "جرّب تغيير الفلاتر أو البحث بكلمة أخرى.",
  emptyAction = null,
  onRowClick,
  rowClassName,
  toolbar = null,
  footerNote = null,
  className,
  toolbarClassName,
  footerClassName,
}) {
  const [sort, setSort] = useState(initialSort ? { key: initialSort, dir: "asc" } : null);
  const [page, setPage] = useState(1);

  const sortableColumns = columns.filter((c) => c.sortValue || c.key);
  const sorted = [...rows];
  if (sort) {
    const col = sortableColumns.find((c) => c.key === sort.key);
    if (col) {
      sorted.sort((a, b) => {
        const va = col.sortValue ? col.sortValue(a) : a[col.key];
        const vb = col.sortValue ? col.sortValue(b) : b[col.key];
        if (typeof va === "number" && typeof vb === "number") return sort.dir === "asc" ? va - vb : vb - va;
        return sort.dir === "asc"
          ? String(va ?? "").localeCompare(String(vb ?? ""), "ar")
          : String(vb ?? "").localeCompare(String(va ?? ""), "ar");
      });
    }
  }

  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const current = Math.min(page, totalPages);
  const start = (current - 1) * pageSize;
  const visible = sorted.slice(start, start + pageSize);

  function toggleSort(key) {
    setSort((prev) => {
      if (!prev || prev.key !== key) return { key, dir: "asc" };
      return { key, dir: prev.dir === "asc" ? "desc" : "asc" };
    });
  }

  return (
    <div className={cn("overflow-hidden rounded-xl border border-border bg-card card-soft", className)}>
      {toolbar && <div className={cn("border-b border-border px-3 py-2", toolbarClassName)}>{toolbar}</div>}

      {rows.length === 0 ? (
        <EmptyState icon={Inbox} title={emptyTitle} description={emptyDescription} action={emptyAction} />
      ) : (
        <>
          <div className="overflow-x-auto scroll-slim">
            <Table className="min-w-full">
              <TableHeader>
                <TableRow className="bg-muted/50 hover:bg-muted/50">
                  {columns.map((col) => (
                    <TableHead
                      key={col.key}
                      className={cn(
                        "h-8 whitespace-nowrap px-2.5 text-[11px] font-semibold text-muted-foreground",
                        col.align === "center" && "text-center",
                        col.align === "end" && "text-left",
                        col.headerClassName,
                      )}
                    >
                      {col.sortable === false ? (
                        col.header
                      ) : (
                        <button
                          type="button"
                          onClick={() => toggleSort(col.key)}
                          className="inline-flex items-center gap-1 transition-colors hover:text-foreground"
                        >
                          {col.header}
                          {sort?.key === col.key ? (
                            sort.dir === "asc" ? (
                              <ArrowUp className="h-3 w-3" />
                            ) : (
                              <ArrowDown className="h-3 w-3" />
                            )
                          ) : (
                            <ArrowUpDown className="h-3 w-3 opacity-40" />
                          )}
                        </button>
                      )}
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {visible.map((row) => (
                  <TableRow
                    key={rowKey(row)}
                    onClick={onRowClick ? () => onRowClick(row) : undefined}
                    className={cn(
                      "border-border/70 transition-colors hover:bg-accent/40",
                      onRowClick && "cursor-pointer",
                      typeof rowClassName === "function" ? rowClassName(row) : rowClassName,
                    )}
                  >
                    {columns.map((col) => (
                      <TableCell
                        key={col.key}
                        className={cn(
                          "whitespace-nowrap px-2.5 py-1.5 text-[13px]",
                          col.align === "center" && "text-center",
                          col.align === "end" && "text-left",
                          col.className,
                        )}
                      >
                        {col.render ? col.render(row) : row[col.key]}
                      </TableCell>
                    ))}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          <div className={cn("flex flex-wrap items-center justify-between gap-2 border-t border-border px-3 py-2", footerClassName)}>
            <p className="num text-[11px] text-muted-foreground">
              عرض {start + 1}–{Math.min(start + pageSize, sorted.length)} من {sorted.length} نتيجة
              {footerNote ? ` • ${footerNote}` : ""}
            </p>
            <div className="flex items-center gap-1">
              <Button variant="outline" size="sm" className="h-8" disabled={current === 1} onClick={() => setPage(current - 1)}>
                السابق
              </Button>
              <span className="num px-2 text-xs font-medium text-muted-foreground">
                صفحة {current} من {totalPages}
              </span>
              <Button variant="outline" size="sm" className="h-8" disabled={current === totalPages} onClick={() => setPage(current + 1)}>
                التالي
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}