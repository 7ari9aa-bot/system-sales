import { Link } from "react-router-dom";
import { useEffect, useState } from "react";
import { ClipboardList, History, RefreshCw } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";

// رأس شاشة الاستبدال: رقم العملية والتاريخ والموظف، مع أزرار العمليات المعلقة وسجل الاستبدال.
export default function ExchangeHeaderBar({ number, employee, employees, onEmployeeChange, heldCount = 0, onRestore }) {
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 60000);
    return () => clearInterval(id);
  }, []);

  const dayLabel = now.toLocaleDateString("ar-EG-u-nu-latn", { weekday: "long", day: "2-digit", month: "2-digit", year: "numeric" });
  const timeLabel = now.toLocaleTimeString("ar-EG-u-nu-latn", { hour: "2-digit", minute: "2-digit" });

  return (
    <header className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <div className="min-w-0">
        <h2 className="font-heading flex items-center gap-2 text-xl font-extrabold leading-tight">
          <RefreshCw className="h-[18px] w-[18px] text-primary" aria-hidden="true" />
          استبدال منتج
        </h2>
        <p className="num text-[11px] font-semibold text-muted-foreground">رقم العملية {number}</p>
      </div>

      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted-foreground">
        <span className="num font-semibold text-foreground">
          {dayLabel} {timeLabel}
        </span>
        <span aria-hidden="true">|</span>
        <select
          value={employee}
          onChange={(e) => onEmployeeChange(e.target.value)}
          aria-label="الموظف المسؤول"
          className="rounded-md border border-border bg-card px-1.5 py-0.5 text-[11px] font-semibold text-foreground outline-none focus-visible:ring-1 focus-visible:ring-ring"
        >
          {employees.map((e) => (
            <option key={e.id} value={e.name}>
              {e.name} — {e.job}
            </option>
          ))}
        </select>
      </div>

      <div className="ms-auto flex items-center gap-2">
        <Button variant="outline" size="sm" className="h-8 gap-1.5 text-[12px]" onClick={onRestore}>
          <History className="h-3.5 w-3.5" />
          عمليات معلقة
          <span className="num rounded-full bg-primary/10 px-1.5 py-0.5 text-[10px] font-bold text-primary">{heldCount}</span>
        </Button>

        <Button asChild variant="outline" size="sm" className="h-8 gap-1.5 text-[12px] text-muted-foreground">
          <Link to="/cashier/exchanges/log">
            <ClipboardList className="h-3.5 w-3.5" />
            سجل الاستبدال
          </Link>
        </Button>
      </div>
    </header>
  );
}