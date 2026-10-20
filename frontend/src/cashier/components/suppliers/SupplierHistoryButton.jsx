import { History } from "lucide-react";
import { Button } from "@/cashier/components/ui/button";
import { BTN } from "@/cashier/components/ui-kit/ledgerStyles";

// زر فتح سجل توريدات المورد من داخل صف الجدول.
export default function SupplierHistoryButton({ onClick }) {
  return (
    <Button className={BTN} onClick={onClick}>
      <History />
      السجل
    </Button>
  );
}