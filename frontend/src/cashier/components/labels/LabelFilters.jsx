import { Button } from "@/cashier/components/ui/button";
import { Input } from "@/cashier/components/ui/input";
import { Label } from "@/cashier/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/cashier/components/ui/select";
import FilterPanel from "@/cashier/components/ui-kit/FilterPanel";
import { BTN, FIELD, FIELD_HINT, FIELD_LABEL, FIELD_SELECT, FILTER_PANEL, FILTER_PANEL_CONTENT, FILTER_PANEL_HEADER } from "@/cashier/components/ui-kit/ledgerStyles";
import { categories } from "@/cashier/lib/mockData";
import { purchaseOrders } from "@/cashier/lib/purchasesData";
import { fmtDate } from "@/cashier/lib/format";

// فلاتر شاشة الملصقات: بحث، تصنيف، سحب كميات فاتورة توريد، وتعبئة سريعة.
export default function LabelFilters({ term, onTerm, category, onCategory, poNumber, onPo, onQuickFill, onReset }) {
  const activeCount = [category, poNumber].filter(Boolean).length + (term ? 1 : 0);

  return (
    <FilterPanel
      className={FILTER_PANEL}
      headerClassName={FILTER_PANEL_HEADER}
      contentClassName={FILTER_PANEL_CONTENT}
      activeCount={activeCount}
      onReset={onReset}
    >
      <div className="grid gap-3 sm:grid-cols-[1.2fr_1fr_1.3fr_1.5fr]">
        <div>
          <Label className={FIELD_LABEL}>بحث بالاسم أو الكود أو الباركود</Label>
          <Input
            value={term}
            onChange={(e) => onTerm(e.target.value)}
            placeholder="تيشيرت، SKU-0001، 200000001..."
            className={FIELD}
          />
        </div>

        <div>
          <Label className={FIELD_LABEL}>التصنيف</Label>
          <Select value={category || "all"} onValueChange={onCategory}>
            <SelectTrigger className={FIELD_SELECT}>
              <SelectValue placeholder="كل التصنيفات" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">كل التصنيفات</SelectItem>
              {categories.map((c) => (
                <SelectItem key={c} value={c}>
                  {c}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div>
          <Label className={FIELD_LABEL}>سحب الكميات من فاتورة توريد</Label>
          <Select value={poNumber || "none"} onValueChange={onPo}>
            <SelectTrigger className={FIELD_SELECT}>
              <SelectValue placeholder="اختر فاتورة التوريد" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">إدخال يدوي</SelectItem>
              {purchaseOrders.map((o) => (
                <SelectItem key={o.id} value={o.number}>
                  {o.number} • {o.supplierName} • {fmtDate(o.date)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <span className={FIELD_HINT}>الكميات المسجلة في الفاتورة لكل لون ومقاس</span>
        </div>

        <div>
          <Label className={FIELD_LABEL}>تعبئة سريعة للنتائج المعروضة</Label>
          <div className="flex flex-wrap gap-2">
            <Button className={BTN} onClick={() => onQuickFill(3)}>
              ٣ لكل متغير
            </Button>
            <Button className={BTN} onClick={() => onQuickFill(5)}>
              ٥ لكل متغير
            </Button>
            <Button className={BTN} onClick={() => onQuickFill(0)}>
              تفريغ الكميات
            </Button>
          </div>
        </div>
      </div>
    </FilterPanel>
  );
}