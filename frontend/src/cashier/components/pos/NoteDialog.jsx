import { useEffect, useState } from "react";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import { Textarea } from "@/cashier/components/ui/textarea";

// ملاحظة الفاتورة: تُطبع مع الفاتورة وتظهر للكاشير التالي.
export default function NoteDialog({
  open,
  onOpenChange,
  note,
  onSave,
  title = "ملاحظة على الفاتورة",
  description = "اكتب أي ملاحظة تخص البيع أو العميل، وستظهر مع الفاتورة.",
  placeholder = "مثال: العميل سيستبدل المقاس غدًا",
}) {
  const [draft, setDraft] = useState(note ?? "");

  useEffect(() => {
    if (open) setDraft(note ?? "");
  }, [open, note]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-md">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>

        <Textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={4} placeholder={placeholder} />

        <div className="flex gap-2">
          <Button variant="outline" className="flex-1" onClick={() => onOpenChange(false)}>
            رجوع
          </Button>
          <Button className="flex-1 font-bold" onClick={() => onSave(draft.trim())}>
            حفظ الملاحظة
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}