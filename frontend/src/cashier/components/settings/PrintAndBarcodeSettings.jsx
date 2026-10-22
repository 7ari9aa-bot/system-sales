import { Info, Printer } from "lucide-react";
import SectionCard from "@/cashier/components/ui-kit/SectionCard";

// الفاتورة والباركود. لا يوجد في الخادم حاليًا مكان يحفظ سطر أعلى/أسفل الفاتورة ولا مقاس الورق ولا عدد النسخ
// ولا بادئة الباركود، والإيصال والملصقات لا تقرأ أي إعداد من هنا. كانت الشاشة تعرض حقولًا وزر «حفظ» يقول
// «تم الحفظ» دون أن يُحفظ شيء، فأُزيلت كي لا نوهم بحفظ لا يحدث (نفس قاعدة «بيانات المحل»).
// مقاس الملصق وإظهار السعر والمحل يُختاران وقت الطباعة من نافذة معاينة الملصقات.
export default function PrintAndBarcodeSettings() {
  return (
    <SectionCard
      title="الفاتورة والباركود"
      description="شكل الفاتورة المطبوعة، مقاس الورق، وإعدادات توليد الباركود على الملصقات"
    >
      <div role="status" data-testid="print-not-stored" className="flex items-start gap-2 rounded-lg border border-border bg-muted/40 p-3 text-sm">
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        <div className="space-y-1">
          <p className="font-medium">لا توجد إعدادات محفوظة للفاتورة أو الباركود بعد.</p>
          <p className="text-xs text-muted-foreground">
            الفاتورة تُطبع بالشكل الثابت للنظام، وأكواد الباركود تُكتب أو تُولَّد بزر «توليد الباركودات» داخل نموذج المنتج.
            ستظهر هنا حقول التعديل عند توفر حفظها في الخادم.
          </p>
        </div>
      </div>
      <p className="mt-4 flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <Printer className="h-3.5 w-3.5" aria-hidden="true" />
        مقاس الملصق وإظهار السعر واسم المحل تختارها وقت الطباعة من معاينة الملصقات.
      </p>
    </SectionCard>
  );
}
