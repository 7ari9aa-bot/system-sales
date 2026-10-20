import { Link } from "react-router-dom";
import { useEffect, useState } from "react";
import { ClipboardList, RotateCcw } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";

// رأس شاشة تسجيل المرتجع: رقم العملية والتاريخ والموظف، مع رابط سجل المرتجعات.
export default function ReturnHeaderBar({ number, employee }) {
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
          <RotateCcw className="h-[18px] w-[18px] text-primary" aria-hidden="true" />
          تسجيل مرتجع
        </h2>
        {number ? <p className="num text-[11px] font-semibold text-muted-foreground">رقم المرتجع {number}</p> : null}
      </div>

      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted-foreground">
        <span className="num font-semibold text-foreground">
          {dayLabel} {timeLabel}
        </span>
        <span aria-hidden="true">|</span>
        <span className="font-semibold text-foreground">{employee}</span>
      </div>

      <div className="ms-auto flex items-center gap-2">
        <Button asChild variant="outline" size="sm" className="h-8 gap-1.5 text-[12px] text-muted-foreground">
          <Link to="/cashier/returns/log">
            <ClipboardList className="h-3.5 w-3.5" />
            سجل المرتجعات
          </Link>
        </Button>
      </div>
    </header>
  );
}