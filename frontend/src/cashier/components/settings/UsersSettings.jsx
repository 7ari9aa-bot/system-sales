import { Button } from "@/cashier/components/ui/button";
import SectionCard from "@/cashier/components/ui-kit/SectionCard";
import { ROLE_LABEL, useTenantUsers } from "@/cashier/api/useTenantUsers";

const ROLE_STYLE = {
  owner: "bg-orange-50 text-orange-700 ring-orange-200",
  manager: "bg-sky-50 text-sky-700 ring-sky-200",
  staff: "bg-slate-100 text-slate-600 ring-slate-200",
};

// المستخدمون الحقيقيون للمحل (للقراءة فقط). الإضافة والتعديل وكلمات المرور تُدار من إعدادات Sales OS الرئيسية.
export default function UsersSettings() {
  const { data: users = [], isPending, isError, refetch } = useTenantUsers();

  return (
    <SectionCard title="المستخدمون والصلاحيات" description="حسابات محلك وأدوارها. تُدار الإضافة والتعديل من إعدادات حساب Sales OS.">
      {isError ? (
        <div role="alert" className="flex items-center justify-between rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
          <span>تعذّر تحميل المستخدمين.</span>
          <Button variant="outline" onClick={() => refetch()}>إعادة المحاولة</Button>
        </div>
      ) : (
        <>
          <div className="overflow-x-auto scroll-slim rounded-xl border border-border">
            <table className="w-full min-w-[480px] text-sm">
              <thead>
                <tr className="bg-muted/50 text-xs text-muted-foreground">
                  <th className="px-3 py-2 text-start font-semibold">الاسم</th>
                  <th className="px-3 py-2 text-start font-semibold">البريد</th>
                  <th className="px-3 py-2 text-center font-semibold">الدور</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {isPending ? (
                  <tr><td colSpan={3} className="px-3 py-6 text-center text-muted-foreground">جاري التحميل…</td></tr>
                ) : (
                  users.map((u) => (
                    <tr key={u.id} className="transition-colors hover:bg-accent/40">
                      <td className="px-3 py-2 font-medium">{u.name}</td>
                      <td className="num px-3 py-2 text-xs text-muted-foreground">{u.email}</td>
                      <td className="px-3 py-2 text-center">
                        <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ${ROLE_STYLE[u.role] ?? ROLE_STYLE.staff}`}>
                          {ROLE_LABEL[u.role] ?? u.role}
                        </span>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
          <p className="num mt-3 text-[11px] text-muted-foreground">{users.length} مستخدمًا</p>
        </>
      )}
    </SectionCard>
  );
}
