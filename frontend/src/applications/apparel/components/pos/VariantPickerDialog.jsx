import { useMemo, useState } from "react";
import { Search } from "lucide-react";
import { Button } from "@/applications/apparel/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/applications/apparel/components/ui/dialog";
import { Input } from "@/applications/apparel/components/ui/input";
import ColorSwatch from "@/applications/apparel/components/ui-kit/ColorSwatch";
import { colourLabel, defaultColour, modelsFromCatalog, sizesFor } from "@/applications/apparel/lib/variantPicker";
import { fmtMoney } from "@/applications/apparel/lib/format";
import { cn } from "@/applications/apparel/lib/utils";

/**
 * اختيار يدوي للصنف: موديل ← لون ← مقاس.
 *
 * A piece whose label is torn still has to be sold, so the till offers the same three choices the
 * rail does. Every rule (grouping, colour order, size order, sold-out) lives in
 * `lib/variantPicker.js`; this file only draws them.
 */
export default function VariantPickerDialog({ open, onOpenChange, catalog = [], onPick, pending = false }) {
  const [term, setTerm] = useState("");
  const [modelId, setModelId] = useState(null);
  const [colour, setColour] = useState("");

  const models = useMemo(() => modelsFromCatalog(catalog, term), [catalog, term]);
  const model = models.find((m) => m.id === modelId) ?? null;
  const activeColour = model ? (model.colours.includes(colour) ? colour : defaultColour(model)) : "";
  const sizes = model ? sizesFor(model, activeColour) : [];

  const reset = () => {
    setTerm("");
    setModelId(null);
    setColour("");
  };

  const close = () => {
    reset();
    onOpenChange(false);
  };

  const pick = (entry) => {
    if (!entry || entry.soldOut || pending) return;
    onPick(entry.variant);
    reset();
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? onOpenChange(true) : close())}>
      <DialogContent dir="rtl" className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="font-heading text-base">اختيار صنف من الكتالوج</DialogTitle>
          <DialogDescription>
            {model ? `${model.name} — اختار اللون والمقاس` : "ابحث بالموديل أو الكود، ثم اختار اللون والمقاس."}
          </DialogDescription>
        </DialogHeader>

        {!model ? (
          <div className="space-y-2">
            <div className="relative">
              <Search className="pointer-events-none absolute inset-y-0 end-3 my-auto h-4 w-4 text-muted-foreground" />
              <Input
                autoFocus
                value={term}
                onChange={(e) => setTerm(e.target.value)}
                placeholder="اسم الموديل أو الكود"
                aria-label="بحث في الكتالوج"
                className="pe-9"
              />
            </div>
            <ul className="max-h-72 overflow-auto rounded-xl border border-border">
              {models.length === 0 ? (
                <li className="px-3 py-6 text-center text-xs text-muted-foreground">مفيش موديل يطابق البحث</li>
              ) : (
                models.map((m) => (
                  <li key={m.id}>
                    <button
                      type="button"
                      onClick={() => {
                        setModelId(m.id);
                        setColour(defaultColour(m));
                      }}
                      className="flex w-full items-center justify-between gap-2 border-b border-border px-3 py-2 text-start text-[13px] last:border-b-0 hover:bg-accent"
                    >
                      <span className="min-w-0">
                        <span className="block truncate font-semibold">{m.name}</span>
                        <span className="block text-[11px] text-muted-foreground">
                          {m.colours.length} لون · {m.sizeCount} مقاس · من {fmtMoney(m.priceFrom)}
                        </span>
                      </span>
                      <span
                        className={cn(
                          "num shrink-0 rounded-full px-2 py-0.5 text-[10px] font-bold",
                          m.inStock > 0 ? "bg-emerald-100 text-emerald-800" : "bg-rose-100 text-rose-700",
                        )}
                      >
                        {m.inStock > 0 ? `${m.inStock} متاح` : "نفد"}
                      </span>
                    </button>
                  </li>
                ))
              )}
            </ul>
          </div>
        ) : (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-1.5">
              {model.colours.map((c) => (
                <button
                  key={c || "none"}
                  type="button"
                  onClick={() => setColour(c)}
                  aria-pressed={c === activeColour}
                  className={cn(
                    "flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[12px] font-semibold",
                    c === activeColour ? "border-primary bg-primary/10 text-primary" : "border-border hover:bg-accent",
                  )}
                >
                  <ColorSwatch color={c} showLabel={false} />
                  {colourLabel(c)}
                </button>
              ))}
            </div>

            <div className="grid grid-cols-3 gap-1.5 sm:grid-cols-4">
              {sizes.map((s) => (
                <button
                  key={s.variant.id}
                  type="button"
                  disabled={s.soldOut || pending}
                  onClick={() => pick(s)}
                  title={s.soldOut ? "نفد من المخزون" : `إضافة ${model.name} ${colourLabel(activeColour)} ${s.label}`}
                  className={cn(
                    "flex flex-col items-center rounded-xl border px-2 py-2 text-[13px] font-bold",
                    s.soldOut
                      ? "cursor-not-allowed border-dashed border-border text-muted-foreground/60"
                      : "border-border hover:border-primary hover:bg-primary/5",
                  )}
                >
                  <span className="num">{s.label}</span>
                  <span className={cn("num text-[10px] font-semibold", s.soldOut ? "text-rose-500" : "text-muted-foreground")}>
                    {s.soldOut ? "نفد" : `${s.stock} · ${fmtMoney(s.price)}`}
                  </span>
                </button>
              ))}
            </div>

            <Button type="button" variant="outline" className="w-full" onClick={() => setModelId(null)}>
              رجوع لقائمة الموديلات
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
