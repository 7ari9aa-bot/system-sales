import React from "react";
import { ImagePlus } from "lucide-react";
import { PageHeader } from "@/components/dashboard/ui";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";

const FIELD = "h-10 w-full rounded-lg border border-input bg-card px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring";

function Field({ label, children, className }) {
  return (
    <label className={cn("block", className)}>
      <span className="mb-1.5 block text-xs font-semibold text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}

/** شاشة إضافة منتج — هيكل مطابق للتصميم الجديد. النماذج لسه متربطش بالـ
 *  catalog endpoints، فالزر مقفول عمدًا: أي حفظ هنا لازم يمشي عبر /api/v1. */
export default function AddProduct() {
  const t = useT();
  return (
    <div className="space-y-4">
      <PageHeader title={t("addProduct.title")} subtitle={t("addProduct.hint")} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_260px]">
        <section className="rounded-xl border border-border bg-card p-4 shadow-card">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label={t("addProduct.modelName")} className="sm:col-span-2">
              <input className={FIELD} placeholder={t("addProduct.modelNamePlaceholder")} />
            </Field>
            <Field label={t("addProduct.type")}>
              <select className={FIELD}><option>{t("addProduct.choose")}</option></select>
            </Field>
            <Field label={t("addProduct.category")}>
              <select className={FIELD}><option>{t("addProduct.choose")}</option></select>
            </Field>
            <Field label={t("addProduct.season")}>
              <select className={FIELD}><option>{t("addProduct.choose")}</option></select>
            </Field>
            <Field label={t("addProduct.sizeSystem")}>
              <select className={FIELD}><option>{t("addProduct.choose")}</option></select>
            </Field>
            <Field label={t("addProduct.colors")} className="sm:col-span-2">
              <input className={FIELD} placeholder={t("addProduct.colorsPlaceholder")} />
            </Field>
            <Field label={t("addProduct.sizes")} className="sm:col-span-2">
              <input className={FIELD} placeholder={t("addProduct.sizesPlaceholder")} />
            </Field>
            <Field label={t("addProduct.purchasePrice")}>
              <input dir="ltr" type="number" className={cn(FIELD, "tabular-nums")} placeholder={t("addProduct.pricePlaceholder")} />
            </Field>
            <Field label={t("addProduct.salePrice")}>
              <input dir="ltr" type="number" className={cn(FIELD, "tabular-nums")} placeholder={t("addProduct.pricePlaceholder")} />
            </Field>
            <Field label={t("addProduct.packSize")}>
              <input dir="ltr" type="number" className={cn(FIELD, "tabular-nums")} placeholder={t("addProduct.qtyPlaceholder")} />
            </Field>
            <Field label={t("addProduct.openingStock")}>
              <input dir="ltr" type="number" className={cn(FIELD, "tabular-nums")} placeholder={t("addProduct.qtyPlaceholder")} />
            </Field>
          </div>

          <div className="mt-4 flex items-center justify-end gap-2 border-t border-border pt-4">
            <span className="me-auto text-xs text-muted-foreground">{t("addProduct.notWired")}</span>
            <button type="button" disabled className="h-10 rounded-lg bg-primary px-5 text-sm font-semibold text-primary-foreground opacity-50">
              {t("addProduct.save")}
            </button>
          </div>
        </section>

        <section className="rounded-xl border border-border bg-card p-4 shadow-card">
          <span className="mb-1.5 block text-xs font-semibold text-muted-foreground">{t("addProduct.image")}</span>
          <div className="grid aspect-square place-items-center rounded-xl border border-dashed border-input text-muted-foreground">
            <div className="text-center">
              <ImagePlus className="mx-auto h-7 w-7" />
              <p className="mt-2 text-xs">{t("addProduct.imageHint")}</p>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
