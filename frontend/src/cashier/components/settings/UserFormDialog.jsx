import { useEffect, useState } from "react";
import { Button } from "@/cashier/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/cashier/components/ui/dialog";
import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/cashier/components/ui/select";
import { Switch } from "@/cashier/components/ui/switch";

export const USER_ROLES = { owner: "مالك", cashier: "كاشير" };

// إضافة أو تعديل مستخدم: الاسم، اسم الدخول، الدور، الجوال، والحالة.
export default function UserFormDialog({ open, onOpenChange, user, onSave }) {
  const [form, setForm] = useState(user ?? {});

  useEffect(() => {
    if (user) setForm(user);
  }, [user]);

  if (!user) return null;

  const valid = Boolean(form.name?.trim() && form.username?.trim());

  function set(key, value) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent dir="rtl" className="max-w-md">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">{form.id ? "تعديل مستخدم" : "مستخدم جديد"}</DialogTitle>
          <DialogDescription>حدد دور المستخدم: المالك يرى كل شيء، والكاشير يعمل على البيع والمصروفات.</DialogDescription>
        </DialogHeader>

        <div className="grid gap-3 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <Label className="mb-1.5 block text-xs text-muted-foreground">الاسم</Label>
            <Input value={form.name ?? ""} onChange={(e) => set("name", e.target.value)} placeholder="أحمد سمير" />
          </div>
          <div>
            <Label className="mb-1.5 block text-xs text-muted-foreground">اسم الدخول</Label>
            <Input value={form.username ?? ""} onChange={(e) => set("username", e.target.value)} placeholder="ahmed.s" className="num" dir="ltr" />
          </div>
          <div>
            <Label className="mb-1.5 block text-xs text-muted-foreground">الدور</Label>
            <Select value={form.role ?? "cashier"} onValueChange={(v) => set("role", v)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {Object.entries(USER_ROLES).map(([key, label]) => (
                  <SelectItem key={key} value={key}>
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="sm:col-span-2">
            <Label className="mb-1.5 block text-xs text-muted-foreground">الجوال</Label>
            <Input value={form.phone ?? ""} onChange={(e) => set("phone", e.target.value)} placeholder="01xxxxxxxxx" className="num" dir="ltr" />
          </div>
          <div className="sm:col-span-2 flex items-center justify-between gap-3 rounded-lg border border-border px-3 py-2.5">
            <div>
              <p className="text-sm font-medium">الحساب نشط</p>
              <p className="text-[11px] text-muted-foreground">المستخدم غير النشط لا يستطيع تسجيل الدخول</p>
            </div>
            <Switch checked={(form.status ?? "active") === "active"} onCheckedChange={(v) => set("status", v ? "active" : "inactive")} />
          </div>
        </div>

        <div className="flex gap-2">
          <Button variant="outline" className="flex-1" onClick={() => onOpenChange(false)}>
            إلغاء
          </Button>
          <Button
            className="flex-1 font-bold"
            disabled={!valid}
            onClick={() => {
              onSave({ ...form, id: form.id ?? `user-${Date.now()}`, status: form.status || "active", phone: form.phone || "" });
              onOpenChange(false);
            }}
          >
            حفظ
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}