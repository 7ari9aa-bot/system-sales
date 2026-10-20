import { Info } from "lucide-react";
import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";
import SectionCard from "@/cashier/components/ui-kit/SectionCard";
import { useAuth } from "@/lib/AuthContext";
import { shopFromUser } from "@/cashier/lib/shopIdentity";

const NOT_STORED = "غير مسجَّل بعد";

// بيانات المحل. الخادم يحتفظ حاليًا باسم المحل فقط؛ العنوان والهاتف والرقم الضريبي لا تُحفظ في أي مكان،
// فنعرضها فارغة بدل بيانات وهمية، ولا يوجد زر حفظ كي لا نوهم بحفظ لا يحدث.
export default function ShopProfileForm() {
  const { user } = useAuth();
  const shop = shopFromUser(user);

  return (
    <SectionCard title="بيانات المحل" description="الاسم المسجَّل للحساب. بقية البيانات تُضاف عند توفر حفظها في الخادم">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <Label className="mb-1.5 block text-xs text-muted-foreground">اسم المحل</Label>
          <Input value={shop.name} readOnly aria-label="اسم المحل" />
        </div>
        {[
          ["الفرع", "branch"],
          ["العنوان", "address"],
          ["الهاتف", "phone"],
          ["الرقم الضريبي", "taxId"],
        ].map(([label, id]) => (
          <div key={id} className={id === "address" ? "sm:col-span-2" : ""}>
            <Label className="mb-1.5 block text-xs text-muted-foreground">{label}</Label>
            <Input value="" readOnly disabled placeholder={NOT_STORED} aria-label={label} />
          </div>
        ))}
      </div>
      <p className="mt-3 flex items-start gap-1.5 text-[11px] text-muted-foreground">
        <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        الإيصالات المطبوعة تعرض اسم المحل أعلاه فقط حتى تُحفظ بقية البيانات.
      </p>
    </SectionCard>
  );
}
