"""Template: «أطفال مرح» (Playful Kids) — design-1, ported from the Funny Baby
Base44 app (v2 source, 2026-11-06).

Faithful port of the design language: warm cream page, coral primary, teal
secondary, golden accent, dark-navy ink; Baloo Bhaijaan 2 headings over
Tajawal body; neo-brutalist cards (2px ink borders, hard offset shadows,
hover lift); eyebrow pills; numbered step circles. The commerce mechanics of
the source app (accounts, cart, checkout, Base44 entities) are deliberately
NOT ported — this template renders presentation only; products come live from
the Sales OS catalog and selling happens through the chat/cashier.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.website.templates.catalog import (
    TemplateManifest,
    TemplatePage,
    TemplateSection,
)

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Baloo+Bhaijaan+2:wght@400;500;600;700;800&family=Tajawal:wght@300;400;500;700;800&display=swap');

:root{
  --fg:#241e38;--muted-fg:#645e78;--card:#ffffff;
  --secondary:#dcf9f6;--secondary-fg:#124749;
  --accent:#ffc533;--accent-fg:#201b32;
  --muted:#f8f4e7;--line:#dad7e4;--whatsapp:#1f8452;
  --ink-border:2px solid rgba(36,30,56,.1)
}
*{box-sizing:border-box}
body{margin:0;font-family:'Tajawal',system-ui,sans-serif;color:var(--fg);background:var(--background)}
h1,h2,h3,h4{font-family:'Baloo Bhaijaan 2','Tajawal',sans-serif;letter-spacing:0;text-wrap:balance}
a{color:inherit;text-decoration:none}
::selection{background:rgba(243,81,63,.2)}

.site-nav{display:flex;flex-wrap:wrap;gap:1rem;align-items:center;justify-content:space-between;
  padding:.85rem 1.25rem;background:var(--card);border-bottom:var(--ink-border);position:sticky;top:0;z-index:5}
.site-nav .brand{font-family:'Baloo Bhaijaan 2',sans-serif;font-weight:800;font-size:1.15rem;display:flex;align-items:center;gap:.5rem}
.site-nav .brand::before{content:'';display:inline-block;width:1.6rem;height:1.6rem;border-radius:50%;
  background:radial-gradient(circle at 30% 30%,var(--accent) 0 40%,var(--primary) 42% 100%)}
.site-nav nav{display:flex;gap:.35rem 1rem;flex-wrap:wrap;font-weight:500}
.site-nav nav a{padding:.3rem .6rem;border-radius:999px}
.site-nav nav a:hover{background:rgba(243,81,63,.1);color:var(--primary)}

.site-page{max-width:72rem;margin:0 auto;padding:1rem 1.25rem 3.5rem}
.page-title{font-size:1.9rem;font-weight:800;margin:1.5rem 0 1rem}

.eyebrow{display:inline-block;border-radius:999px;background:rgba(243,81,63,.1);
  padding:.25rem .75rem;font-size:.75rem;font-weight:700;color:var(--primary);margin:0}

.hero{position:relative;overflow:hidden;border-radius:0 0 2.5rem 2.5rem}
.hero::before{content:'';position:absolute;top:-6rem;inset-inline-end:-8%;width:26rem;height:26rem;
  border-radius:50%;background:var(--accent);opacity:.55;filter:blur(64px)}
.hero::after{content:'';position:absolute;bottom:-9rem;inset-inline-start:-8%;width:22rem;height:22rem;
  border-radius:50%;background:var(--secondary);filter:blur(64px)}
.hero>*{position:relative;z-index:1}
.hero{padding:4.5rem 1.25rem 5rem;display:flex;flex-direction:column;align-items:center;text-align:center;gap:.75rem}
.hero .eyebrow{border:var(--ink-border);background:var(--accent);color:var(--accent-fg);font-weight:700}
.hero h1{margin:.75rem 0 0;font-size:clamp(2.2rem,5vw,3.6rem);font-weight:800;line-height:1.15}
.hero h1::after{content:'';display:block;width:min(14rem,60%);height:.65rem;margin:.35rem auto 0;
  border-radius:999px;background:var(--accent);opacity:.65}
.hero p{margin:0;max-width:34rem;color:var(--muted-fg);line-height:1.9}
.hero a{display:inline-block;margin-top:1.25rem;background:var(--primary);color:#fff;
  padding:.8rem 1.9rem;border-radius:999px;font-weight:700;font-family:'Baloo Bhaijaan 2',sans-serif;
  box-shadow:4px 4px 0 0 var(--fg);transition:transform .15s ease,box-shadow .15s ease}
.hero a:hover{transform:translateY(-2px);box-shadow:5px 6px 0 0 var(--fg)}

.features{padding:2.5rem 0}
.features h2{margin:.5rem 0 1.25rem;font-size:1.7rem}
.feature-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:1rem}
.feature-card{display:flex;align-items:flex-start;gap:.85rem;border-radius:1.75rem;border:var(--ink-border);padding:1.15rem}
.feature-card--0{background:var(--card)}
.feature-card--1{background:var(--secondary);color:var(--secondary-fg)}
.feature-card--2{background:rgba(255,197,51,.25)}
.feature-card--1 p,.feature-card--2 p{color:inherit;opacity:.75}
.feature-badge{flex-shrink:0;width:2.4rem;height:2.4rem;border-radius:.9rem;margin-top:.1rem}
.feature-card--0 .feature-badge{background:var(--primary)}
.feature-card--1 .feature-badge{background:var(--fg)}
.feature-card--2 .feature-badge{background:var(--accent)}
.feature-card h3{margin:0;font-size:1rem;font-weight:700}
.feature-card p{margin:.35rem 0 0;font-size:.875rem;line-height:1.8;color:var(--muted-fg)}

.image-text{display:flex;gap:1.75rem;align-items:center;margin:2.5rem 0;flex-wrap:wrap}
.image-text--right{flex-direction:row-reverse}
.image-text img{max-width:22rem;width:100%;border-radius:2.25rem;border:3px solid rgba(36,30,56,.15)}
.image-text h2{margin:0 0 .5rem;font-size:1.8rem;font-weight:800}
.image-text p{margin:0;line-height:1.9;color:var(--muted-fg)}

.steps{border-top:var(--ink-border);margin-top:2.5rem;padding:3.5rem 0}
.steps .eyebrow{margin-bottom:.4rem}
.steps h2{margin:0;font-size:1.9rem;font-weight:800}
.steps-text{max-width:28rem;color:var(--muted-fg);line-height:1.9;margin:.75rem 0 1.5rem}
.steps-list{list-style:none;margin:0;padding:0;display:grid;gap:1rem}
.step-card{background:var(--card);border:var(--ink-border);border-radius:1.75rem;padding:1.4rem 1.5rem;
  transition:transform .15s ease,box-shadow .15s ease,border-color .15s ease}
.step-card:hover{transform:translateY(-2px);border-color:rgba(243,81,63,.4);box-shadow:6px 6px 0 0 var(--accent)}
.step-num{display:inline-flex;align-items:center;justify-content:center;width:2.1rem;height:2.1rem;
  border-radius:50%;background:var(--primary);color:#fff;font-family:'Baloo Bhaijaan 2',sans-serif;font-weight:700}
.step-card h3{display:inline;margin:0 0 0 .6rem;font-size:1.1rem;font-weight:700;vertical-align:middle}
.step-card p{margin:.6rem 0 0;max-width:34rem;color:var(--muted-fg);font-size:.9rem;line-height:1.9}

.product-grid h2,.collection-grid h2,.branches h2{margin:2.5rem 0 1.1rem;font-size:1.7rem;font-weight:800}
.product-grid .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:1rem}
.product-card{background:var(--card);border:var(--ink-border);border-radius:1.5rem;padding:1rem;text-align:center;
  transition:transform .15s ease,box-shadow .15s ease}
.product-card:hover{transform:translateY(-2px);box-shadow:5px 5px 0 0 var(--accent)}
.product-card .ph{height:7.5rem;border-radius:1rem;margin-bottom:.75rem;
  background:linear-gradient(135deg,var(--primary),var(--accent));opacity:.85}
.product-card .name{font-weight:700}
.product-card .price{color:var(--primary);margin-top:.3rem;font-weight:800;font-family:'Baloo Bhaijaan 2',sans-serif}

.branch-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:1rem}
.branch-card{background:var(--card);border:var(--ink-border);border-radius:1.75rem;padding:1.3rem 1.4rem}
.branch-card h3{margin:0;font-size:1.15rem;font-weight:700}
.branch-card p{margin:.5rem 0 0;color:var(--muted-fg);line-height:1.8}
.branch-phone{display:inline-block;margin-top:.6rem;color:var(--primary);font-weight:700;direction:ltr}
.branch-hours{font-size:.85rem !important}

.testimonial{background:var(--card);border:var(--ink-border);border-radius:1.75rem;padding:1.5rem;margin:2rem 0}
.testimonial blockquote{margin:0 0 .75rem;font-size:1.05rem;line-height:1.9}

.faq details{background:var(--card);border:var(--ink-border);border-radius:1.25rem;padding:.85rem 1.1rem;margin:.6rem 0}
.faq summary{font-weight:700;cursor:pointer;font-family:'Baloo Bhaijaan 2',sans-serif}
.faq p{color:var(--muted-fg);line-height:1.9;margin:.6rem 0 0}

.cta{text-align:center;background:var(--card);border:var(--ink-border);border-radius:2rem;
  padding:2.75rem 1rem;margin:2.5rem 0;box-shadow:6px 6px 0 0 var(--accent)}
.cta h2{margin:0 0 .4rem;font-size:1.6rem;font-weight:800}
.cta p{margin:0;color:var(--muted-fg)}
.cta a{display:inline-block;margin-top:1.25rem;background:var(--primary);color:#fff;
  padding:.75rem 1.9rem;border-radius:999px;font-weight:700;box-shadow:4px 4px 0 0 var(--fg)}

.newsletter{text-align:center;margin:2rem 0}
.rich-text{line-height:2;max-width:44rem}
.rich-text a{color:var(--primary);font-weight:700}

.site-footer{background:var(--fg);color:#efeef6;padding:2rem 1.25rem;text-align:center;margin-top:2rem}
.site-footer a{color:var(--accent);font-weight:700}
"""

manifest = TemplateManifest(
    id="funny-baby",
    name="Playful Kids",
    name_ar="أطفال مرح",
    description="A playful kids-store design: warm cream page, coral primary, teal and golden cards, bold ink borders.",
    description_ar="تصميم مرح لمتجر أطفال: خلفية كريمي دافية، أساسي كورال، كروت تركواز ودهبي، وحدود حبر سميكة وظلال صلبة.",
    price=Decimal("2000.00"),
    css=CSS,
    theme_tokens={"primary": "#f3513f", "background": "#fffdf5"},
    demo_products=(
        {"title": "بودي سوت قطن — ٠-٣ شهور", "price": "185.00 ج.م"},
        {"title": "أفرول شتوي بالكابوت — ٣-٦ شهور", "price": "320.00 ج.م"},
        {"title": "طقم نوم قطن قطعتين — ٦-٩ شهور", "price": "240.00 ج.م"},
        {"title": "تيشيرت تريكو ملون — ١-٢ سنة", "price": "150.00 ج.م"},
        {"title": "جاكيت شتوي بالفرو — ٢-٣ سنة", "price": "395.00 ج.م"},
        {"title": "فستان حفلات مطرز — ٣-٤ سنة", "price": "465.00 ج.م"},
        {"title": "بنطلون قطن مرن — ٤-٥ سنة", "price": "175.00 ج.م"},
        {"title": "بيجامة قطن قطعتين — ٥-٦ سنة", "price": "210.00 ج.م"},
    ),
    preview_image="/templates/funny-baby.svg",
    pages=(
        TemplatePage(
            title="الرئيسية",
            slug="home",
            sections=(
                TemplateSection(
                    type="hero",
                    props={
                        "heading": "ملابس تلعب وتنام، وتكبر مع طفلك",
                        "subheading": "من أجسام المواليد حتى أفرول المدرسة، قطع مختارة بعناية تناسب حركة الأطفال، بمقاسات حقيقية وألوان مبهجة.",
                        "cta_label": "تسوق الآن",
                        "cta_url": "#page-products",
                    },
                ),
                TemplateSection(
                    type="features",
                    props={
                        "eyebrow": "وعودنا ليك",
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
                    type="product_grid",
                    props={
                        "collection_id": "featured",
                        "title": "منتجاتنا",
                        "limit": 8,
                        "columns": 4,
                    },
                ),
                TemplateSection(
                    type="image_text",
                    props={
                        "heading": "ملابس تُسعد الطفل، وتُريح من يشتريها",
                        "text": "متجر ملابس أطفال مصري، وفكرتنا واحدة: راحة الطفل تعني اطمئنان الأم. نختار كل قطعة بأيدينا ونجربها قبل ظهورها في الفروع، والكتالوج الكامل وأسعاره متاحة لكل عملائنا.",
                        "image_side": "left",
                    },
                ),
                TemplateSection(
                    type="steps",
                    props={
                        "eyebrow": "طريقة الشراء",
                        "heading": "من المقاس إلى المنزل في ٣ خطوات",
                        "text": "تختار القطعة اللي تعجبك، تكلمنا أو تمر على الفرع، وطلبك يوصلك لحد باب البيت.",
                        "items": [
                            {
                                "title": "اختار المقاس بالعمر",
                                "text": "كل قطعة مكتوب عليها المدى العمري والمقاس بالسنتيمتر، فتختار من أول مرة.",
                            },
                            {
                                "title": "كلمنا أو امشي للفرع",
                                "text": "فريقنا بيرد على واتساب، وفروعنا في القاهرة والجيزة جاهزة تستقبلك وتساعدك في القياس.",
                            },
                            {
                                "title": "اطلب واستلم",
                                "text": "توصيل إلى كل المحافظات خلال ٤٨ ساعة، والاستبدال خلال ١٤ يومًا من الاستلام.",
                            },
                        ],
                    },
                ),
                TemplateSection(
                    type="cta",
                    props={
                        "heading": "محتاج مساعدة في الاختيار؟",
                        "subheading": "كلمنا على واتساب ونساعدك تختار المقاس المناسب لطفلك",
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
                        "title": "العروض والكولكشنز",
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
                                "q": "إزاي أعرف المقاس المناسب؟",
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
