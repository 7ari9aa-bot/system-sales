import { useEffect, useState } from "react";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";

const blank = { name: "", company: "", agent: "", phone: "", city: "", status: "active" };

// إضافة مورد أو تعديل بياناته. المورد اللي له تعاملات ما بيتمسحش: بيتوقف بس.
export default function SupplierFormDialog({ open, onOpenChange, supplier, onSubmit, pending, error }) {
  const [form, setForm] = useState(blank);
  const [localError, setLocalError] = useState("");

  useEffect(() => {
    if (!open) return;
    setForm(supplier ? { name: supplier.name, company: supplier.company, agent: supplier.agent, phone: supplier.phone, city: supplier.city, status: supplier.status } : blank);
    setLocalError("");
  }, [open, supplier]);

  const set = (field, value) => setForm((prev) => ({ ...prev, [field]: value }));

  function submit() {
    if (!form.name.trim()) {
      setLocalError("اكتب اسم المورد");
      return;
    }
    setLocalError("");
    onSubmit({
      name: form.name.trim(),
      company: form.company.trim() || null,
      contact_name: form.agent.trim() || null,
      phone: form.phone.trim() || null,
      city: form.city.trim() || null,
      ...(supplier ? { status: form.status } : {}),
    });
  }

  const shown = localError || error;
  const field = (label, key, props = {}) => (
    <div>
      <Label className="mb-1.5 block text-xs text-muted-foreground">{label}</Label>
      <Input value={form[key]} onChange={(e) => set(key, e.target.value)} {...props} />
    </div>
  );

  return (
    <Dialog open={open} onOpenChange={(next) => !pending && onOpenChange(next)}>
      <DialogContent dir="rtl" className="max-w-xl">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">{supplier ? "تعديل بيانات المورد" : "إضافة مورد جديد"}</DialogTitle>
          <DialogDescription>رصيد المورد بيتحسب تلقائيًا من فواتيره ومدفوعاته ومرتجعاته، مش بيتكتب بإيدك.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="sm:col-span-2">{field("اسم المورد", "name", { maxLength: 255, autoFocus: true })}</div>
          {field("التخصص / الشركة", "company", { maxLength: 255 })}
          {field("المسؤول", "agent", { maxLength: 255 })}
          {field("الهاتف", "phone", { maxLength: 31, inputMode: "tel", className: "num" })}
          {field("المدينة", "city", { maxLength: 80 })}
          {supplier && (
            <div className="sm:col-span-2">
              <Label className="mb-1.5 block text-xs text-muted-foreground">الحالة</Label>
              <div className="flex gap-2">
                {[["active", "نشط"], ["inactive", "متوقف"]].map(([value, label]) => (
                  <Button key={value} type="button" variant={form.status === value ? "default" : "outline"} onClick={() => set("status", value)}>
                    {label}
                  </Button>
                ))}
              </div>
              {form.status === "inactive" && <p className="mt-1.5 text-xs text-muted-foreground">المورد المتوقف ما ينفعش تسجّل له فواتير جديدة، وتاريخه بيفضل محفوظ.</p>}
            </div>
          )}
        </div>
        {shown && (
          <p role="alert" className="rounded-md border border-[#F1C7C3] bg-[#FDECEA] px-3 py-2 text-xs font-semibold text-[#B3261E]">
            {shown}
          </p>
        )}
        <DialogFooter className="gap-2">
          <Button variant="outline" disabled={pending} onClick={() => onOpenChange(false)}>رجوع</Button>
          <Button className="font-bold" disabled={pending} onClick={submit}>
            {pending ? "جارٍ الحفظ..." : supplier ? "حفظ التعديلات" : "إضافة المورد"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
