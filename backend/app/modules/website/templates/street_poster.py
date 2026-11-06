"""Template: «بوستر» (Street Poster) — design-3, ported from the Funny Baby
Base44 app (poster restyle, 2026-11-06).

A printed street-poster identity: sharp corners everywhere, cream paper
#f2f0e9, ink-black blocks, brick-red color fields, thick 3-6px borders, huge
condensed numerals, offset ink shadows, and slow poster-slide animations.
The home hero is a brick block with an ink-highlighted headline, a rotated
ink frame, a black stats strip and an ink ticker; feature rows carry giant
numbers; the promise band is olive; the path block is ink black.

The hero, features and steps render through overrides registered in
``renderer._TEMPLATE_REGISTRIES["street-poster"]``; the rest is CSS on the
base renderers. Products stay live references to the Sales OS catalog.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.website.templates.catalog import (
    TemplateManifest,
    TemplatePage,
    TemplateSection,
)

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Baloo+Bhaijaan+2:wght@400;500;600;700;800;900&family=IBM+Plex+Sans+Arabic:wght@300;400;500;600;700&display=swap');

:root{
  --ink:#111111;--paper:#f2f0e9;--card:#fffdf8;
  --brick:#c24a2b;--brick-deep:#a53d22;--olive:#4f6152;
  --muted-ink:#55524a;--gold:#e9c86a;
}
*{box-sizing:border-box}
body{margin:0;font-family:'IBM Plex Sans Arabic',system-ui,sans-serif;color:var(--ink);background:var(--background)}
h1,h2,h3,h4{font-family:'Baloo Bhaijaan 2','IBM Plex Sans Arabic',sans-serif;font-weight:900;letter-spacing:-1px}
a{color:inherit;text-decoration:none}
::selection{background:rgba(194,74,43,.3)}

.site-nav{display:flex;flex-wrap:wrap;gap:1rem;align-items:center;justify-content:space-between;
  padding:.7rem 1.3rem;background:var(--paper);border-bottom:3px solid var(--ink);position:sticky;top:0;z-index:5}
.site-nav .brand{font-family:'Baloo Bhaijaan 2',sans-serif;font-weight:900;font-size:1.1rem;
  display:flex;align-items:center;gap:.55rem}
.site-nav .brand::before{content:'FB';display:inline-flex;width:2.4rem;height:2.4rem;
  align-items:center;justify-content:center;background:var(--ink);color:var(--paper);
  font-weight:900;font-size:.9rem}
.site-nav nav{display:flex;gap:.2rem .4rem;flex-wrap:wrap}
.site-nav nav a{display:inline-block;padding:.55rem .85rem;border:3px solid transparent;
  font-family:'Baloo Bhaijaan 2',sans-serif;font-size:.9rem;font-weight:900;line-height:1}
.site-nav nav a:hover{background:var(--card);border-color:var(--ink)}

.site-page{max-width:80rem;margin:0 auto;padding:1rem 1.3rem 3.5rem}
.page-title{font-size:2.4rem;font-weight:900;letter-spacing:-1.5px;margin:1.4rem 0 1rem}

/* ------------------------------- الهيرو: كتلة طوبي ---------------------- */
.poster-hero .blk{background:var(--brick);color:var(--paper);padding:56px 60px 70px;
  position:relative;animation:poster-in-end .9s cubic-bezier(.22,1,.36,1) both}
.poster-hero .blk::after{content:'';position:absolute;left:0;right:0;bottom:46px;height:14px;background:#fff}
.poster-hero .hero{display:grid;grid-template-columns:1.1fr .9fr;gap:40px;align-items:center;position:relative;z-index:1}
.poster-hero .eb{display:inline-block;background:var(--ink);color:var(--paper);font-size:15px;
  font-weight:800;padding:8px 18px}
.poster-hero h1{font-size:clamp(2.6rem,7vw,5.2rem);line-height:1.05;font-weight:900;
  letter-spacing:-2px;margin-top:22px;animation:poster-up .8s .3s both}
.poster-hero h1 span{background:var(--ink);color:var(--paper);padding:0 12px;display:inline-block}
.poster-hero .lead{font-weight:600;font-size:17px;line-height:2;max-width:470px;margin-top:22px;
  animation:poster-up .8s .45s both}
.poster-hero .btns{display:flex;gap:14px;margin-top:28px;animation:poster-up .8s .6s both}
.poster-hero .b{display:inline-block;padding:17px 32px;font-size:17px;font-weight:900;
  border:3px solid var(--ink);transition:background .2s,color .2s}
.poster-hero .b1{background:var(--ink);color:var(--paper)}
.poster-hero .b1:hover{background:var(--paper);color:var(--ink)}
.poster-hero .b2{background:var(--paper);color:var(--ink)}
.poster-hero .b2:hover{background:var(--ink);color:var(--paper)}
.poster-hero .gift{display:inline-block;margin-top:24px;border:3px solid var(--ink);background:var(--paper);
  color:var(--ink);font-weight:800;font-size:13px;padding:9px 16px;animation:poster-up .8s .7s both}
.poster-hero .fr{position:relative;transform:rotate(3deg);border:6px solid var(--ink);background:var(--paper);
  box-shadow:14px 14px 0 var(--ink);animation:poster-in-start 1s .2s cubic-bezier(.22,1,.36,1) both}
.poster-hero .fr-img{display:block;width:100%;aspect-ratio:4/5}
.poster-hero .fr-img-empty{background:linear-gradient(160deg,var(--paper) 30%,var(--brick) 130%)}
.poster-hero .stats{display:grid;grid-template-columns:repeat(3,1fr);background:var(--ink);color:var(--paper);margin:0}
.poster-hero .st{padding:28px 34px;border-left:3px solid var(--paper)}
.poster-hero .st:last-child{border-left:0}
.poster-hero .st b{display:block;font-size:clamp(1.6rem,4vw,2.75rem);font-weight:900;letter-spacing:-1px;line-height:1.1}
.poster-hero .st:nth-child(1) b{color:var(--brick)}
.poster-hero .st:nth-child(2) b{color:#8fa593}
.poster-hero .st span{display:block;margin-top:8px;font-size:14px;font-weight:700}
.poster-hero .tick{background:var(--ink);border-top:3px solid var(--paper);border-bottom:3px solid var(--brick);
  padding:16px 0;overflow:hidden;direction:ltr}
.poster-hero .tk{display:flex;width:max-content;animation:poster-tick 34s linear infinite}
.poster-hero .tg{display:flex;flex-shrink:0}
.poster-hero .tg span{white-space:nowrap;color:var(--paper);font-size:20px;font-weight:900;
  padding-right:26px;direction:rtl}
.poster-hero .tg i{color:var(--brick);font-style:normal;padding-right:26px;font-size:20px}
@keyframes poster-in-end{from{transform:translateX(120px);opacity:0}to{transform:none;opacity:1}}
@keyframes poster-in-start{from{transform:translateX(-120px);opacity:0}to{transform:none;opacity:1}}
@keyframes poster-up{from{transform:translateY(26px);opacity:0}to{transform:none;opacity:1}}
@keyframes poster-tick{from{transform:translateX(0)}to{transform:translateX(-50%)}}
@media (prefers-reduced-motion:reduce){
  .poster-hero .blk,.poster-hero h1,.poster-hero .lead,.poster-hero .btns,
  .poster-hero .gift,.poster-hero .fr,.poster-hero .tk{animation:none !important}}

/* --------------------------------- صفوف الأبواب ------------------------- */
.poster-sec{padding:60px 0 16px}
.poster-sec .eb2{display:inline-block;background:var(--brick);color:var(--paper);font-size:14px;
  font-weight:800;padding:7px 16px}
.poster-sec h2{font-size:clamp(2rem,5vw,3.4rem);line-height:1.1;font-weight:900;letter-spacing:-1.5px;
  margin-top:16px;max-width:34rem}
.poster-sec h2 em{font-style:normal;background:var(--ink);color:var(--paper);padding:0 14px;display:inline-block}
.poster-sec .sh-lead{max-width:20rem;font-weight:600;font-size:14px;line-height:2;color:var(--muted-ink)}
.poster-sec .rows{margin-top:34px;border-top:4px solid var(--ink)}
.poster-sec .row{display:grid;grid-template-columns:110px 1fr 300px;align-items:center;gap:28px;
  border-bottom:4px solid var(--ink);position:relative;background:var(--paper);
  transition:background .25s,color .25s}
.poster-sec .row:hover{background:var(--brick);color:var(--paper)}
.poster-sec .row .n{font-size:clamp(2.6rem,7vw,5.2rem);font-weight:900;letter-spacing:-4px;line-height:1;
  padding:16px 0;text-align:center;color:var(--brick);transition:color .25s}
.poster-sec .row:hover .n{color:var(--ink)}
.poster-sec .row h3{font-size:clamp(1.4rem,3.5vw,2.3rem);font-weight:900;letter-spacing:-1px;line-height:1.15}
.poster-sec .row small{display:block;font-size:15px;font-weight:700;margin-top:8px}
.poster-sec .row-img{display:block;width:100%;height:130px;border-right:4px solid var(--ink);
  background:linear-gradient(140deg,var(--gold-soft,#e9c86a55),var(--brick) 140%)}

/* ------------------------------- شريط الوعد ----------------------------- */
.poster-pro{background:var(--olive);color:#fff;margin-top:60px;padding:60px}
.poster-pro .eb2{display:inline-block;background:var(--brick);color:var(--paper);font-size:14px;
  font-weight:800;padding:7px 16px}
.poster-pro h2{font-size:clamp(2.2rem,6vw,4.2rem);font-weight:900;line-height:1.1;letter-spacing:-1.5px;
  margin-top:16px;color:#fff}
.poster-pro h2 em{font-style:normal;background:var(--ink);padding:0 14px;display:inline-block}
.poster-pro .cols{display:grid;grid-template-columns:repeat(3,1fr);margin-top:40px;border-top:4px solid #fff}
.poster-pro .col{padding:26px 26px 6px;border-left:4px solid #fff}
.poster-pro .col:last-child{border-left:0}
.poster-pro .pn{font-size:clamp(2.4rem,6vw,4rem);font-weight:900;letter-spacing:-3px;line-height:1;color:var(--ink)}
.poster-pro .col h3{font-size:1.5rem;font-weight:900;margin-top:14px;line-height:1.35}
.poster-pro .col p{font-size:14px;font-weight:600;line-height:2;margin-top:8px}
.poster-pro .col span{display:inline-block;margin-top:10px;background:var(--ink);color:var(--paper);
  font-size:12px;font-weight:800;padding:5px 12px}

/* ------------------------------ مسار الشراء ----------------------------- */
.poster-path{background:var(--ink);color:var(--paper);padding:60px;margin-top:0}
.poster-path .eb2{display:inline-block;background:var(--paper);color:var(--ink);font-size:14px;
  font-weight:800;padding:7px 16px}
.poster-path h2{color:var(--paper);font-size:clamp(2rem,5vw,3.2rem);font-weight:900;margin-top:16px}
.poster-path .psteps{list-style:none;margin:36px 0 0;padding:0;display:grid;
  grid-template-columns:repeat(3,1fr);border-top:4px solid var(--brick)}
.poster-path .sp{padding:26px 26px 10px;border-left:4px solid #333}
.poster-path .sp:last-child{border-left:0}
.poster-path .big{font-size:clamp(3.4rem,9vw,6.8rem);font-weight:900;letter-spacing:-6px;line-height:1;
  color:var(--brick)}
.poster-path .sp h3{font-size:1.7rem;font-weight:900;margin-top:12px}
.poster-path .sp p{font-size:14px;font-weight:600;line-height:2;margin-top:8px;color:#d8d5cb}

/* --------------------------- باقي الصفحات بنفس اللغة --------------------- */
.product-grid h2,.collection-grid h2,.branches h2{margin:2.4rem 0 1.1rem;
  font-size:clamp(1.7rem,4vw,2.4rem);font-weight:900;letter-spacing:-1px}
.product-grid .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1.1rem}
.product-card{background:var(--card);border:3px solid var(--ink);padding:1rem;text-align:center;
  box-shadow:6px 6px 0 var(--ink);transition:box-shadow .2s,transform .2s}
.product-card:hover{transform:translate(-2px,-2px);box-shadow:9px 9px 0 var(--brick)}
.product-card .ph{height:7.5rem;margin-bottom:.75rem;background:linear-gradient(140deg,var(--brick),var(--gold,#e9c86a))}
.product-card .name{font-weight:700}
.product-card .price{color:var(--brick);margin-top:.3rem;font-weight:900;font-family:'Baloo Bhaijaan 2',sans-serif}

.branch-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:1.1rem}
.branch-card{background:var(--card);border:3px solid var(--ink);padding:1.3rem 1.4rem;box-shadow:6px 6px 0 var(--brick)}
.branch-card h3{margin:0;font-size:1.2rem;font-weight:900}
.branch-card p{margin:.5rem 0 0;color:var(--muted-ink);line-height:1.85}
.branch-phone{display:inline-block;margin-top:.6rem;color:var(--brick);font-weight:800;direction:ltr}
.branch-hours{font-size:.85rem !important}

.testimonial{background:var(--card);border:3px solid var(--ink);padding:1.5rem;margin:2rem 0;
  box-shadow:6px 6px 0 var(--olive)}
.testimonial blockquote{margin:0 0 .75rem;font-size:1.05rem;line-height:1.9}

.faq details{background:var(--card);border:3px solid var(--ink);padding:.85rem 1.1rem;margin:.6rem 0}
.faq summary{font-weight:800;cursor:pointer;font-family:'Baloo Bhaijaan 2',sans-serif;font-size:1.05rem}
.faq p{color:var(--muted-ink);line-height:1.95;margin:.6rem 0 0}

.cta{text-align:center;background:var(--card);border:3px solid var(--ink);padding:2.6rem 1rem;
  margin:2.4rem 0;box-shadow:8px 8px 0 var(--brick)}
.cta h2{margin:0 0 .4rem;font-size:1.8rem;font-weight:900}
.cta p{margin:0;color:var(--muted-ink)}
.cta a{display:inline-block;margin-top:1.2rem;background:var(--ink);color:var(--paper);
  padding:1rem 2rem;font-weight:900;border:3px solid var(--ink)}
.cta a:hover{background:var(--brick);color:var(--paper);border-color:var(--ink)}

.newsletter{text-align:center;margin:2rem 0}
.rich-text{line-height:2.1;max-width:44rem;font-weight:500}
.rich-text a{color:var(--brick);font-weight:800}

.site-footer{background:var(--ink);color:var(--paper);padding:2rem 1.4rem;text-align:center;
  margin-top:2rem;border-top:4px solid var(--brick)}
.site-footer a{color:var(--gold);font-weight:800}

@media (max-width:1023px){
  .poster-hero .blk{padding:40px 28px 58px}
  .poster-hero .blk::after{bottom:30px;height:10px}
  .poster-hero .hero{grid-template-columns:1fr;gap:34px}
  .poster-sec .row{grid-template-columns:64px 1fr 150px;gap:16px}
  .poster-sec .row-img{height:96px}
  .poster-pro,.poster-path{padding:44px 24px}
  .poster-sec{padding:44px 0 16px}
}
@media (max-width:767px){
  .poster-hero .btns{flex-wrap:wrap}
  .poster-sec .row{grid-template-columns:56px 1fr}
  .poster-sec .row-img{display:none}
  .poster-pro .cols,.poster-path .psteps{grid-template-columns:1fr}
  .poster-pro .col,.poster-path .sp{border-left:0;border-top:4px solid rgba(255,255,255,.4);padding:20px 0}
  .poster-pro .col:first-child,.poster-path .sp:first-child{border-top:0}
  .poster-hero .stats{grid-template-columns:1fr}
  .poster-hero .st{border-left:0;border-top:3px solid var(--paper)}
  .poster-hero .st:first-child{border-top:0}
}
"""

manifest = TemplateManifest(
    id="street-poster",
    name="Street Poster",
    name_ar="بوستر",
    description="A printed street-poster identity: brick blocks, ink borders, giant numerals, sharp corners.",
    description_ar="هوية ملصق شارع مطبوع: كتل طوبي وحدود حبر سميكة وأرقام ضخمة وزوايا حادة.",
    price=Decimal("2500.00"),
    css=CSS,
    theme_tokens={"primary": "#c24a2b", "background": "#f2f0e9"},
    preview_image="/templates/street-poster.svg",
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
                        "stats": [
                            {"value": "S – XXL", "label": "المقاسات المتاحة"},
                            {"value": "٣", "label": "فروع بالقاهرة والجيزة"},
                            {"value": "٤٨ س", "label": "توصيل لكل المحافظات"},
                        ],
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
                    type="features",
                    props={
                        "eyebrow": "أقسام الموقع",
                        "heading": "ابدأ من الباب اللي يريحك",
                        "text": "أربعة أبواب مختصرة: تسوّق، زور فرعًا، شوف العروض، أو اعرف كل حاجة عن العناية والتوصيل.",
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
                    type="features",
                    props={
                        "eyebrow": "وعدنا لك",
                        "heading": "لا نعرض قطعة\nلم نقتنع بها",
                        "text": "نختار القليل ونشرحه جيدًا: الخامة، المقاس، وطريقة العناية. حتى تصلك القطعة كما توقعتها.",
                        "items": [
                            {
                                "title": "مقاس مكتوب بالسنتيمتر",
                                "text": "كل قطعة مكتوب عليها المقاس بالسنتيمتر والعمر، ويمكن تجربة المقاس في الفرع قبل الشراء.",
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
                        "heading": "مر ني عليك في أي فرع",
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
