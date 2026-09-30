import React, { useState, useEffect } from "react";
import { X, Upload, Loader2, ImageIcon } from "lucide-react";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";

const EMPTY = { name: "", sku: "", price: "", stock: "", category: "", image_url: "" };

function deriveStatus(stock) {
  const n = Number(stock) || 0;
  if (n <= 0) return "out";
  if (n < 20) return "low";
  return "in-stock";
}

export default function ProductDialog({ open, product, onClose, onSaved }) {
  const t = useT();
  const [form, setForm] = useState(EMPTY);
  const [uploading, setUploading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (open) {
      setForm(product ? { ...EMPTY, ...product, price: product.price ?? "", stock: product.stock ?? "" } : EMPTY);
      setErr("");
    }
  }, [open, product]);

  if (!open) return null;

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  async function onImage(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      // رفع الصور غير متاح في الـbackend حاليًا — الحفظ بدون صورة
      const file_url = null;
    } catch {
      setErr(t("products.image.error"));
    } finally {
      setUploading(false);
    }
  }

  async function save() {
    if (!form.name || form.price === "" || form.stock === "") {
      setErr(t("products.required"));
      return;
    }
    setSaving(true);
    setErr("");
    const payload = {
      name: form.name,
      sku: form.sku || "",
      price: Number(form.price) || 0,
      stock: Number(form.stock) || 0,
      status: deriveStatus(form.stock),
      trend: Number(form.trend) || 0,
      category: form.category || "",
      image_url: form.image_url || "",
    };
    try {
      if (product?.id) {
        await api(`/products/${product.id}`, { method: 'PATCH', body: payload });
      } else {
        await api('/products', { method: 'POST', body: payload });
      }
      onSaved();
      onClose();
    } catch (e) {
      setErr(t("products.save.error"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4 animate-fade-in" onClick={onClose}>
      <div className="w-full max-w-lg rounded-2xl bg-card border border-border shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          <h3 className="font-display text-[16px] font-semibold">{product ? t("products.edit") : t("products.new")}</h3>
          <button onClick={onClose} className="h-8 w-8 grid place-items-center rounded-lg hover:bg-surface text-muted-foreground"><X className="h-4 w-4" /></button>
        </div>
        <div className="p-5 space-y-4">
          {/* Image */}
          <div className="flex items-center gap-4">
            <div className="h-20 w-20 rounded-xl border border-border bg-surface grid place-items-center overflow-hidden shrink-0">
              {form.image_url ? (
                <img src={form.image_url} alt="" className="h-full w-full object-cover" />
              ) : (
                <ImageIcon className="h-6 w-6 text-muted-foreground/40" />
              )}
            </div>
            <div>
              <label className="inline-flex items-center gap-1.5 h-9 px-3 rounded-lg border border-border text-[13px] font-medium hover:bg-surface cursor-pointer">
                {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                {t("products.image")}
                <input type="file" accept="image/*" className="hidden" onChange={onImage} disabled={uploading} />
              </label>
              <p className="text-[11.5px] text-muted-foreground mt-1.5 max-w-[220px]">{t("products.image.hint")}</p>
            </div>
          </div>

          <Field label={t("products.name")}>
            <input value={form.name} onChange={(e) => set("name", e.target.value)} className={inputCls} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("products.sku")}>
              <input value={form.sku} onChange={(e) => set("sku", e.target.value)} className={inputCls} />
            </Field>
            <Field label={t("products.category")}>
              <input value={form.category} onChange={(e) => set("category", e.target.value)} className={inputCls} />
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("products.price")}>
              <input type="number" value={form.price} onChange={(e) => set("price", e.target.value)} className={inputCls} />
            </Field>
            <Field label={t("products.stock")}>
              <input type="number" value={form.stock} onChange={(e) => set("stock", e.target.value)} className={inputCls} />
            </Field>
          </div>

          {err && <p className="text-[12.5px] text-destructive">{err}</p>}
        </div>
        <div className="flex justify-end gap-2 px-5 py-4 border-t border-border">
          <button onClick={onClose} className="h-9 px-4 rounded-lg border border-border text-[13px] font-medium hover:bg-surface">{t("products.cancel")}</button>
          <button onClick={save} disabled={saving} className="h-9 px-4 rounded-lg bg-primary text-primary-foreground text-[13px] font-medium flex items-center gap-1.5 disabled:opacity-60">
            {saving && <Loader2 className="h-4 w-4 animate-spin" />}
            {t("products.save")}
          </button>
        </div>
      </div>
    </div>
  );
}

const inputCls = "w-full h-9 px-3 rounded-lg bg-surface border border-border text-[13px] focus:outline-none focus:ring-2 focus:ring-ring/30";

function Field({ label, children }) {
  return (
    <label className="block">
      <span className="text-[12px] font-medium text-muted-foreground mb-1.5 block">{label}</span>
      {children}
    </label>
  );
}