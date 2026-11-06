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
from pathlib import Path

from app.modules.website.templates.catalog import (
    TemplateManifest,
    TemplatePage,
    TemplateSection,
)

CSS = (Path(__file__).parent / "funny_baby.css").read_text(encoding="utf-8")


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
