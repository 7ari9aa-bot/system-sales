import { UserRound } from "lucide-react";
import { Input } from "@/cashier/components/ui/input";

// بيانات الزبون الاختيارية أسفل جدول الفاتورة (حقل فوق حقل).
export default function PosCustomerFields({
  name,
  onNameChange,
  phone,
  onPhoneChange,
  customers = [],
}) {
  return (
    <div className="flex w-[230px] shrink-0 flex-col gap-1.5">
      <div className="relative">
        <UserRound className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={name}
          onChange={(e) => onNameChange(e.target.value)}
          list="pos-customers"
          placeholder="اسم الزبون (اختياري)"
          className="h-8 ps-9 text-[13px]"
          autoComplete="off"
          aria-label="اسم الزبون"
        />
        <datalist id="pos-customers">
          {customers.map((c) => (
            <option key={c.id} value={c.name} />
          ))}
        </datalist>
      </div>

      <Input
        value={phone}
        onChange={(e) => onPhoneChange(e.target.value)}
        placeholder="تليفون الزبون (اختياري)"
        className="num h-8 text-[13px]"
        autoComplete="off"
        aria-label="تليفون الزبون"
      />
    </div>
  );
}