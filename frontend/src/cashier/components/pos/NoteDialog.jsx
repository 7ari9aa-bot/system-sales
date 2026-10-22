import { useEffect, useState } from "react";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import { Textarea } from "@/cashier/components/ui/textarea";

/** The longest remark the server keeps on an invoice (it answers 422 beyond this). */
export const NOTE_MAX = 512;

// ملاحظة على الفاتورة: نص حر (مثلاً «هدية» أو «التوصيل بكرة»). لا تغيّر الإجمالي ولا المخزون.
export default function NoteDialog({ open, onOpenChange, value = "", onSave }) {
  const [text, setText] = useState("");
  useEffect(() => {
    if (open) setText(value);
  }, [open, value]);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-sm">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">ملاحظة على الفاتورة</DialogTitle>
          <DialogDescription>تُحفظ مع الفاتورة ولا تؤثر على الإجمالي أو المخزون.</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            onSave(text.trim());
          }}
        >
          <Textarea aria-label="ملاحظة الفاتورة" placeholder="اكتب ملاحظة (اختياري)" rows={4} maxLength={NOTE_MAX} value={text} onChange={(e) => setText(e.target.value)} autoFocus />
          <p className="num text-left text-[11px] text-muted-foreground">
            {text.length}/{NOTE_MAX}
          </p>
          <div className="flex gap-2">
            <Button type="button" variant="outline" className="flex-1" onClick={() => onOpenChange(false)}>
              رجوع
            </Button>
            {value ? (
              <Button type="button" variant="outline" className="flex-1" onClick={() => onSave("")}>
                مسح
              </Button>
            ) : null}
            <Button type="submit" className="flex-1 font-bold">
              حفظ
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
