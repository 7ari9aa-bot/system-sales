import { Eye, History, MoreHorizontal, Printer, Repeat2 } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/cashier/components/ui/dropdown-menu";

// قائمة إجراءات لكل صف في سجل المبيعات.
export default function InvoiceRowActions({ invoice, onView, onPrint, onReturn, onLog }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 rounded-lg text-[#6b6358] transition-colors hover:bg-[#F6F0E6] hover:text-[#6b6358] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#F97316] focus-visible:ring-0"
          aria-label={`إجراءات الفاتورة ${invoice.number}`}
        >
          <MoreHorizontal className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56" dir="rtl">
        <DropdownMenuLabel className="num text-xs text-muted-foreground">{invoice.number}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem className="gap-2" onSelect={() => onView(invoice)}>
          <Eye className="h-4 w-4" />
          عرض تفاصيل الفاتورة
        </DropdownMenuItem>
        <DropdownMenuItem className="gap-2" onSelect={() => onPrint(invoice)}>
          <Printer className="h-4 w-4" />
          طباعة / إعادة طباعة
        </DropdownMenuItem>
        <DropdownMenuItem className="gap-2" onSelect={() => onReturn(invoice)}>
          <Repeat2 className="h-4 w-4" />
          استرجاع أو استبدال
        </DropdownMenuItem>
        <DropdownMenuItem className="gap-2" onSelect={() => onLog(invoice)}>
          <History className="h-4 w-4" />
          سجل العمليات
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}