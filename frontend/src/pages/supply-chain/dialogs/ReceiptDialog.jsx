/**
 * ReceiptDialog — نافذة مستقلة بدل ما تكون JSX مدفون في وعاء الصفحة.
 */
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function ReceiptDialog(props) {
  const {
    activePoForReceipt,
    handleConfirmCreateReceipt,
    isAr,
    receiptDialogOpen,
    receiptNotes,
    setReceiptDialogOpen,
    setReceiptNotes,
  } = props;

  return (
      <Dialog open={receiptDialogOpen} onOpenChange={setReceiptDialogOpen}>
        <DialogContent className="max-w-md" dir={isAr ? "rtl" : "ltr"}>
          <DialogHeader>
            <DialogTitle>{isAr ? "إنشاء إذن استلام بضائع من مورد" : "Create Goods Receipt"}</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleConfirmCreateReceipt} className="space-y-4 py-2">
            <div>
              <Label className="text-xs">{isAr ? "أمر الشراء" : "Purchase Order"}</Label>
              <Input
                value={activePoForReceipt?.number || ""}
                disabled
                className="mt-1 h-9 bg-[#FAF8F5]"
              />
            </div>
            <div>
              <Label className="text-xs">{isAr ? "ملاحظات إذن الاستلام" : "Receipt Notes"}</Label>
              <Input
                value={receiptNotes}
                onChange={(e) => setReceiptNotes(e.target.value)}
                placeholder={isAr ? "مثال: استلام دفعة أولى بحالة سليمة" : "Receipt notes"}
                className="mt-1 h-9"
              />
            </div>
            <DialogFooter className="mt-4">
              <Button type="submit" className="bg-[#E8761A] text-white hover:bg-[#D1650F]">
                {isAr ? "تأكيد وإنشاء الإذن" : "Confirm Receipt"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
  );
}
