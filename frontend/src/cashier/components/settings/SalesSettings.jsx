import { Info, Percent } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import SectionCard from "@/cashier/components/ui-kit/SectionCard";
import { posApi } from "@/cashier/api/posApi";
import { ceilingPct } from "@/cashier/lib/discountCeiling";

// حد الخصم المسموح للكاشير بدون مدير. هو نفس الرقم الذي يفرضه الخادم عند كل بيع (فوقه يلزم رقم سري للمدير)،
// ويُحفظ على ملف الكاشير ويُعدَّل من إعدادات نقاط البيع في النظام. هنا للعرض فقط حتى لا يوجد مكانان لتعديل نفس الرقم.
// (لا توجد إعدادات طرق دفع: كل البيع نقدي حاليًا.)
export default function SalesSettings() {
  const profiles = useQuery({ queryKey: ["cashier", "profiles"], queryFn: async () => (await posApi.listProfiles()) ?? [] });
  const list = (profiles.data ?? []).filter((p) => p.is_active !== false);

  return (
    <SectionCard title="حدود الخصم" description="أقصى خصم يمنحه الكاشير على الفاتورة أو الصنف قبل أن يطلب النظام رقم المدير السري">
      {profiles.isLoading ? (
        <p className="text-sm text-muted-foreground" role="status">جارٍ التحميل…</p>
      ) : profiles.isError ? (
        <p className="text-sm text-destructive" role="alert">تعذّر تحميل إعدادات الكاشير: {profiles.error?.message || "خطأ غير معروف"}</p>
      ) : list.length === 0 ? (
        <p className="text-sm text-muted-foreground">لا يوجد ملف كاشير بعد. يُنشأ عند تجهيز أول جهاز كاشير.</p>
      ) : (
        <ul className="space-y-2">
          {list.map((p) => (
            <li key={p.id} className="flex items-center gap-2 text-sm">
              <Percent className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
              <span className="text-muted-foreground">{list.length > 1 ? `${p.name}: ` : ""}الحد الحالي</span>
              <strong className="num" data-testid={`ceiling-${p.code}`}>{ceilingPct(p)}%</strong>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-4 flex items-start gap-1.5 text-[11px] text-muted-foreground">
        <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        <span>
          الخصم الأعلى من هذا الحد لا يُمنع: يطلب النظام رقم مدير سري ويُسجَّل من وافق عليه. لتغيير الحد افتح{" "}
          <Link to="/settings/pos" className="underline">إعدادات نقاط البيع</Link>.
        </span>
      </p>
    </SectionCard>
  );
}
