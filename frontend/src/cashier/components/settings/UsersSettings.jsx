import { useState } from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/cashier/components/ui/button";
import SectionCard from "@/cashier/components/ui-kit/SectionCard";
import ConfirmDialog from "@/cashier/components/ui-kit/ConfirmDialog";
import UserFormDialog, { USER_ROLES } from "@/cashier/components/settings/UserFormDialog";
import { employees } from "@/cashier/lib/mockData";
import { fmtDateTime } from "@/cashier/lib/format";

// المستخدمون: المالك والكاشير، بأدوارهم وحالتهم.
const initialUsers = employees.map((e) => ({
  id: e.id,
  name: e.name,
  username: e.username,
  role: e.role === "مدير" ? "owner" : "cashier",
  phone: "",
  status: e.status,
  lastActive: e.lastActive,
}));

export default function UsersSettings() {
  const [users, setUsers] = useState(initialUsers);
  const [editing, setEditing] = useState(null);
  const [removing, setRemoving] = useState(null);

  function saveUser(user) {
    const exists = users.some((u) => u.id === user.id);
    setUsers((prev) => {
      // المالك واحد فقط: أي مالك جديد يُنزّل المالك الحالي إلى كاشير.
      const others = prev.map((u) => (user.role === "owner" && u.id !== user.id ? { ...u, role: "cashier" } : u));
      return exists ? others.map((u) => (u.id === user.id ? user : u)) : [user, ...others];
    });
    toast.success(`تم ${exists ? "تحديث" : "إضافة"} المستخدم ${user.name}`);
  }

  return (
    <SectionCard
      title="المستخدمون والصلاحيات"
      description="حسابات المالك والكاشير المسموح لها بالدخول للنظام"
      action={
        <Button
          className="gap-2"
          onClick={() => setEditing({ name: "", username: "", role: "cashier", phone: "", status: "active" })}
        >
          <Plus className="h-4 w-4" />
          مستخدم جديد
        </Button>
      }
    >
      <div className="overflow-x-auto scroll-slim rounded-xl border border-border">
        <table className="w-full min-w-[680px] text-sm">
          <thead>
            <tr className="bg-muted/50 text-xs text-muted-foreground">
              <th className="px-3 py-2 text-start font-semibold">الاسم</th>
              <th className="px-3 py-2 text-start font-semibold">اسم الدخول</th>
              <th className="px-3 py-2 text-center font-semibold">الدور</th>
              <th className="px-3 py-2 text-start font-semibold">الجوال</th>
              <th className="px-3 py-2 text-start font-semibold">آخر دخول</th>
              <th className="px-3 py-2 text-center font-semibold">الحالة</th>
              <th className="px-3 py-2 text-center font-semibold">الإجراء</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {users.map((u) => (
              <tr key={u.id} className="transition-colors hover:bg-accent/40">
                <td className="px-3 py-2 font-medium">{u.name}</td>
                <td className="num px-3 py-2 text-xs text-muted-foreground">{u.username}</td>
                <td className="px-3 py-2 text-center">
                  <span
                    className={
                      u.role === "owner"
                        ? "rounded-full bg-orange-50 px-2 py-0.5 text-[11px] font-semibold text-orange-700 ring-1 ring-orange-200"
                        : "rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-600 ring-1 ring-slate-200"
                    }
                  >
                    {USER_ROLES[u.role]}
                  </span>
                </td>
                <td className="num px-3 py-2 text-xs">{u.phone || "—"}</td>
                <td className="num px-3 py-2 text-xs text-muted-foreground">{u.lastActive ? fmtDateTime(u.lastActive) : "—"}</td>
                <td className="px-3 py-2 text-center">
                  <span
                    className={
                      u.status === "active"
                        ? "rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-emerald-700 ring-1 ring-emerald-200"
                        : "rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-500 ring-1 ring-slate-200"
                    }
                  >
                    {u.status === "active" ? "نشط" : "موقوف"}
                  </span>
                </td>
                <td className="px-3 py-2">
                  <div className="flex items-center justify-center gap-1">
                    <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => setEditing(u)} aria-label={`تعديل ${u.name}`}>
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 text-rose-600 hover:bg-rose-50 hover:text-rose-700"
                      disabled={u.role === "owner"}
                      onClick={() => setRemoving(u)}
                      aria-label={`حذف ${u.name}`}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="num mt-3 text-[11px] text-muted-foreground">{users.length} مستخدمًا • مالك واحد وكاشير للبيع والتحصيل</p>

      <UserFormDialog open={!!editing} onOpenChange={(open) => !open && setEditing(null)} user={editing} onSave={saveUser} />
      <ConfirmDialog
        open={!!removing}
        onOpenChange={(open) => !open && setRemoving(null)}
        title={`حذف ${removing?.name ?? ""}؟`}
        description="سيتم إلغاء وصول المستخدم للنظام، ويمكن إضافته مرة أخرى لاحقًا."
        confirmLabel="حذف"
        onConfirm={() => {
          setUsers((prev) => prev.filter((u) => u.id !== removing.id));
          toast.info("تم حذف المستخدم");
          setRemoving(null);
        }}
      />
    </SectionCard>
  );
}