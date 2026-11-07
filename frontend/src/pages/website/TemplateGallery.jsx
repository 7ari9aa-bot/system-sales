import React from "react";
import { Check, ExternalLink, Globe, Rocket } from "lucide-react";
import { SectionCard } from "@/components/dashboard/ui";
import { api, apiUrl } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { slugError, slugify } from "./slugRules";

/** The template gallery: every template is a real design the merchant can
 *  preview, pick, name, and purchase. The POST carries an Idempotency-Key —
 *  a double-click or a retried request must never create two purchases. */

function formatPrice(value, isAr) {
  const amount = Number(value ?? 0).toLocaleString(isAr ? "ar-EG" : "en-EG", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return isAr ? `${amount} ج.م` : `EGP ${amount}`;
}

export default function TemplateGallery({ onPurchased }) {
  const { lang } = useI18n();
  const isAr = lang === "ar";
  const L = (ar, en) => (isAr ? ar : en);

  const [templates, setTemplates] = React.useState(null);
  const [selected, setSelected] = React.useState("");
  const [siteName, setSiteName] = React.useState("");
  const [slug, setSlug] = React.useState("");
  const [slugTouched, setSlugTouched] = React.useState(false);
  const [siteCategory, setSiteCategory] = React.useState("");
  const [whatsappNumber, setWhatsappNumber] = React.useState("");
  const [instagramUrl, setInstagramUrl] = React.useState("");
  const [facebookUrl, setFacebookUrl] = React.useState("");
  const [tiktokUrl, setTiktokUrl] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    let alive = true;
    api("/website/templates")
      .then((data) => {
        if (alive) setTemplates(data?.templates ?? []);
      })
      .catch((err) => {
        if (alive) setError(err?.message || L("تعذر تحميل القوالب", "Could not load templates"));
      });
    return () => {
      alive = false;
    };
     
  }, []);

  const effectiveSlug = slugTouched ? slug : slugify(siteName);
  const slugProblem = slugError(effectiveSlug);

  const submit = async () => {
    if (!selected || slugProblem || busy) return;
    setBusy(true);
    setError("");
    try {
      await api("/website/purchase", {
        method: "POST",
        headers: { "Idempotency-Key": (crypto.randomUUID?.() ?? `id-${Date.now()}-${Math.random().toString(36).slice(2)}`) },
        body: JSON.stringify({
          template_id: selected,
          site_name: siteName.trim(),
          slug: effectiveSlug,
          site_category: siteCategory || null,
          whatsapp_number: whatsappNumber.trim() || null,
          social_links: [
            ...(instagramUrl.trim() ? [{ platform: "instagram", href: instagramUrl.trim() }] : []),
            ...(facebookUrl.trim() ? [{ platform: "facebook", href: facebookUrl.trim() }] : []),
            ...(tiktokUrl.trim() ? [{ platform: "tiktok", href: tiktokUrl.trim() }] : []),
          ],
        }),
      });
      onPurchased();
    } catch (err) {
      setError(err?.message || L("تعذر إنشاء الطلب", "Could not create the purchase"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <SectionCard
      title={L("اختر تصميم موقعك", "Choose your website design")}
      action={
        selected ? (
          <span className="text-xs text-muted-foreground">
            {L("التصميم المحدد", "Selected")}: {templates.find((t) => t.id === selected)?.[isAr ? "name_ar" : "name"]}
          </span>
        ) : null
      }
    >
      {!templates ? (
        <div className="animate-pulse grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-56 rounded-xl bg-muted" />
          ))}
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {templates.map((tpl) => (
            <div
              key={tpl.id}
              role="button"
              aria-pressed={selected === tpl.id}
              tabIndex={0}
              onClick={() => setSelected(tpl.id)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setSelected(tpl.id);
                }
              }}
              className={`group cursor-pointer rounded-xl border p-3 text-start transition ${
                selected === tpl.id
                  ? "border-primary ring-2 ring-primary/30"
                  : "hover:border-primary/40"
              }`}
            >
              <div className="mb-3 aspect-[4/3] overflow-hidden rounded-lg bg-gradient-to-br from-primary/10 to-primary/5">
                {tpl.preview_image ? (
                  <img src={tpl.preview_image} alt={isAr ? tpl.name_ar : tpl.name} loading="lazy" className="h-full w-full object-cover" />
                ) : (
                  <div className="grid h-full place-items-center">
                    <Globe className="h-10 w-10 text-primary/40" />
                  </div>
                )}
              </div>
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="text-sm font-semibold">{isAr ? tpl.name_ar : tpl.name}</div>
                  <div className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                    {isAr ? tpl.description_ar : tpl.description}
                  </div>
                </div>
                {selected === tpl.id ? (
                  <span className="rounded-full bg-primary p-1 text-primary-foreground">
                    <Check className="h-3.5 w-3.5" />
                  </span>
                ) : null}
              </div>
              <div className="mt-2 flex items-center justify-between gap-2">
                <span className="text-sm font-semibold text-primary">
                  {formatPrice(tpl.price, isAr)}
                </span>
                {/* المعاينة الحية: الموقع الديمو كامل يفتح في تاب جديد —
                    زرار مستقل عن تحديد الكارت عشان الزائر يتجول الأول. */}
                {/* عبر قاعدة الـ API: في الإنتاج الواجهة بتكلم الباك على أصل
                    مختلف، فالمعاينة لازم تتفتح من أصل الباك عشان روابط
                    التنقل جوه الديمو تفضل شغالة. */}
                <a
                  href={apiUrl(`/public/preview/${tpl.id}`)}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={(e) => e.stopPropagation()}
                  className="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-medium hover:bg-accent"
                >
                  <ExternalLink className="h-3.5 w-3.5" />
                  {isAr ? "معاينة حية" : "Live preview"}
                </a>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="mt-6 rounded-xl border bg-muted/30 p-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block">
            <span className="mb-1 block text-sm font-medium">{L("اسم الموقع", "Site name")}</span>
            <input
              value={siteName}
              onChange={(e) => setSiteName(e.target.value)}
              placeholder={L("مثال: متجر النور", "e.g. Al-Nour Store")}
              maxLength={200}
              className="w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-primary/30"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium">
              {L("عنوان الموقع", "Site address")}
              <span className="ms-1 font-normal text-muted-foreground">
                {L("(بالإنجليزية — هيبقى رابط موقعك)", "(latin — becomes your site link)")}
              </span>
            </span>
            <div className="flex items-center gap-2">
              <input
                value={effectiveSlug}
                onChange={(e) => {
                  setSlugTouched(true);
                  setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ""));
                }}
                placeholder={L("my-store", "my-store")}
                maxLength={80}
                dir="ltr"
                className={`w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-primary/30 ${
                  effectiveSlug && slugProblem ? "border-red-400" : ""
                }`}
              />
            </div>
            {effectiveSlug && slugProblem ? (
              <span className="mt-1 block text-xs text-red-600">
                {slugProblem === "reserved"
                  ? L("العنوان ده محجوز، اختار غيره", "That address is reserved — pick another")
                  : slugProblem === "short"
                    ? L("العنوان لازم 3 حروف على الأقل", "At least 3 characters")
                    : L("حروف إنجليزية صغيرة وأرقام وشرطة فقط، ويبدأ وينتهي بحرف أو رقم", "Lowercase letters, digits and hyphens only")}
              </span>
            ) : null}
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium">{L("فئة الموقع", "Site category")}</span>
            <select
              value={siteCategory}
              onChange={(e) => setSiteCategory(e.target.value)}
              className="w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-primary/30"
            >
              <option value="">{L("اختار الفئة", "Select category")}</option>
              <option value="clothing">{L("ملابس", "Clothing")}</option>
              <option value="shoes">{L("أحذية", "Shoes")}</option>
              <option value="accessories">{L("إكسسوارات", "Accessories")}</option>
              <option value="electronics">{L("إلكترونيات", "Electronics")}</option>
              <option value="furniture">{L("أثاث", "Furniture")}</option>
              <option value="food">{L("أكل ومشروبات", "Food & Drinks")}</option>
              <option value="beauty">{L("عناية وجمال", "Beauty")}</option>
              <option value="other">{L("أخرى", "Other")}</option>
            </select>
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium">
              {L("رقم الواتساب", "WhatsApp number")}
              <span className="ms-1 font-normal text-muted-foreground">
                {L("(هيظهر على موقعك)", "(shown on your site)")}
              </span>
            </span>
            <input
              value={whatsappNumber}
              onChange={(e) => setWhatsappNumber(e.target.value)}
              placeholder="201000000000"
              maxLength={30}
              dir="ltr"
              className="w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-primary/30"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium">{L("إنستجرام", "Instagram")}</span>
            <input
              value={instagramUrl}
              onChange={(e) => setInstagramUrl(e.target.value)}
              placeholder="https://instagram.com/..."
              dir="ltr"
              className="w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-primary/30"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium">{L("فيسبوك", "Facebook")}</span>
            <input
              value={facebookUrl}
              onChange={(e) => setFacebookUrl(e.target.value)}
              placeholder="https://facebook.com/..."
              dir="ltr"
              className="w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-primary/30"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium">{L("تيك توك", "TikTok")}</span>
            <input
              value={tiktokUrl}
              onChange={(e) => setTiktokUrl(e.target.value)}
              placeholder="https://tiktok.com/..."
              dir="ltr"
              className="w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-primary/30"
            />
          </label>
        </div>

        {error ? <div role="alert" className="mt-3 text-sm text-red-600">{error}</div> : null}

        <button
          type="button"
          onClick={submit}
          disabled={!selected || !siteName.trim() || Boolean(slugProblem) || busy}
          className="mt-4 inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          <Rocket className="h-4 w-4" />
          {busy
            ? L("جارٍ إنشاء الطلب…", "Creating the purchase…")
            : L("اطلب الموقع بهذا التصميم", "Purchase the website with this design")}
        </button>
        <p className="mt-2 text-xs text-muted-foreground">
          {L(
            "بعد الطلب هتلاقي تعليمات الدفع، والموقع بيتفعل أول ما يتأكد الدفع.",
            "After ordering you'll see the payment instructions; the site activates once payment is confirmed.",
          )}
        </p>
      </div>
    </SectionCard>
  );
}
