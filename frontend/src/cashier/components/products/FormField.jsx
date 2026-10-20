import { Label } from "@/cashier/components/ui/label";
import { FIELD, LABEL } from "@/cashier/components/products/formStyles";

// حقل موحّد: عنوان صغير فوق عنصر الإدخال.
export default function FormField({ label, children }) {
  return (
    <div className={FIELD}>
      <Label className={LABEL}>{label}</Label>
      {children}
    </div>
  );
}