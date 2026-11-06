"""Reference template: a warm restaurant / cafe front with a menu grid."""

from __future__ import annotations

from decimal import Decimal

from app.modules.website.templates.catalog import TemplateManifest, TemplatePage, TemplateSection

CSS = """
:root{--fg:#3f2d20;--muted:#8a7361;--card:#fffaf3;--line:#ead9c5}
*{box-sizing:border-box}
body{margin:0;font-family:'Segoe UI',Tahoma,Arial,sans-serif;color:var(--fg);background:var(--background)}
a{color:inherit;text-decoration:none}
.site-nav{display:flex;flex-wrap:wrap;gap:1rem;align-items:center;justify-content:space-between;padding:.9rem 1.25rem;background:var(--card);border-bottom:2px solid var(--primary);position:sticky;top:0;z-index:5}
.site-nav .brand{font-weight:800;font-size:1.1rem}
.site-nav nav{display:flex;gap:1rem;flex-wrap:wrap}
.site-page{max-width:1000px;margin:0 auto;padding:1.5rem 1.25rem 3rem}
.hero{display:flex;flex-direction:column;align-items:center;text-align:center;gap:.75rem;padding:4.5rem 1rem;border-radius:18px;background:linear-gradient(160deg,var(--primary),#9a3412);color:#fff}
.hero h1{margin:0;font-size:2.4rem}
.hero p{margin:0;opacity:.92;max-width:520px}
.rich-text{line-height:2}
.product-grid h2,.collection-grid h2{margin:2.5rem 0 1rem}
.product-grid .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:1rem}
.product-card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:1rem;text-align:center;box-shadow:0 1px 3px rgba(63,45,32,.08)}
.product-card .ph{height:110px;border-radius:10px;background:linear-gradient(135deg,var(--primary),#f59e0b);opacity:.2;margin-bottom:.75rem}
.product-card .name{font-weight:700}
.product-card .price{color:var(--primary);margin-top:.25rem;font-weight:600}
.faq details{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:.8rem 1rem;margin:.5rem 0}
.faq summary{font-weight:700;cursor:pointer}
.cta{text-align:center;background:var(--primary);color:#fff;border-radius:18px;padding:2.75rem 1rem;margin:2rem 0}
.cta h2{margin:0 0 .4rem}
.cta p{opacity:.9;margin:0}
.cta a{display:inline-block;margin-top:1.25rem;background:#fff;color:var(--primary);padding:.75rem 2rem;border-radius:999px;font-weight:700}
.site-footer{border-top:2px solid var(--primary);padding:1.5rem;text-align:center;color:var(--muted);background:var(--card)}
"""

manifest = TemplateManifest(
    id="restaurant",
    name="Warm Diner",
    name_ar="مطعم دافئ",
    description="A warm, appetite-first front for restaurants and cafes.",
    description_ar="واجهة دافئة تناسب المطاعم والكافيهات، مع منيو ومنتجات مميزة.",
    price=Decimal("1800.00"),
    css=CSS,
    theme_tokens={"primary": "#7f1d1d", "background": "#fff7ed"},
    preview_image="/templates/restaurant.svg",
    pages=(
        TemplatePage(
            title="الرئيسية",
            slug="home",
            sections=(
                TemplateSection(
                    type="hero",
                    props={
                        "heading": "من قلب المطبخ",
                        "subheading": "أكل بيتي بمكونات طازجة وطعم زي بيتنا بالظبط",
                    },
                ),
                TemplateSection(
                    type="product_grid",
                    props={"collection_id": "menu", "title": "المنيو", "limit": 12, "columns": 3},
                ),
                TemplateSection(
                    type="testimonial",
                    props={
                        "quote": "أحسن وجبة اتناولتها من زمان، والطلب بيوصل سخن وفي وقته.",
                        "author": "منى س.",
                    },
                ),
                TemplateSection(
                    type="cta",
                    props={
                        "heading": "احجز ترابيزتك",
                        "subheading": "متاح للحجز يوميًا من 12 ظهرًا حتى 12 مساءً",
                        "button_label": "اتصل بينا",
                        "button_url": "tel:+201000000000",
                    },
                ),
            ),
        ),
    ),
)
