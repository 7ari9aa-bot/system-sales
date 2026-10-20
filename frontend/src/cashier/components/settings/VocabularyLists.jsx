import { useState } from "react";
import { Plus, Save, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/cashier/components/ui/button";
import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/cashier/components/ui/select";
import SectionCard from "@/cashier/components/ui-kit/SectionCard";
import { COLORS, SIZE_SETS, categories } from "@/cashier/lib/mockData";

const SIZE_SET_LABELS = {
  clothing: "ملابس رجالي وحريمي",
  kids: "ملابس أطفال",
  shoes: "أحذية",
  one: "مقاس واحد",
};

function Chip({ children, onRemove }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted/50 px-2.5 py-1 text-xs">
      {children}
      <button type="button" onClick={onRemove} className="text-muted-foreground transition-colors hover:text-rose-600" aria-label="حذف">
        <X className="h-3 w-3" />
      </button>
    </span>
  );
}

// التصنيفات والألوان والمقاسات المستخدمة في كتالوج المنتجات.
export default function VocabularyLists() {
  const [cats, setCats] = useState(categories);
  const [colors, setColors] = useState(COLORS);
  const [sizes, setSizes] = useState(SIZE_SETS);
  const [newCat, setNewCat] = useState("");
  const [newColor, setNewColor] = useState("");
  const [newHex, setNewHex] = useState("#B91C1C");
  const [sizeSet, setSizeSet] = useState("clothing");
  const [newSize, setNewSize] = useState("");

  return (
    <SectionCard
      title="التصنيفات والألوان والمقاسات"
      description="القوائم التي تظهر عند إضافة منتج جديد — عدّلها لتطابق تشكيلة محلك"
      action={
        <Button className="gap-2" onClick={() => toast.success("تم حفظ التصنيفات والألوان والمقاسات")}>
          <Save className="h-4 w-4" />
          حفظ
        </Button>
      }
    >
      <div className="grid gap-3 lg:grid-cols-3">
        <div>
          <Label className="mb-2 block text-xs font-semibold text-muted-foreground">التصنيفات</Label>
          <div className="flex flex-wrap gap-1.5">
            {cats.map((c) => (
              <Chip key={c} onRemove={() => setCats((prev) => prev.filter((x) => x !== c))}>
                {c}
              </Chip>
            ))}
          </div>
          <div className="mt-2 flex gap-2">
            <Input value={newCat} onChange={(e) => setNewCat(e.target.value)} placeholder="تصنيف جديد" className="h-9" />
            <Button
              variant="outline"
              size="icon"
              className="h-9 w-9 shrink-0"
              aria-label="إضافة تصنيف"
              onClick={() => {
                const value = newCat.trim();
                if (!value) return;
                setCats((prev) => [...prev, value]);
                setNewCat("");
              }}
            >
              <Plus className="h-4 w-4" />
            </Button>
          </div>
        </div>

        <div>
          <Label className="mb-2 block text-xs font-semibold text-muted-foreground">الألوان</Label>
          <div className="flex flex-wrap gap-1.5">
            {colors.map((c) => (
              <Chip key={c.name} onRemove={() => setColors((prev) => prev.filter((x) => x.name !== c.name))}>
                <span className="h-3 w-3 rounded-full ring-1 ring-black/10" style={{ backgroundColor: c.hex }} aria-hidden="true" />
                {c.name}
              </Chip>
            ))}
          </div>
          <div className="mt-2 flex gap-2">
            <Input value={newColor} onChange={(e) => setNewColor(e.target.value)} placeholder="لون جديد" className="h-9" />
            <input
              type="color"
              value={newHex}
              onChange={(e) => setNewHex(e.target.value)}
              className="h-9 w-9 shrink-0 cursor-pointer rounded-md border border-input bg-transparent p-0.5"
              aria-label="درجة اللون"
            />
            <Button
              variant="outline"
              size="icon"
              className="h-9 w-9 shrink-0"
              aria-label="إضافة لون"
              onClick={() => {
                const value = newColor.trim();
                if (!value) return;
                setColors((prev) => [...prev, { name: value, hex: newHex }]);
                setNewColor("");
              }}
            >
              <Plus className="h-4 w-4" />
            </Button>
          </div>
        </div>

        <div>
          <Label className="mb-2 block text-xs font-semibold text-muted-foreground">المقاسات</Label>
          <Select value={sizeSet} onValueChange={setSizeSet}>
            <SelectTrigger className="h-9">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(SIZE_SET_LABELS).map(([key, label]) => (
                <SelectItem key={key} value={key}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {sizes[sizeSet].map((s) => (
              <Chip
                key={s}
                onRemove={() => setSizes((prev) => ({ ...prev, [sizeSet]: prev[sizeSet].filter((x) => x !== s) }))}
              >
                {s}
              </Chip>
            ))}
          </div>
          <div className="mt-2 flex gap-2">
            <Input value={newSize} onChange={(e) => setNewSize(e.target.value)} placeholder="مقاس جديد" className="h-9" />
            <Button
              variant="outline"
              size="icon"
              className="h-9 w-9 shrink-0"
              aria-label="إضافة مقاس"
              onClick={() => {
                const value = newSize.trim();
                if (!value) return;
                setSizes((prev) => ({ ...prev, [sizeSet]: [...prev[sizeSet], value] }));
                setNewSize("");
              }}
            >
              <Plus className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </div>
    </SectionCard>
  );
}