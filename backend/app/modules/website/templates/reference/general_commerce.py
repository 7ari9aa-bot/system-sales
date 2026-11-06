"""Reference template: a clean general-commerce store front.

Arabic-first (the renderer serves dir="rtl" lang=ar by default), neutral
palette driven by theme tokens so the merchant can recolor from the dashboard
without touching this file. This template is also the CONTRACT EXAMPLE for
the 20 merchant templates: manifest + CSS, nothing else.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.website.templates.catalog import TemplateManifest, TemplatePage, TemplateSection

CSS = """
:root{--fg:#1f2937;--muted:#6b7280;--card:#ffffff;--line:#e5e7eb}
*{box-sizing:border-box}
body{margin:0;font-family:'Segoe UI',Tahoma,Arial,sans-serif;color:var(--fg);background:var(--background)}
a{color:inherit;text-decoration:none}
.site-nav{display:flex;flex-wrap:wrap;gap:1rem;align-items:center;justify-content:space-between;padding:.9rem 1.25rem;background:var(--card);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5}
.site-nav .brand{font-weight:700;font-size:1.05rem}
.site-nav nav{display:flex;gap:1rem;flex-wrap:wrap}
.site-page{max-width:1080px;margin:0 auto;padding:1.5rem 1.25rem 3rem}
.hero{display:flex;flex-direction:column;align-items:center;text-align:center;gap:.75rem;padding:4rem 1rem;border-radius:16px;background:linear-gradient(135deg,var(--primary),var(--primary));color:#fff}
.hero h1{margin:0;font-size:2.2rem}
.hero p{margin:0;opacity:.9;max-width:520px}
.hero a{display:inline-block;margin-top:.5rem;background:#fff;color:var(--primary);padding:.65rem 1.6rem;border-radius:999px;font-weight:600}
.rich-text{line-height:1.9;color:var(--fg)}
.image-text{display:flex;gap:1.5rem;align-items:center;margin:2rem 0;flex-wrap:wrap}
.image-text--right{flex-direction:row-reverse}
.image-text img{max-width:320px;width:100%;border-radius:12px}
.image-text h2{margin:0 0 .5rem}
.product-grid h2,.collection-grid h2{margin:2.5rem 0 1rem}
.product-grid .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1rem}
.product-card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:1rem;text-align:center}
.product-card .ph{height:120px;border-radius:8px;background:linear-gradient(135deg,var(--primary),var(--primary));opacity:.15;margin-bottom:.75rem}
.product-card .name{font-weight:600}
.product-card .price{color:var(--muted);margin-top:.25rem}
.testimonial{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:1.5rem;margin:2rem 0}
.testimonial blockquote{margin:0 0 .75rem;font-size:1.05rem;line-height:1.8}
.faq details{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.8rem 1rem;margin:.5rem 0}
.faq summary{font-weight:600;cursor:pointer}
.cta{text-align:center;background:var(--card);border:1px solid var(--line);border-radius:16px;padding:2.5rem 1rem;margin:2rem 0}
.cta h2{margin:0 0 .4rem}
.cta a{display:inline-block;margin-top:1rem;background:var(--primary);color:#fff;padding:.7rem 1.8rem;border-radius:999px;font-weight:600}
.newsletter{text-align:center;margin:2rem 0}
.site-footer{border-top:1px solid var(--line);padding:1.5rem;text-align:center;color:var(--muted);background:var(--card)}
"""

manifest = TemplateManifest(
    id="general-commerce",
    name="Clean Store",
    name_ar="متجر أنيق",
    description="A clean, general-purpose store front for any product line.",
    description_ar="واجهة متجر أنيقة وعامة تناسب أي نشاط تجاري.",
    price=Decimal("1500.00"),
    css=CSS,
    theme_tokens={"primary": "#0f172a", "background": "#ffffff"},
    preview_image="/templates/general-commerce.svg",
    pages=(
        TemplatePage(
            title="الرئيسية",
            slug="home",
            sections=(
                TemplateSection(
                    type="hero",
                    props={
                        "heading": "أهلاً بك في متجرنا",
                        "subheading": "منتجات مختارة بعناية، وخدمة تليق بك",
                        "cta_label": "تسوق الآن",
                        "cta_url": "#page-products",
                    },
                ),
                TemplateSection(
                    type="product_grid",
                    props={
                        "collection_id": "featured",
                        "title": "منتجاتنا",
                        "limit": 8,
                        "columns": 4,
                    },
                ),
                TemplateSection(
                    type="testimonial",
                    props={
                        "quote": "خدمة سريعة ومنتجات ممتازة، تجربة شراء مريحة من أول رسالة للمنتج في إيدي.",
                        "author": "أحمد م.",
                        "role": "عميل",
                    },
                ),
                TemplateSection(
                    type="cta",
                    props={
                        "heading": "محتاج مساعدة في الاختيار؟",
                        "subheading": "كلمنا ونساعدك تختار المناسب لك",
                        "button_label": "تواصل معنا",
                        "button_url": "https://wa.me/201000000000",
                    },
                ),
            ),
        ),
        TemplatePage(
            title="عن المتجر",
            slug="about",
            sections=(
                TemplateSection(
                    type="rich_text",
                    props={
                        "content": "بدأنا بفكرة بسيطة: منتجات كويسة بسعر عادل وخدمة تحترم وقت العميل. كل طلب بيتم تحضيره بعناية وبيوصلك في أسرع وقت."
                    },
                ),
            ),
        ),
    ),
)
