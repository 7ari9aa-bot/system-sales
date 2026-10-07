import React, { useEffect, useState } from "react";
import { X, Loader2, Package, ImagePlus } from "lucide-react";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";

const EMPTY = {
  title: "",
  description: "",
  sku: "",
  price: "",
  variant_id: null,
  image_url: "",
};

function slugFromTitle(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[^\w\u0600-\u06FF]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function httpImageUrl(value) {
  try {
    const url = new URL(String(value || "").trim());
    return url.protocol === "http:" || url.protocol === "https:" ? url.toString() : "";
  } catch {
    return "";
  }
}

export default function ProductDialog({ open, product, onClose, onSaved }) {
  const t = useT();
  const [form, setForm] = useState(EMPTY);
  const [savedImageUrl, setSavedImageUrl] = useState("");
  const [selectedImage, setSelectedImage] = useState(null);
  const [uploadedPreviewUrl, setUploadedPreviewUrl] = useState("");
  const [createdProductId, setCreatedProductId] = useState(null);
  const [createdVariantId, setCreatedVariantId] = useState(null);
  const [imagePreviewFailed, setImagePreviewFailed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!open) return;
    const variant = product?.variants?.find((item) => item.is_active) || product?.variants?.[0];
    const images = Array.isArray(product?.images) ? product.images : [];
    const currentImageUrl = images.length ? images[images.length - 1].url || "" : "";
    setForm(product ? {
      title: product.title || product.name || "",
      description: product.description || "",
      sku: variant?.sku || product.sku || "",
      price: variant?.price ?? product.price ?? "",
      variant_id: variant?.id || product.variant_id || null,
      image_url: currentImageUrl,
    } : EMPTY);
    setSavedImageUrl(currentImageUrl);
    setSelectedImage(null);
    setCreatedProductId(null);
    setCreatedVariantId(null);
    setImagePreviewFailed(false);
    setErr("");
  }, [open, product]);

  useEffect(() => {
    if (!selectedImage) {
      setUploadedPreviewUrl("");
      return undefined;
    }
    const previewUrl = URL.createObjectURL(selectedImage);
    setUploadedPreviewUrl(previewUrl);
    return () => URL.revokeObjectURL(previewUrl);
  }, [selectedImage]);

  if (!open) return null;

  function setField(key, value) {
    setForm((current) => ({ ...current, [key]: value }));
    if (key === "image_url") {
      setImagePreviewFailed(false);
      setSelectedImage(null);
    }
  }

  async function save(event) {
    event?.preventDefault();
    const title = form.title.trim();
    const price = form.price.trim();
    const numericPrice = Number(price);
    const imageUrl = form.image_url.trim();
    const imagePreviewUrl = httpImageUrl(imageUrl);
    const allowedImageTypes = new Set([
      "image/jpeg",
      "image/png",
      "image/webp",
      "image/gif",
      "image/bmp",
    ]);
    if (selectedImage && selectedImage.size > 10 * 1024 * 1024) {
      setErr(t("products.imageTooLarge"));
      return;
    }
    if (selectedImage && !allowedImageTypes.has(selectedImage.type)) {
      setErr(t("products.imageTypeNotAllowed"));
      return;
    }
    if (!title || !Number.isFinite(numericPrice) || numericPrice <= 0) {
      setErr(t("products.required"));
      return;
    }
    if (!selectedImage && imageUrl && !imagePreviewUrl) {
      setErr(t("products.imageUrlInvalid"));
      return;
    }

    setSaving(true);
    setErr("");
    try {
      let productId = product?.id || createdProductId;
      let variantId = form.variant_id || createdVariantId;
      if (productId) {
        await api("/products/" + productId, {
          method: "PATCH",
          body: { title, description: form.description.trim() || null },
        });
        if (variantId) {
          await api("/variants/" + variantId, {
            method: "PATCH",
            body: { sku: form.sku.trim() || null, title, price },
          });
        } else {
          const variant = await api("/products/" + productId + "/variants", {
            method: "POST",
            body: { sku: form.sku.trim() || null, title, price, option_values: {} },
          });
          variantId = variant?.id || null;
          setCreatedVariantId(variantId);
        }
      } else {
        const created = await api("/products", {
          method: "POST",
          body: {
            title,
            slug: slugFromTitle(title) || "product-" + Date.now(),
            description: form.description.trim() || null,
            sku: form.sku.trim() || null,
            price,
          },
        });
        if (!created?.id) throw new Error(t("products.save.error"));
        productId = created.id;
        setCreatedProductId(created.id);
        variantId = created.variant_id || null;
        setCreatedVariantId(variantId);
      }

      if (selectedImage) {
        await api("/products/" + productId + "/images/upload", {
          method: "POST",
          body: selectedImage,
          rawBody: true,
          contentType: selectedImage.type,
        });
      } else if (imageUrl && imageUrl !== savedImageUrl) {
        await api("/products/" + productId + "/images", {
          method: "POST",
          body: { url: imagePreviewUrl, alt: title },
        });
        setSavedImageUrl(imageUrl);
      }

      await onSaved?.();
      onClose();
    } catch (e) {
      setErr(e?.message || t("products.save.error"));
    } finally {
      setSaving(false);
    }
  }

  const imagePreviewUrl = uploadedPreviewUrl || httpImageUrl(form.image_url);

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4 animate-fade-in" onClick={() => !saving && onClose()}>
      <form
        onSubmit={save}
        role="dialog"
        aria-modal="true"
        aria-labelledby="product-dialog-title"
        className="flex max-h-[90vh] w-full max-w-lg flex-col rounded-2xl border border-border bg-card shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex shrink-0 items-center justify-between border-b border-border px-5 py-4">
          <h3 id="product-dialog-title" className="font-display text-[16px] font-semibold">{product ? t("products.edit") : t("products.new")}</h3>
          <button type="button" aria-label={t("common.close", "Close")} onClick={onClose} disabled={saving} className="grid h-8 w-8 place-items-center rounded-lg text-muted-foreground hover:bg-surface disabled:opacity-50">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="space-y-4 overflow-y-auto p-5">
          <Field label={t("products.name")}>
            <input required maxLength={255} value={form.title} onChange={(event) => setField("title", event.target.value)} className={inputCls} />
            <span className="mt-1.5 block text-[11.5px] text-muted-foreground">{t("products.slugHelp")}</span>
          </Field>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label={t("products.price")}>
              <input required type="number" min="0.01" step="0.01" value={form.price} onChange={(event) => setField("price", event.target.value)} className={inputCls} />
            </Field>
            <Field label={t("products.sku")}>
              <input maxLength={63} value={form.sku} onChange={(event) => setField("sku", event.target.value)} className={inputCls} />
            </Field>
          </div>
          <p className="-mt-2 text-[11.5px] text-muted-foreground">{t("products.skuHelp")}</p>
          <Field label={t("products.image")} asLabel={false}>
            <label htmlFor="product-image-file" className="flex min-h-11 cursor-pointer items-center justify-center gap-2 rounded-lg border border-dashed border-border bg-surface px-3 py-2 text-[13px] font-medium hover:border-primary hover:bg-primary/5">
              <ImagePlus className="h-4 w-4" />
              <span>{selectedImage ? selectedImage.name : t("products.chooseImage")}</span>
            </label>
            <input
              id="product-image-file"
              type="file"
              accept="image/jpeg,image/png,image/webp,image/gif,image/bmp"
              className="sr-only"
              onChange={(event) => {
                const nextImage = event.target.files?.[0] || null;
                event.currentTarget.value = "";
                setSelectedImage(nextImage);
                setImagePreviewFailed(false);
                setErr("");
              }}
            />
            <span className="mt-1.5 block text-[11.5px] text-muted-foreground">{t("products.imageHelp")}</span>
            <details className="mt-2">
              <summary className="cursor-pointer text-[11.5px] text-muted-foreground">{t("products.imageUrlAlternate")}</summary>
              <input type="url" maxLength={2048} value={form.image_url} onChange={(event) => setField("image_url", event.target.value)} className={inputCls + " mt-2"} dir="ltr" placeholder="https://example.com/product.jpg" />
            </details>
            <div className="mt-2 grid h-36 place-items-center overflow-hidden rounded-lg border border-border bg-surface">
              {imagePreviewUrl && !imagePreviewFailed ? (
                <img src={imagePreviewUrl} alt={form.title || t("products.name")} onError={() => setImagePreviewFailed(true)} className="h-full w-full object-contain" />
              ) : (
                <div className="flex flex-col items-center gap-2 text-center text-muted-foreground">
                  <Package className="h-8 w-8 opacity-45" />
                  <span className="text-[11.5px]">{imagePreviewFailed ? t("products.imagePreviewUnavailable") : t("products.imagePreview")}</span>
                </div>
              )}
            </div>
          </Field>
          <Field label={t("products.description")}>
            <textarea maxLength={4000} value={form.description} onChange={(event) => setField("description", event.target.value)} className={inputCls + " h-20 resize-y py-2"} />
          </Field>
          <p className="text-[11.5px] text-muted-foreground">{t("products.stockManagedInInventory", "Stock levels are managed from Inventory.")}</p>
          {err && <p role="alert" className="text-[12.5px] text-destructive">{err}</p>}
        </div>
        <div className="flex shrink-0 justify-end gap-2 border-t border-border px-5 py-4">
          <button type="button" onClick={onClose} disabled={saving} className="h-9 rounded-lg border border-border px-4 text-[13px] font-medium hover:bg-surface disabled:opacity-50">{t("products.cancel")}</button>
          <button type="submit" disabled={saving} className="flex h-9 items-center gap-1.5 rounded-lg bg-primary px-4 text-[13px] font-medium text-primary-foreground disabled:opacity-60">
            {saving && <Loader2 className="h-4 w-4 animate-spin" />}
            {t("products.save")}
          </button>
        </div>
      </form>
    </div>
  );
}

const inputCls = "w-full rounded-lg border border-border bg-surface px-3 py-2 text-[13px] focus:outline-hidden focus:ring-2 focus:ring-ring/30";

function Field({ label, children, asLabel = true }) {
  const Wrapper = asLabel ? "label" : "div";
  return (
    <Wrapper className="block">
      <span className="mb-1.5 block text-[12px] font-medium text-muted-foreground">{label}</span>
      {children}
    </Wrapper>
  );
}
