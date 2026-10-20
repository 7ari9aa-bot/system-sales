import { LEDGER, TD, TH } from "@/cashier/components/ui-kit/ledgerStyles";
import { cn } from "@/cashier/lib/utils";

// جدول تقرير بنفس شكل جداول النظام: عنوان، رأس داكن، صفوف بخط شعري، وصف إجمالي — بلا ترقيم.
export default function ReportTable({ title, description, columns, rows, totals, footnote }) {
  const align = (value) => (value === "center" ? "text-center" : value === "end" ? "text-left" : "text-start");

  return (
    <div className={cn(LEDGER, "[&_tbody_tr:last-child]:border-b-0")}>
      {(title || description) && (
        <div className="border-b border-[#DED8CD] px-3.5 py-2">
          {title && <h2 className="font-heading text-[13px] font-bold text-[#33322E]">{title}</h2>}
          {description && <p className="mt-0.5 text-[11px] text-[#7A766C]">{description}</p>}
        </div>
      )}

      <div className="overflow-x-auto scroll-slim">
        <table className="w-full min-w-[720px]">
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c.key} className={cn(TH, "whitespace-nowrap px-2.5", align(c.align))}>
                  {c.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="px-3.5 py-10 text-center text-[12px] text-[#7A766C]">
                  لا توجد بيانات في هذه الفترة.
                </td>
              </tr>
            ) : (
              rows.map((row, index) => (
                <tr key={row.id ?? index}>
                  {columns.map((c) => (
                    <td key={c.key} className={cn(TD, "whitespace-nowrap", align(c.align), c.className)}>
                      {c.render ? c.render(row) : row[c.key]}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
          {totals && (
            <tfoot>
              <tr className="border-t-2 border-t-[#33322E] bg-[#F7F5F0]">
                {columns.map((c) => (
                  <td key={c.key} className={cn("num whitespace-nowrap px-2.5 py-2.5 text-[12px] font-semibold text-[#33322E]", align(c.align))}>
                    {totals[c.key] ?? ""}
                  </td>
                ))}
              </tr>
            </tfoot>
          )}
        </table>
      </div>

      {footnote && <p className="num border-t border-[#DED8CD] px-3.5 py-2 text-[11px] text-[#7A766C]">{footnote}</p>}
    </div>
  );
}