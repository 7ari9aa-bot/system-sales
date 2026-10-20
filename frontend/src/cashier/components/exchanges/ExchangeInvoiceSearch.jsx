import { FileSearch, Search, TriangleAlert, X } from "lucide-react";
import { useState } from "react";
import { Badge } from "@/cashier/components/ui/badge";
import { Button } from "@/cashier/components/ui/button";
import { Input } from "@/cashier/components/ui/input";
import { fmtDateTime, fmtInt, fmtMoney } from "@/cashier/lib/format";

// شريط البحث عن الفاتورة الأصلية: رقم الفاتورة أو باركود أو هاتف العميل.
export default function ExchangeInvoiceSearch({ term, onTermChange, onSubmit, error, invoice, matches, onPick, onClear, quickPicks = [] }) {
  const [open, setOpen] = useState(false);
  const showList = open && !invoice && matches.length > 0;

  return (
    <div className="rounded-lg border border-border bg-card px-2.5 py-1.5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className="inline-flex items-center gap-1.5 text-[13px] font-bold text-muted-foreground">
          <FileSearch className="h-4 w-4" aria-hidden="true" />
          الفاتورة الأصلية
        </span>

        <div className="relative min-w-[220px] flex-1 sm:max-w-[300px]">
          <Input
            value={term}
            onChange={(e) => {
              onTermChange(e.target.value);
              setOpen(true);
            }}
            onFocus={() => setOpen(true)}
            onBlur={() => setTimeout(() => setOpen(false), 120)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                onSubmit();
                setOpen(false);
              }
            }}
            placeholder="رقم الفاتورة أو الباركود أو هاتف العميل"
            className="num h-8 pe-8 text-[12px] font-semibold"
            aria-label="بحث عن الفاتورة الأصلية"
          />
          {term && (
            <button
              type="button"
              onClick={() => {
                onClear();
                setOpen(true);
              }}
              aria-label="مسح البحث"
              className="absolute end-1.5 top-1/2 -translate-y-1/2 rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}

          {showList && (
            <ul className="absolute start-0 top-full z-20 mt-1 max-h-56 w-full overflow-y-auto scroll-slim rounded-lg border border-border bg-popover p-1 shadow-lg">
              {matches.map((inv) => (
                <li key={inv.id}>
                  <button
                    type="button"
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => {
                      onPick(inv);
                      setOpen(false);
                    }}
                    className="flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-start transition-colors hover:bg-accent"
                  >
                    <span className="min-w-0">
                      <span className="num block text-[12px] font-bold">{inv.number}</span>
                      <span className="num block text-[10px] text-muted-foreground">
                        {inv.customerName} • {fmtDateTime(inv.date)}
                      </span>
                    </span>
                    <span className="num shrink-0 text-[11px] font-semibold">{fmtMoney(inv.total)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <Button size="sm" className="h-8 gap-1.5" onClick={onSubmit}>
          <Search className="h-3.5 w-3.5" />
          بحث
        </Button>

        {invoice && (
          <>
            <span className="inline-flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md bg-accent/60 px-2 py-1 text-[11px]">
              <span className="num font-bold text-foreground">{invoice.number}</span>
              <span className="text-muted-foreground">
                العميل: <span className="font-semibold text-foreground">{invoice.customerName}</span>
              </span>
              <span className="num text-muted-foreground">{invoice.customerPhone}</span>
              <span className="num text-muted-foreground">{fmtDateTime(invoice.date)}</span>
              <span className="num font-semibold text-foreground">{fmtMoney(invoice.total)}</span>
              <Badge variant="secondary" className="num">
                {fmtInt(invoice.pieces)} قطعة
              </Badge>
            </span>
            <Button variant="ghost" size="sm" className="h-8 text-[12px] text-muted-foreground" onClick={onClear}>
              <X className="h-3.5 w-3.5" />
              تغيير الفاتورة
            </Button>
          </>
        )}

        {!invoice && !error && (
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted-foreground">
            <span>ابحث برقم الفاتورة أو هاتف العميل أو امسح باركود قطعة من الفاتورة.</span>
            {quickPicks.length > 0 && (
              <span className="flex flex-wrap items-center gap-1">
                <span className="font-semibold">فواتير جاهزة للتجربة:</span>
                {quickPicks.map((inv) => (
                  <button
                    key={inv.id}
                    type="button"
                    onClick={() => onPick(inv)}
                    title={`${inv.customerName} — ${inv.pieces} قطعة`}
                    className="num rounded-md border border-border bg-muted/60 px-1.5 py-0.5 font-bold text-foreground transition-colors hover:border-primary hover:bg-accent"
                  >
                    {inv.number}
                  </button>
                ))}
              </span>
            )}
          </span>
        )}

        {error && (
          <span className="inline-flex items-center gap-1.5 text-[11px] font-semibold text-rose-600">
            <TriangleAlert className="h-3.5 w-3.5" />
            {error}
          </span>
        )}
      </div>
    </div>
  );
}