import React, { useEffect, useState } from "react";
import { X, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";

const EMPTY = { title: "", slug: "", description: "", sku: "", price: "", variant_id: null };

function slugFromTitle(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[^\w\u0600-\u06FF]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export default function ProductDialog({ open, product, onClose, onSaved }) {
  const t = useT();
  const [form, setForm] = useState(EMPTY);
  const [slugTouched, setSlugTouched] = useState(false);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!open) return;
    const variant = product?.variants?.find((item) => item.is_active) || product?.variants?.[0];
    setForm(product ? {
      title: product.title || product.name || "",
      slug: product.slug || "",
      description: product.description || "",
      sku: variant?.sku || product.sku || "",
      price: variant?.price ?? product.price ?? "",
      variant_id: variant?.id || product.variant_id || null,
    } : EMPTY);
    setSlugTouched(Boolean(product?.slug));
    setErr("");
  }, [open, product]);

  if (!open) return null;

  function setField(key, value) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function save(event) {
    event?.preventDefault();
    const title = form.title.trim();
    const slug = (form.slug || slugFromTitle(title)).trim();
    const price = form.price.trim();
    const numericPrice = Number(price);
    if (!title || !slug || !Number.isFinite(numericPrice) || numericPrice <= 0) {
      setErr(t("products.required"));
      return;
    }
    setSaving(true);
    setErr("");
    try {
      if (product?.id) {
        await api(`/products/${product.id}`, {
          method: "PATCH",
          body: { title, slug, description: form.description.trim() || null },
        });
        if (form.variant_id) {
          await api(`/variants/${form.variant_id}`, {
            method: "PATCH",
          body: { sku: form.sku.trim() || null, price },
          });
        } else {
          await api(`/products/${product.id}/variants`, {
            method: "POST",
            body: { sku: form.sku.trim() || null, title, price, option_values: {} },
          });
        }
      } else {
        await api("/products", {
          method: "POST",
          body: {
            title,
            slug,
            description: form.description.trim() || null,
            sku: form.sku.trim() || null,
            price,
          },
        });
      }
      await onSaved?.();
      onClose();
    } catch (e) {
      setErr(e?.message || t("products.save.error"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4 animate-fade-in" onClick={onClose}>
      <form
        onSubmit={save}
        className="w-full max-w-lg rounded-2xl bg-card border border-border shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          <h3 className="font-display text-[16px] font-semibold">{product ? t("products.edit") : t("products.new")}</h3>
          <button type="button" aria-label={t("common.close", "Close")} onClick={onClose} className="h-8 w-8 grid place-items-center rounded-lg hover:bg-surface text-muted-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="p-5 space-y-4">
          <Field label={t("products.name")}>
            <input required maxLength={255} value={form.title} onChange={(event) => {
              const title = event.target.value;
              setForm((current) => ({ ...current, title, ...(!slugTouched ? { slug: slugFromTitle(title) } : {}) }));
            }} className={inputCls} />
          </Field>
          <Field label={t("products.slug", "Slug")}>
            <input required maxLength={255} value={form.slug} onChange={(event) => {
              setSlugTouched(true);
              setField("slug", event.target.value);
            }} className={inputCls} dir="ltr" />
          </Field>
          <Field label={t("products.description", "Description")}>
            <textarea maxLength={4000} value={form.description} onChange={(event) => setField("description", event.target.value)} className={`${inputCls} h-20 resize-y py-2`} />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("products.sku")}>
              <input maxLength={63} value={form.sku} onChange={(event) => setField("sku", event.target.value)} className={inputCls} />
            </Field>
            <Field label={t("products.price")}>
              <input required type="number" min="0.01" step="0.01" value={form.price} onChange={(event) => setField("price", event.target.value)} className={inputCls} />
            </Field>
          </div>
          <p className="text-[11.5px] text-muted-foreground">{t("products.stockManagedInInventory", "Stock levels are managed from Inventory.")}</p>
          {err && <p role="alert" className="text-[12.5px] text-destructive">{err}</p>}
        </div>
        <div className="flex justify-end gap-2 px-5 py-4 border-t border-border">
          <button type="button" onClick={onClose} className="h-9 px-4 rounded-lg border border-border text-[13px] font-medium hover:bg-surface">{t("products.cancel")}</button>
          <button type="submit" disabled={saving} className="h-9 px-4 rounded-lg bg-primary text-primary-foreground text-[13px] font-medium flex items-center gap-1.5 disabled:opacity-60">
            {saving && <Loader2 className="h-4 w-4 animate-spin" />}
            {t("products.save")}
          </button>
        </div>
      </form>
    </div>
  );
}

const inputCls = "w-full rounded-lg bg-surface border border-border px-3 py-2 text-[13px] focus:outline-hidden focus:ring-2 focus:ring-ring/30";

function Field({ label, children }) {
  return (
    <label className="block">
      <span className="text-[12px] font-medium text-muted-foreground mb-1.5 block">{label}</span>
      {children}
    </label>
  );
}
