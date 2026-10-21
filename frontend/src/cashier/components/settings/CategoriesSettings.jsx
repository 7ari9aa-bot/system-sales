import { useState } from "react";
import { Plus } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/cashier/components/ui/button";
import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";
import SectionCard from "@/cashier/components/ui-kit/SectionCard";
import { useCategories, useCreateCategory } from "@/cashier/api/useCatalogWrite";

// فئات المنتجات الحقيقية للمحل. الإضافة تُحفظ فورًا في النظام؛ لا يوجد حفظ جماعي.
// (الألوان والمقاسات خيارات ثابتة في نموذج المنتج، ولا تُخزَّن كإعدادات للمحل بعد.)
export default function CategoriesSettings() {
  const { data: categories = [], isPending, isError, refetch } = useCategories();
  const create = useCreateCategory();
  const [name, setName] = useState("");

  async function add() {
    const value = name.trim();
    if (!value) return;
    if (categories.some((c) => c.name === value)) {
      toast.error("هذه الفئة موجودة بالفعل");
      return;
    }
    try {
      await create.mutateAsync(value);
      setName("");
      toast.success("تمت إضافة الفئة");
    } catch (e) {
      toast.error(e?.message ?? "تعذّرت إضافة الفئة");
    }
  }

  return (
    <SectionCard title="فئات المنتجات" description="الفئات التي تظهر عند إضافة منتج أو تعديله. تُحفظ الإضافة فورًا.">
      {isError ? (
        <div role="alert" className="flex items-center justify-between rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
          <span>تعذّر تحميل الفئات.</span>
          <Button variant="outline" onClick={() => refetch()}>إعادة المحاولة</Button>
        </div>
      ) : (
        <div>
          <Label className="mb-2 block text-xs font-semibold text-muted-foreground">الفئات الحالية</Label>
          {isPending ? (
            <p className="text-sm text-muted-foreground">جاري التحميل…</p>
          ) : categories.length === 0 ? (
            <p className="text-sm text-muted-foreground">لا توجد فئات بعد. أضف أول فئة.</p>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {categories.map((c) => (
                <span key={c.id} className="inline-flex items-center rounded-full border border-border bg-muted/50 px-2.5 py-1 text-xs">
                  {c.name}
                </span>
              ))}
            </div>
          )}
          <div className="mt-3 flex max-w-sm gap-2">
            <Input value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && add()} placeholder="فئة جديدة" className="h-9" />
            <Button variant="outline" size="icon" className="h-9 w-9 shrink-0" aria-label="إضافة فئة" disabled={create.isPending} onClick={add}>
              <Plus className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}
    </SectionCard>
  );
}
