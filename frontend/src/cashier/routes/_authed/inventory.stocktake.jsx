import { ClipboardList } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/cashier/components/ui/button";
import PageHeader from "@/cashier/components/ui-kit/PageHeader";
import StocktakeTable from "@/cashier/components/inventory/StocktakeTable";
import { stocktakeErrorMessage } from "@/cashier/api/stocktakeAdapter";
import { useOpenStocktake, useOpenStocktakeId, useStocktakeSheet } from "@/cashier/api/useStocktake";

const Notice = ({ children, role }) => (
  <div role={role} className="rounded-2xl border border-[#E3DED4] bg-white p-8 text-center text-[13px]">{children}</div>
);

export default function StocktakePage() {
  const openId = useOpenStocktakeId();
  const start = useOpenStocktake();
  const { sheet, isLoading, error } = useStocktakeSheet(openId.data);

  let body;
  if (openId.isLoading || (openId.data && isLoading)) {
    body = <Notice role="status">جارٍ تحميل الجرد…</Notice>;
  } else if (openId.isError || error) {
    const denied = (openId.error ?? error)?.status === 403;
    body = (
      <Notice role="alert">
        {denied ? "الجرد من صلاحية المدير أو المالك. اطلب منهم فتح الجرد." : "تعذّر تحميل الجرد. حاول مرة أخرى."}
      </Notice>
    );
  } else if (!openId.data || !sheet) {
    body = (
      <Notice>
        <ClipboardList className="mx-auto mb-3 h-8 w-8 text-muted-foreground" />
        <p className="mb-1 font-semibold">لا يوجد جرد مفتوح</p>
        <p className="mb-4 text-xs text-muted-foreground">
          عند البدء تُسجَّل الكميات الحالية. يمكنك متابعة البيع أثناء العدّ دون أن تضيع أي عملية بيع.
        </p>
        <Button
          disabled={start.isPending}
          onClick={() => start.mutate(undefined, { onError: (e) => toast.error(stocktakeErrorMessage(e, "open")) })}
        >
          بدء جرد جديد
        </Button>
      </Notice>
    );
  } else {
    body = <StocktakeTable key={sheet.id} sheet={sheet} />;
  }

  return (
    <div className="animate-fade-up">
      <PageHeader
        title="الجرد الفعلي"
        description="عدّ الأصناف وأدخل الكمية الفعلية. يظهر الفرق فورًا ولا تُعدّل الأرصدة إلا بعد اعتماد المدير."
      />
      {body}
    </div>
  );
}
