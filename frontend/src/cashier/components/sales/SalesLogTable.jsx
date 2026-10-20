import { useState } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown, Inbox } from "lucide-react";
import EmptyState from "@/cashier/components/ui-kit/EmptyState";
import { cn } from "@/cashier/lib/utils";

const TH = "whitespace-nowrap bg-[#F6F0E6] px-[14px] py-3 text-right align-middle text-[11px] font-bold text-[#6b6358]";
const TD = "num whitespace-nowrap border-t border-[#efe7da] px-[14px] py-[13px] text-[13px]";
const PAGE_BTN =
  "rounded-[10px] border border-[#e3d6c2] bg-white px-[14px] py-[6px] text-[12px] font-bold text-[#0F172A] transition-[background-color,box-shadow,border-color] duration-150 hover:border-[#F97316] hover:bg-[#FFF4E8] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#F97316] disabled:cursor-not-allowed disabled:opacity-50";

// جدول سجل المبيعات: رأس رملي، صفوف بخطوط رفيعة، ظهور متتابع، وشريط برتقالي على حافة الصف عند المرور.
// columns: [{ key, header, render?, sortValue?, align?, className? }]
export default function SalesLogTable({
  columns,
  rows,
  onRowClick,
  rowKey = (row) => row.id,
  pageSize = 10,
  emptyTitle = "لا توجد نتائج مطابقة",
  emptyDescription = "",
  emptyAction = null,
}) {
  const [sort, setSort] = useState(null);
  const [page, setPage] = useState(1);

  const sortable = columns.filter((c) => c.sortable !== false && c.key);
  const sorted = [...rows];
  if (sort) {
    const col = sortable.find((c) => c.key === sort.key);
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
    setSort((prev) => (!prev || prev.key !== key ? { key, dir: "asc" } : { key, dir: prev.dir === "asc" ? "desc" : "asc" }));
  }

  return (
    <div className="overflow-hidden rounded-b-[14px] border-[1.5px] border-t border-[#F97316] bg-white shadow-[0_18px_40px_-28px_rgba(15,23,42,.3)]">
      {rows.length === 0 ? (
        <EmptyState icon={Inbox} title={emptyTitle} description={emptyDescription} action={emptyAction} />
      ) : (
        <>
          <div className="overflow-x-auto scroll-slim">
            <table className="w-full border-collapse">
              <thead>
                <tr>
                  {columns.map((col) => (
                    <th
                      key={col.key}
                      className={cn(TH, col.align === "center" && "text-center", col.align === "end" && "text-left")}
                    >
                      {col.sortable === false ? (
                        col.header
                      ) : (
                        <button
                          type="button"
                          onClick={() => toggleSort(col.key)}
                          className="inline-flex items-center gap-1 transition-colors hover:text-[#F97316]"
                        >
                          {col.header}
                          {sort?.key === col.key ? (
                            sort.dir === "asc" ? (
                              <ArrowUp className="h-3 w-3 text-[#F97316]" />
                            ) : (
                              <ArrowDown className="h-3 w-3 text-[#F97316]" />
                            )
                          ) : (
                            <ArrowUpDown className="h-3 w-3 opacity-40" />
                          )}
                        </button>
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {visible.map((row, index) => (
                  <tr
                    key={rowKey(row)}
                    onClick={() => onRowClick?.(row)}
                    className="group animate-row-rise cursor-pointer transition-colors hover:bg-[#FFF7EE]"
                    style={{ animationDelay: `${0.05 + index * 0.015}s` }}
                  >
                    {columns.map((col, colIndex) => (
                      <td
                        key={col.key}
                        className={cn(
                          TD,
                          col.align === "center" && "text-center",
                          col.align === "end" && "text-left",
                          col.className,
                          colIndex === 0 && "transition-[box-shadow] duration-150 group-hover:shadow-[inset_-3px_0_0_#F97316]",
                        )}
                      >
                        {col.render ? col.render(row) : row[col.key]}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[#efe7da] bg-[#FFFDFA] px-4 py-3">
            <p className="num text-[11px] text-[#7a6f61]">
              عرض {start + 1}–{Math.min(start + pageSize, sorted.length)} من {sorted.length} نتيجة
            </p>
            <div className="flex items-center gap-2">
              <button type="button" className={PAGE_BTN} disabled={current === 1} onClick={() => setPage(current - 1)}>
                السابق
              </button>
              <span className="num text-[12px] font-semibold text-[#7a6f61]">
                صفحة {current} من {totalPages}
              </span>
              <button
                type="button"
                className={PAGE_BTN}
                disabled={current === totalPages}
                onClick={() => setPage(current + 1)}
              >
                التالي
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}