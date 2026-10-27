import { useState } from "react";
import { UserRound, X } from "lucide-react";
import { Input } from "@/cashier/components/ui/input";

/**
 * Who the sale is for. Two separate things live here:
 *  - a REAL customer, picked from the search results (this is what the sale is booked to);
 *  - a free label, typed when no customer is picked (printed on the receipt, nothing more).
 * `required` comes from the till's profile: the picker is then mandatory and the label is not enough.
 */
export default function PosCustomerFields({
  name,
  onNameChange,
  phone,
  onPhoneChange,
  customer = null,
  onPick,
  results = [],
  searching = false,
  required = false,
}) {
  const [open, setOpen] = useState(false);

  if (customer) {
    return (
      <div className="flex w-[230px] shrink-0 flex-col gap-1.5">
        <div className="flex h-8 items-center justify-between gap-2 rounded-md border bg-muted/40 px-2.5 text-[13px]">
          <span className="flex min-w-0 items-center gap-1.5">
            <UserRound className="h-4 w-4 shrink-0 text-muted-foreground" />
            <span className="truncate font-bold" title={customer.name}>{customer.name}</span>
          </span>
          <button type="button" onClick={() => onPick(null)} aria-label="إزالة العميل" className="text-muted-foreground hover:text-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>
        {customer.phone ? <p className="num px-1 text-[11px] text-muted-foreground">{customer.phone}</p> : null}
      </div>
    );
  }

  const term = name.trim();
  return (
    <div className="relative flex w-[230px] shrink-0 flex-col gap-1.5">
      <div className="relative">
        <UserRound className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={name}
          onChange={(e) => {
            onNameChange(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          placeholder={required ? "ابحث عن العميل (مطلوب)" : "اسم الزبون (اختياري)"}
          className={`h-8 ps-9 text-[13px] ${required ? "border-destructive/60" : ""}`}
          autoComplete="off"
          aria-label="اسم الزبون"
          aria-required={required}
        />
        {open && term.length >= 2 ? (
          <ul role="listbox" className="absolute bottom-full z-20 mb-1 max-h-48 w-full overflow-auto rounded-md border bg-popover p-1 text-[13px] shadow-md">
            {searching ? <li className="px-2 py-1.5 text-muted-foreground">جارٍ البحث…</li> : null}
            {!searching && results.length === 0 ? <li className="px-2 py-1.5 text-muted-foreground">لا يوجد عميل بهذا الاسم</li> : null}
            {results.map((c) => (
              <li key={c.id}>
                <button
                  type="button"
                  role="option"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => {
                    onPick(c);
                    setOpen(false);
                  }}
                  className="flex w-full items-center justify-between gap-2 rounded px-2 py-1.5 text-start hover:bg-accent"
                >
                  <span className="truncate">{c.name}</span>
                  {c.phone ? <span className="num shrink-0 text-[11px] text-muted-foreground">{c.phone}</span> : null}
                </button>
              </li>
            ))}
          </ul>
        ) : null}
      </div>

      <Input
        value={phone}
        onChange={(e) => onPhoneChange(e.target.value)}
        placeholder="تليفون الزبون (لمتابعة فاتورته من الشات)"
        className="num h-8 text-[13px]"
        autoComplete="off"
        aria-label="تليفون الزبون"
      />
    </div>
  );
}
