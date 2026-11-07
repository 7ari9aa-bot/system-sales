"""Template: «ورق دافئ» (Warm Paper) — design-2, ported from the Funny Baby
Base44 app (men's-wear restyle, 2026-11-06).

A calm paper-craft identity: cream page, brown ink, terracotta and sage
accents, gold marker highlights, ink-bordered paper cards with hard offset
shadows, dashed pills, a sage ticker strip, and tilted photo frames. Headings
stay Baloo Bhaijaan 2; body text moves to IBM Plex Sans Arabic.

The hero, feature cards and steps render through bespoke overrides registered
in ``renderer._TEMPLATE_REGISTRIES["warm-paper"]``; everything else is CSS on
the base renderers. Commerce mechanics of the source app are not ported —
products come live from the Sales OS catalog.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.website.templates.catalog import (
    TemplateManifest,
    TemplatePage,
    TemplateSection,
)

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Baloo+Bhaijaan+2:wght@400;500;600;700;800&family=IBM+Plex+Sans+Arabic:wght@300;400;500;600;700&display=swap');

:root{
  --ink:#4a3a33;--muted-ink:#6d5a50;--soft-ink:#7a665c;
  --paper:#fffdf8;--page:#fff8ef;
  --terra:#d98974;--terra-deep:#a85a47;
  --sage:#82a99b;--sage-soft:#eef5f1;
  --gold:#e9c86a;--gold-soft:#e9c86a55;
}
*{box-sizing:border-box}
body{margin:0;font-family:'IBM Plex Sans Arabic',system-ui,sans-serif;color:var(--ink);background:var(--background);font-weight:500}
h1,h2,h3,h4{font-family:'Baloo Bhaijaan 2','IBM Plex Sans Arabic',sans-serif;text-wrap:balance}
a{color:inherit;text-decoration:none}
::selection{background:rgba(217,137,116,.25)}

.site-nav{display:flex;flex-wrap:wrap;gap:1rem;align-items:center;justify-content:space-between;
  padding:.85rem 1.4rem;background:var(--paper);border-bottom:2px solid var(--ink);position:sticky;top:0;z-index:5}
.site-nav .brand{font-family:'Baloo Bhaijaan 2',sans-serif;font-weight:800;font-size:1.15rem;display:flex;align-items:center;gap:.55rem}
.site-nav .brand::before{content:'';display:inline-block;width:1.5rem;height:1.5rem;border-radius:.55rem;
  background:linear-gradient(135deg,var(--terra),var(--gold));border:2px solid var(--ink)}
.site-nav nav{display:flex;gap:.25rem 1rem;flex-wrap:wrap;font-weight:600;font-size:.95rem}
.site-nav nav a{padding:.3rem .65rem;border-radius:999px}
.site-nav nav a:hover{background:var(--gold-soft);color:var(--terra-deep)}

.site-page{max-width:73rem;margin:0 auto;padding:1rem 1.4rem 3.5rem}
.page-title{font-size:2rem;font-weight:800;margin:1.5rem 0 1.1rem}

.eyebrow{display:inline-flex;align-items:center;gap:.5rem;background:var(--gold-soft);
  border:1.5px dashed var(--terra);color:var(--terra-deep);border-radius:999px;
  padding:.375rem 1rem;font-size:.8125rem;font-weight:700;margin:0}
.eyebrow::before{content:'';width:7px;height:7px;border-radius:50%;background:var(--terra)}

.hero-paper{padding:.5rem 0 0}
.story-paper{background:var(--paper);border:2px solid var(--ink);border-radius:2.25rem}
.story-paper-green{box-shadow:8px 10px 0 var(--sage)}
.story-paper-yellow{box-shadow:8px 10px 0 var(--gold)}
.hero-paper .story-paper{padding:2.6rem 2rem;overflow:hidden}
.hero-paper-grid{display:grid;gap:2.5rem;align-items:center}
.hero-paper h1{margin:.9rem 0 0;font-size:clamp(2.4rem,6vw,4rem);font-weight:800;line-height:1.14}
.story-mark{background-image:linear-gradient(transparent 62%,rgba(233,200,106,.67) 62%);padding:0 6px}
.hero-sub{margin:1.1rem 0 0;max-width:32rem;color:var(--muted-ink);line-height:2;font-size:.98rem}
.hero-ctas{display:flex;flex-wrap:wrap;gap:.85rem;margin-top:1.6rem}
.story-btn{display:inline-flex;align-items:center;justify-content:center;gap:.5rem;border-radius:999px;
  padding:.9rem 1.8rem;font-size:1rem;font-weight:700;line-height:1;border:2px solid var(--ink);
  transition:box-shadow .2s,background-color .2s,filter .2s}
.story-btn-1{background:var(--terra);color:#fff;box-shadow:4px 5px 0 var(--ink)}
.story-btn-1:hover{filter:brightness(1.06);box-shadow:4px 7px 0 var(--ink)}
.story-btn-2{background:#fff;color:var(--ink);box-shadow:4px 5px 0 var(--sage)}
.story-btn-2:hover{background:var(--sage-soft)}
.story-note{display:inline-flex;align-items:center;gap:.5rem;margin-top:1.4rem;border-radius:999px;
  border:2px solid var(--ink);background:#fff;padding:.5rem 1rem;font-size:.78rem;font-weight:600;color:var(--muted-ink)}
.story-frame{background:#fff;border:2px solid var(--ink);border-radius:1.6rem;overflow:hidden;
  aspect-ratio:4/5;transform:rotate(1.5deg);box-shadow:8px 9px 0 var(--terra);max-width:24rem;margin-inline:auto}
.story-frame img{width:100%;height:100%;object-fit:cover}
.story-frame-empty{background:linear-gradient(160deg,var(--gold-soft),var(--sage-soft) 55%,var(--terra) 130%)}

.story-ticker{border-top:2px solid var(--ink);background:var(--sage);margin-top:2.2rem;
  border-radius:0 0 2rem 2rem;overflow:hidden;padding:.9rem 0}
.story-ticker-row{display:flex;width:max-content;animation:paper-tick 26s linear infinite;direction:ltr}
.story-tick{display:inline-flex;align-items:center;gap:1.4rem;padding-inline-end:1.4rem;white-space:nowrap;
  color:#fff;font-weight:700;font-size:.95rem}
.story-tick i{color:var(--gold);font-style:normal}
@keyframes paper-tick{from{transform:translateX(0)}to{transform:translateX(-50%)}}
@media (prefers-reduced-motion:reduce){.story-ticker-row{animation:none !important}}

.features{padding:3rem 0}
.features .eyebrow{margin-bottom:.5rem}
.features h2{margin:.4rem 0 1.4rem;font-size:1.9rem;font-weight:800}
.chap-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1.15rem}
.story-chap{display:flex;flex-direction:column;height:100%;background:#fff;border:2px solid var(--ink);
  border-radius:1.7rem;overflow:hidden;box-shadow:5px 6px 0 var(--terra);transition:box-shadow .25s,border-color .25s}
.story-chap:hover{box-shadow:5px 9px 0 var(--terra)}
.story-chap-img{display:block;aspect-ratio:5/4;border-bottom:2px solid var(--ink);
  background:linear-gradient(140deg,var(--gold-soft),var(--sage-soft) 60%,rgba(217,137,116,.55))}
.story-chap-body{display:block;padding:.95rem 1.2rem 1.4rem}
.story-chap-title{display:flex;align-items:center;justify-content:space-between;gap:.5rem;
  font-family:'Baloo Bhaijaan 2',sans-serif;font-size:1.3rem;font-weight:800}
.story-chap-note{display:block;margin-top:.4rem;font-size:.82rem;line-height:1.9;color:var(--soft-ink)}

.promise-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:1.1rem}
.story-promise{background:var(--paper);border:2px solid var(--ink);border-radius:1.6rem;
  padding:1.35rem;box-shadow:4px 5px 0 var(--gold);transition:box-shadow .25s}
.story-promise:hover{box-shadow:4px 8px 0 var(--gold)}
.story-pn{display:inline-flex;align-items:center;justify-content:center;width:38px;height:38px;
  border-radius:50%;background:var(--sage);color:#fff;font-weight:800;font-size:.85rem;border:2px solid var(--ink)}
.story-promise h3{margin:.8rem 0 0;font-size:1.2rem;font-weight:800;line-height:1.45}
.story-promise p{margin:.5rem 0 0;font-size:.82rem;line-height:1.95;color:var(--soft-ink)}

.steps{padding:3rem 0}
.steps .story-paper{padding:2.2rem 1.8rem}
.steps .eyebrow{margin-bottom:.5rem}
.steps h2{margin:.4rem 0 1.2rem;font-size:1.8rem;font-weight:800}
.step-grid{list-style:none;margin:0;padding:0;display:grid;gap:1rem}
.story-step{background:var(--page);border:2px dashed var(--sage);border-radius:1.6rem;padding:1.4rem;
  transition:border-color .25s,background-color .25s}
.story-step:hover{border-color:var(--terra);background:#fff}
.story-ghost{font-family:'Baloo Bhaijaan 2',sans-serif;font-size:1.9rem;font-weight:800;color:rgba(217,137,116,.4)}
.story-step h3{margin:.35rem 0 0;font-size:1.25rem;font-weight:800}
.story-step p{margin:.5rem 0 0;font-size:.85rem;line-height:1.95;color:var(--soft-ink)}

.product-grid h2,.collection-grid h2,.branches h2{margin:2.4rem 0 1.1rem;font-size:1.7rem;font-weight:800}
.product-grid .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1.1rem}
.product-card{background:#fff;border:2px solid var(--ink);border-radius:1.5rem;padding:1rem;text-align:center;
  box-shadow:4px 5px 0 var(--sage);transition:box-shadow .2s,transform .2s}
.product-card:hover{transform:translateY(-2px);box-shadow:5px 7px 0 var(--sage)}
.product-card .ph{height:7.5rem;border-radius:1.1rem;margin-bottom:.75rem;
  background:linear-gradient(140deg,var(--terra),var(--gold))}
.product-card .name{font-weight:700}
.product-card .price{color:var(--terra-deep);margin-top:.3rem;font-weight:800;font-family:'Baloo Bhaijaan 2',sans-serif}

.branch-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:1.1rem}
.branch-card{background:var(--paper);border:2px solid var(--ink);border-radius:1.6rem;padding:1.3rem 1.4rem;
  box-shadow:4px 5px 0 var(--gold)}
.branch-card h3{margin:0;font-size:1.15rem;font-weight:800}
.branch-card p{margin:.5rem 0 0;color:var(--soft-ink);line-height:1.85}
.branch-phone{display:inline-block;margin-top:.6rem;color:var(--terra-deep);font-weight:700;direction:ltr}
.branch-hours{font-size:.85rem !important}

.testimonial{background:var(--paper);border:2px solid var(--ink);border-radius:1.6rem;padding:1.5rem;margin:2rem 0}
.testimonial blockquote{margin:0 0 .75rem;font-size:1.05rem;line-height:1.9}

.faq details{background:var(--paper);border:2px solid var(--ink);border-radius:1.25rem;padding:.85rem 1.1rem;margin:.6rem 0;
  box-shadow:3px 4px 0 var(--gold-soft)}
.faq summary{font-weight:700;cursor:pointer;font-family:'Baloo Bhaijaan 2',sans-serif}
.faq p{color:var(--soft-ink);line-height:1.95;margin:.6rem 0 0}

.cta{text-align:center;background:var(--paper);border:2px solid var(--ink);border-radius:2rem;
  padding:2.6rem 1rem;margin:2.4rem 0;box-shadow:6px 7px 0 var(--terra)}
.cta h2{margin:0 0 .4rem;font-size:1.6rem;font-weight:800}
.cta p{margin:0;color:var(--muted-ink)}
.cta a{display:inline-block;margin-top:1.2rem;background:var(--terra);color:#fff;
  padding:.8rem 1.9rem;border-radius:999px;font-weight:700;border:2px solid var(--ink);box-shadow:4px 5px 0 var(--ink)}

.newsletter{text-align:center;margin:2rem 0}
.rich-text{line-height:2.1;max-width:44rem}
.rich-text a{color:var(--terra-deep);font-weight:700}

.site-footer{background:var(--ink);color:#f3ede7;padding:2rem 1.4rem;text-align:center;margin-top:2rem}
.site-footer a{color:var(--gold);font-weight:700}
"""

manifest = TemplateManifest(
    id="warm-paper",
    name="Warm Paper",
    name_ar="ورق دافئ",
    description="A calm paper-craft fashion design: cream page, brown ink, terracotta and sage cards, gold marker highlights.",
    description_ar="هوية ورقية هادية للأزياء: خلفية كريمي وحبر بني، كروت طوبي وزيتوني بظلال صلبة، وتسطير ذهبي للعناوين.",
    price=Decimal("2500.00"),
    css=CSS,
    theme_tokens={"primary": "#d98974", "background": "#fff8ef"},
    demo_products=(
        {"title": "قميص قطن كلاسيك — M", "price": "420.00 ج.م"},
        {"title": "تيشيرت بولو بيكي — L", "price": "310.00 ج.م"},
        {"title": "بنطلون قماش سليم — 32", "price": "540.00 ج.م"},
        {"title": "بدلة سموكينج كاملة", "price": "1850.00 ج.م"},
        {"title": "جاكيت صوف كاجوال", "price": "690.00 ج.م"},
        {"title": "قميص كاروهات شتوي — XL", "price": "480.00 ج.م"},
    ),
    preview_image="/templates/warm-paper.svg",
    pages=(
        TemplatePage(
            title="الرئيسية",
            slug="home",
            sections=(
                TemplateSection(
                    type="hero",
                    props={
                        "eyebrow": "مجموعة الموسم ٢٠٢٦",
                        "heading": "ستايل هادي\nيفرق في إطلالتك",
                        "subheading": "أقمشة مريحة وقصّات هادية ومقاسات مكتوبة بالسنتيمتر — قمصان وتيشيرتات وبناطيل وبدل، مع تغليف هدايا جاهز.",
                        "cta_label": "ابدأ التسوق",
                        "cta_url": "#page-products",
                        "secondary_label": "زيارة الفروع",
                        "secondary_url": "#page-stores",
                        "note": "تغليف هدايا مجاني في الفروع — كل أيام الأسبوع",
                        "ticker": [
                            "توصيل لكل المحافظات",
                            "استبدال حتى ١٤ يومًا",
                            "مقاسات مكتوبة بالسنتيمتر",
                            "قمصان وتيشيرتات وبناطيل",
                            "فروع في القاهرة والجيزة",
                            "تغليف هدايا في الفرع",
                        ],
                    },
                ),
                TemplateSection(
                    type="chapters",
                    props={
                        "eyebrow": "أقسام الموقع",
                        "heading": "ابدأ من الباب اللي يريحك",
                        "items": [
                            {
                                "title": "الكتالوج",
                                "text": "قمصان وبناطيل وبدل بأسعارها",
                                "href": "#page-products",
                            },
                            {
                                "title": "الفروع",
                                "text": "فروع للزيارة والتجربة",
                                "href": "#page-stores",
                            },
                            {
                                "title": "العروض",
                                "text": "عروض الموسم وأكواد الخصم",
                                "href": "#page-offers",
                            },
                            {
                                "title": "العناية والتوصيل",
                                "text": "دليل العناية وسياسة الاستبدال",
                                "href": "#page-shipping",
                            },
                        ],
                    },
                ),
                TemplateSection(
                    type="product_grid",
                    props={
                        "collection_id": "featured",
                        "title": "مختارات الموسم",
                        "limit": 8,
                        "columns": 4,
                    },
                ),
                TemplateSection(
                    type="manifesto",
                    props={
                        "eyebrow": "وعدنا لك",
                        "heading": "لا نعرض قطعة لم نقتنع بها",
                        "items": [
                            {
                                "title": "مقاس مكتوب بالسنتيمتر",
                                "text": "كل قطعة مكتوب عليها المقاس بالسنتيمتر والمدى العمري، ويمكن تجربة المقاس في الفرع قبل الشراء.",
                            },
                            {
                                "title": "توصيل لكل المحافظات",
                                "text": "نشحن من الفروع إلى جميع محافظات مصر، ويمكن متابعة حالة الطلب برقمه في أي وقت.",
                            },
                            {
                                "title": "استبدال بدون تعقيد",
                                "text": "استبدال المقاس أو اللون متاح من أي فرع أو أونلاين خلال المدة المعلنة في سياسة الاستبدال.",
                            },
                        ],
                    },
                ),
                TemplateSection(
                    type="steps",
                    props={
                        "eyebrow": "مسار الشراء",
                        "heading": "ثلاث خطوات، بلا مفاجآت",
                        "items": [
                            {
                                "title": "اختار بدقة",
                                "text": "كل قطعة مكتوب عليها المقاس بالسنتيمتر إلى جانب المدى العمري.",
                            },
                            {
                                "title": "كلمنا أو امشي للفرع",
                                "text": "فريقنا بيرد على واتساب، وفروعنا في القاهرة والجيزة جاهزة تستقبلك.",
                            },
                            {
                                "title": "استلم وتابع",
                                "text": "توصيل لكل المحافظات خلال ٤٨ ساعة، ومتابعة الطلب برقمه في أي وقت.",
                            },
                        ],
                    },
                ),
                TemplateSection(
                    type="cta",
                    props={
                        "heading": "محتاج مساعدة في القياس؟",
                        "subheading": "كلمنا على واتساب ونساعدك تختار المناسب",
                        "button_label": "تواصل معنا",
                        "button_url": "https://wa.me/201000000000",
                    },
                ),
            ),
        ),
        TemplatePage(
            title="المنتجات",
            slug="products",
            sections=(
                TemplateSection(
                    type="product_grid",
                    props={
                        "collection_id": "all",
                        "title": "كل المنتجات",
                        "limit": 24,
                        "columns": 4,
                    },
                ),
            ),
        ),
        TemplatePage(
            title="العروض",
            slug="offers",
            sections=(
                TemplateSection(
                    type="product_grid",
                    props={
                        "collection_id": "offers",
                        "title": "عروض الموسم",
                        "limit": 12,
                        "columns": 4,
                    },
                ),
            ),
        ),
        TemplatePage(
            title="الفروع",
            slug="stores",
            sections=(
                TemplateSection(
                    type="branches",
                    props={
                        "eyebrow": "فروعنا",
                        "heading": "مر ни عليك في أي فرع",
                        "items": [
                            {
                                "name": "فرع المعادي",
                                "address": "٣٧ شارع ٩، المعادي، القاهرة",
                                "phone": "01000000001",
                                "hours": "١١ ص – ١٠ م",
                            },
                            {
                                "name": "فرع مدينة نصر",
                                "address": "٥ شارع عباس العقاد، مدينة نصر، القاهرة",
                                "phone": "01000000002",
                                "hours": "١٢ م – ١٠ م",
                            },
                            {
                                "name": "فرع الشيخ زايد",
                                "address": "داون تاون مول، الدور الأول، الشيخ زايد",
                                "phone": "01000000003",
                                "hours": "١٢ م – ١١ م",
                            },
                        ],
                    },
                ),
                TemplateSection(
                    type="cta",
                    props={
                        "heading": "عندك سؤال قبل ما تمر؟",
                        "subheading": "كلمنا على واتساب أو اتصل بأقرب فرع",
                        "button_label": "واتساب",
                        "button_url": "https://wa.me/201000000000",
                    },
                ),
            ),
        ),
        TemplatePage(
            title="الأسئلة الشائعة",
            slug="faq",
            sections=(
                TemplateSection(
                    type="faq",
                    props={
                        "items": [
                            {
                                "q": "إزاي أعرف مقاسي بالظبط؟",
                                "a": "كل قطعة مكتوب عليها المقاس بالسنتيمتر والمدى العمري، ولو محتار كلمنا على واتساب وهنساعدك.",
                            },
                            {
                                "q": "بتوصلوا لكل المحافظات؟",
                                "a": "أيوه، نشحن من فروعنا إلى كل محافظات مصر خلال ٤٨ ساعة تقريبًا.",
                            },
                            {
                                "q": "أقدر أستبدل المقاس؟",
                                "a": "استبدال المقاس أو اللون متاح خلال ١٤ يوم من الاستلام، من أي فرع أو أونلاين.",
                            },
                            {
                                "q": "إزاي أدفع؟",
                                "a": "الدفع عند الاستلام أو تحويل قبل الشحن — كلمنا على واتساب ونؤكدلك التفاصيل.",
                            },
                            {
                                "q": "إزاي أتابع طلبي؟",
                                "a": "كلمنا برقم الطلب على واتساب أو من صفحة تتبع الطلب وهنقولك حالة طلبك فورًا.",
                            },
                        ],
                    },
                ),
            ),
        ),
        TemplatePage(
            title="تتبع الطلب",
            slug="track-order",
            sections=(
                TemplateSection(
                    type="rich_text",
                    props={
                        "content": "عشان تتابع طلبك: كلمنا على واتساب برقم الطلب اللي وصلك بعد الشراء، وفريقنا هيقولك حالة الطلب وميعاد التوصيل فورًا."
                    },
                ),
                TemplateSection(
                    type="cta",
                    props={
                        "heading": "تابع طلبك الآن",
                        "subheading": "ابعتلنا رقم الطلب على واتساب",
                        "button_label": "واتساب",
                        "button_url": "https://wa.me/201000000000",
                    },
                ),
            ),
        ),
        TemplatePage(
            title="الشحن والتوصيل",
            slug="shipping",
            sections=(
                TemplateSection(
                    type="rich_text",
                    props={
                        "content": "نشحن من فروعنا إلى كل محافظات مصر. مدة التوصيل من ٤٨ ساعة حتى ٣ أيام عمل حسب المحافظة، وتكلفة الشحن بتتأكد معك على واتساب قبل تأكيد الطلب."
                    },
                ),
            ),
        ),
        TemplatePage(
            title="الاستبدال والاسترجاع",
            slug="exchange-return",
            sections=(
                TemplateSection(
                    type="rich_text",
                    props={
                        "content": "استبدال المقاس أو اللون متاح خلال ١٤ يومًا من الاستلام بشرط أن القطعة بحالتها وبملصقاتها. الاسترجاع متاح خلال المدة نفسها وفقًا لسياسة المتجر — كلمنا على واتساب ونتولى الباقي."
                    },
                ),
            ),
        ),
        TemplatePage(
            title="سياسة الخصوصية",
            slug="privacy",
            sections=(
                TemplateSection(
                    type="rich_text",
                    props={
                        "content": "بياناتك بتُستخدم بس لإتمام طلبك والتواصل معك بخصوصه، ومش بنشاركها مع أي طرف تالت غير شركات الشحن. حدّث هذه الصفحة من لوحة تحكم موقعك بالسياسة الكاملة لمتجرك."
                    },
                ),
            ),
        ),
        TemplatePage(
            title="الشروط والأحكام",
            slug="terms",
            sections=(
                TemplateSection(
                    type="rich_text",
                    props={
                        "content": "باستخدامك للموقع فأنت موافق على شروط البيع والاستبدال المعلنة هنا. حدّث هذه الصفحة من لوحة تحكم موقعك بالشروط الكاملة لمتجرك."
                    },
                ),
            ),
        ),
    ),
)
