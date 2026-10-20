import { useEffect, useState } from "react";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import { Input } from "@/cashier/components/ui/input";

// تعليق الفاتورة: اسم اختياري يساعد الكاشير على معرفتها لاحقاً (مثلاً اسم العميل).
export default function HoldDialog({ open, onOpenChange, defaultLabel = "", pending = false, error = null, onConfirm }) {
  const [label, setLabel] = useState("");
  useEffect(() => {
    if (open) setLabel(defaultLabel);
  }, [open, defaultLabel]);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-sm">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">تعليق الفاتورة</DialogTitle>
          <DialogDescription>لن يتم حجز المخزون. ستجد الفاتورة في «الفواتير المعلقة» على هذه الوردية فقط.</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            onConfirm(label);
          }}
        >
          <Input aria-label="اسم الفاتورة المعلقة" placeholder="اسم العميل أو وصف قصير (اختياري)" value={label} maxLength={60} onChange={(e) => setLabel(e.target.value)} autoFocus />
          {error ? <p role="alert" className="text-xs font-semibold text-rose-600">{error}</p> : null}
          <div className="flex gap-2">
            <Button type="button" variant="outline" className="flex-1" onClick={() => onOpenChange(false)} disabled={pending}>
              رجوع
            </Button>
            <Button type="submit" className="flex-1 font-bold" disabled={pending}>
              {pending ? "جارٍ التعليق…" : "تعليق الفاتورة"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
