import { useState } from "react";
import { Input } from "@/cashier/components/ui/input";
import { Button } from "@/cashier/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/cashier/components/ui/select";
import { INPUT, SELECT_TRIGGER } from "@/cashier/components/products/formStyles";

const NONE = "__none__";

/**
 * A pick-one list that comes from the backend (categories, brands) with an inline "add new".
 * A brand-new shop has no categories or brands yet, so the list can be empty: the shop adds its own.
 * `value` is the record id ("" = none); `onCreate(name)` resolves to the new record.
 */
export default function NamedPicker({ items, value, onChange, onCreate, loading, noneLabel, addLabel, placeholder }) {
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit() {
    const clean = name.trim();
    if (!clean) return;
    if (items.some((i) => i.name.trim().toLowerCase() === clean.toLowerCase())) {
      setError("هذا الاسم موجود بالفعل في القائمة");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const made = await onCreate(clean);
      onChange(made?.id ?? "");
      setName("");
      setAdding(false);
    } catch (e) {
      setError(e?.message ?? "تعذّرت الإضافة");
    } finally {
      setBusy(false);
    }
  }

  if (adding) {
    return (
      <div className="flex flex-col gap-1.5">
        <div className="flex gap-2">
          <Input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder={placeholder} className={INPUT}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); submit(); } }} />
          <Button type="button" onClick={submit} disabled={busy || !name.trim()}>{busy ? "…" : "حفظ"}</Button>
          <Button type="button" variant="outline" onClick={() => { setAdding(false); setError(""); }}>إلغاء</Button>
        </div>
        {error ? <p role="alert" className="text-xs font-semibold text-rose-600">{error}</p> : null}
      </div>
    );
  }

  return (
    <div className="flex gap-2">
      <Select value={value || NONE} onValueChange={(v) => onChange(v === NONE ? "" : v)} disabled={loading}>
        <SelectTrigger className={SELECT_TRIGGER}>
          <SelectValue placeholder={loading ? "جارٍ التحميل…" : noneLabel} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={NONE}>{noneLabel}</SelectItem>
          {items.map((i) => (
            <SelectItem key={i.id} value={i.id}>{i.name}</SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button type="button" variant="outline" onClick={() => setAdding(true)} className="shrink-0">{addLabel}</Button>
    </div>
  );
}
