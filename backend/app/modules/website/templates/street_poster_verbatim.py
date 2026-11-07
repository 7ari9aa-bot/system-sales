"""Street-poster VERBATIM rendering — the poster restyle (v4 source) — the design ported 1:1 from the Base44
app source (v2), at the merchant's explicit requirement: the emitted markup
is their exact Tailwind DOM (same classes, same structure), their lucide
icons inline with the exact source paths, and their real images hotlinked
from media.base44.com. The stylesheet is THEIR tailwind.config build
compiled against this markup — never a hand approximation.
"""

from __future__ import annotations

from datetime import UTC, datetime

_LUCIDE = _LUCIDE = {
    "smile": (
        ("circle", {"cx": "12", "cy": "12", "r": "10", "key": "1mglay"}),
        ("path", {"d": "M8 14s1.5 2 4 2 4-2 4-2", "key": "1y1vjs"}),
        ("line", {"x1": "9", "x2": "9.01", "y1": "9", "y2": "9", "key": "yxxnd0"}),
        ("line", {"x1": "15", "x2": "15.01", "y1": "9", "y2": "9", "key": "1p4y9e"}),
    ),
    "chevron-down": (("path", {"d": "m6 9 6 6 6-6", "key": "qrunsl"})),
    "check": (("path", {"d": "M20 6 9 17l-5-5", "key": "1gmf2c"})),
    "heart": (
        (
            "path",
            {
                "d": "M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z",
                "key": "c3ymky",
            },
        )
    ),
    "sparkles": (
        (
            "path",
            {
                "d": "M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z",
                "key": "4pj2yx",
            },
        ),
        ("path", {"d": "M20 3v4", "key": "1olli1"}),
        ("path", {"d": "M22 5h-4", "key": "1gvqau"}),
        ("path", {"d": "M4 17v2", "key": "vumght"}),
        ("path", {"d": "M5 18H3", "key": "zchphs"}),
    ),
    "leaf": (
        (
            "path",
            {
                "d": "M11 20A7 7 0 0 1 9.8 6.1C15.5 5 17 4.48 19 2c1 2 2 4.18 2 8 0 5.5-4.78 10-10 10Z",
                "key": "nnexq3",
            },
        ),
        ("path", {"d": "M2 21c0-3 1.85-5.36 5.08-6C9.5 14.52 12 13 13 12", "key": "mt58a7"}),
    ),
    "ruler": (
        (
            "path",
            {
                "d": "M21.3 15.3a2.4 2.4 0 0 1 0 3.4l-2.6 2.6a2.4 2.4 0 0 1-3.4 0L2.7 8.7a2.41 2.41 0 0 1 0-3.4l2.6-2.6a2.41 2.41 0 0 1 3.4 0Z",
                "key": "icamh8",
            },
        ),
        ("path", {"d": "m14.5 12.5 2-2", "key": "inckbg"}),
        ("path", {"d": "m11.5 9.5 2-2", "key": "fmmyf7"}),
        ("path", {"d": "m8.5 6.5 2-2", "key": "vc6u1g"}),
        ("path", {"d": "m17.5 15.5 2-2", "key": "wo5hmg"}),
    ),
    "truck": (
        (
            "path",
            {"d": "M14 18V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v11a1 1 0 0 0 1 1h2", "key": "wrbu53"},
        ),
        ("path", {"d": "M15 18H9", "key": "1lyqi6"}),
        (
            "path",
            {
                "d": "M19 18h2a1 1 0 0 0 1-1v-3.65a1 1 0 0 0-.22-.624l-3.48-4.35A1 1 0 0 0 17.52 8H14",
                "key": "lysw3i",
            },
        ),
        ("circle", {"cx": "17", "cy": "18", "r": "2", "key": "332jqn"}),
        ("circle", {"cx": "7", "cy": "18", "r": "2", "key": "19iecd"}),
    ),
    "arrow-left": (
        ("path", {"d": "m12 19-7-7 7-7", "key": "1l729n"}),
        ("path", {"d": "M19 12H5", "key": "x3x0zl"}),
    ),
    "arrow-up-left": (
        ("path", {"d": "M7 17V7h10", "key": "11bw93"}),
        ("path", {"d": "M17 17 7 7", "key": "2786uv"}),
    ),
    "arrow-up-right": (
        ("path", {"d": "M7 7h10v10", "key": "1tivn9"}),
        ("path", {"d": "M7 17 17 7", "key": "1vkiza"}),
    ),
    "star": (
        (
            "path",
            {
                "d": "M11.525 2.295a.53.53 0 0 1 .95 0l2.31 4.679a2.123 2.123 0 0 0 1.595 1.16l5.166.756a.53.53 0 0 1 .294.904l-3.736 3.638a2.123 2.123 0 0 0-.611 1.878l.882 5.14a.53.53 0 0 1-.771.56l-4.618-2.428a2.122 2.122 0 0 0-1.973 0L6.396 21.01a.53.53 0 0 1-.77-.56l.881-5.139a2.122 2.122 0 0 0-.611-1.879L2.16 9.795a.53.53 0 0 1 .294-.906l5.165-.755a2.122 2.122 0 0 0 1.597-1.16z",
                "key": "r04s7s",
            },
        )
    ),
    "user-plus": (
        ("path", {"d": "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2", "key": "1yyitq"}),
        ("circle", {"cx": "9", "cy": "7", "r": "4", "key": "nufk8"}),
        ("line", {"x1": "19", "x2": "19", "y1": "8", "y2": "14", "key": "1bvyxn"}),
        ("line", {"x1": "22", "x2": "16", "y1": "11", "y2": "11", "key": "1shjgl"}),
    ),
    "package-check": (
        ("path", {"d": "m16 16 2 2 4-4", "key": "gfu2re"}),
        (
            "path",
            {
                "d": "M21 10V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l2-1.14",
                "key": "e7tb2h",
            },
        ),
        ("path", {"d": "m7.5 4.27 9 5.15", "key": "1c824w"}),
        ("polyline", {"points": "3.29 7 12 12 20.71 7", "key": "ousv84"}),
        ("line", {"x1": "12", "x2": "12", "y1": "22", "y2": "12", "key": "a4e8g8"}),
    ),
    "phone": (
        (
            "path",
            {
                "d": "M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z",
                "key": "foiqr5",
            },
        )
    ),
    "message-circle": (("path", {"d": "M7.9 20A9 9 0 1 0 4 16.1L2 22Z", "key": "vv11sd"})),
    "mail": (
        ("rect", {"width": "20", "height": "16", "x": "2", "y": "4", "rx": "2", "key": "18n3k1"}),
        ("path", {"d": "m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7", "key": "1ocrg3"}),
    ),
    "map-pin": (
        (
            "path",
            {
                "d": "M20 10c0 4.993-5.539 10.193-7.399 11.799a1 1 0 0 1-1.202 0C9.539 20.193 4 14.993 4 10a8 8 0 0 1 16 0",
                "key": "1r0f0z",
            },
        ),
        ("circle", {"cx": "12", "cy": "10", "r": "3", "key": "ilqhr7"}),
    ),
    "clock": (
        ("circle", {"cx": "12", "cy": "12", "r": "10", "key": "1mglay"}),
        ("polyline", {"points": "12 6 12 12 16 14", "key": "68esgv"}),
    ),
    "store": (
        (
            "path",
            {"d": "m2 7 4.41-4.41A2 2 0 0 1 7.83 2h8.34a2 2 0 0 1 1.42.59L22 7", "key": "ztvudi"},
        ),
        ("path", {"d": "M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8", "key": "1b2hhj"}),
        ("path", {"d": "M15 22v-4a2 2 0 0 0-2-2h-2a2 2 0 0 0-2 2v4", "key": "2ebpfo"}),
        ("path", {"d": "M2 7h20", "key": "1fcdvo"}),
        (
            "path",
            {
                "d": "M22 7v3a2 2 0 0 1-2 2a2.7 2.7 0 0 1-1.59-.63.7.7 0 0 0-.82 0A2.7 2.7 0 0 1 16 12a2.7 2.7 0 0 1-1.59-.63.7.7 0 0 0-.82 0A2.7 2.7 0 0 1 12 12a2.7 2.7 0 0 1-1.59-.63.7.7 0 0 0-.82 0A2.7 2.7 0 0 1 8 12a2.7 2.7 0 0 1-1.59-.63.7.7 0 0 0-.82 0A2.7 2.7 0 0 1 4 12a2 2 0 0 1-2-2V7",
                "key": "6c3vgh",
            },
        ),
    ),
    "navigation": (("polygon", {"points": "3 11 22 2 13 21 11 13 3 11", "key": "1ltx0t"})),
    "facebook": (
        (
            "path",
            {
                "d": "M18 2h-3a5 5 0 0 0-5 5v3H7v4h3v8h4v-8h3l1-4h-4V7a1 1 0 0 1 1-1h3z",
                "key": "1jg4f8",
            },
        )
    ),
    "instagram": (
        (
            "rect",
            {
                "width": "20",
                "height": "20",
                "x": "2",
                "y": "2",
                "rx": "5",
                "ry": "5",
                "key": "2e1cvw",
            },
        ),
        ("path", {"d": "M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z", "key": "9exkf1"}),
        ("line", {"x1": "17.5", "x2": "17.51", "y1": "6.5", "y2": "6.5", "key": "r4j83e"}),
    ),
    "music-2": (
        ("circle", {"cx": "8", "cy": "18", "r": "4", "key": "1fc0mg"}),
        ("path", {"d": "M12 18V2l7 4", "key": "g04rme"}),
    ),
    "youtube": (
        (
            "path",
            {
                "d": "M2.5 17a24.12 24.12 0 0 1 0-10 2 2 0 0 1 1.4-1.4 49.56 49.56 0 0 1 16.2 0A2 2 0 0 1 21.5 7a24.12 24.12 0 0 1 0 10 2 2 0 0 1-1.4 1.4 49.55 49.55 0 0 1-16.2 0A2 2 0 0 1 2.5 17",
                "key": "1q2vi4",
            },
        ),
        ("path", {"d": "m10 15 5-3-5-3z", "key": "1jp15x"}),
    ),
    "external-link": (
        ("path", {"d": "M15 3h6v6", "key": "1q9fwt"}),
        ("path", {"d": "M10 14 21 3", "key": "gplh6r"}),
        (
            "path",
            {"d": "M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6", "key": "a6xqqp"},
        ),
    ),
    "menu": (
        ("line", {"x1": "4", "x2": "20", "y1": "12", "y2": "12", "key": "1e0a9i"}),
        ("line", {"x1": "4", "x2": "20", "y1": "6", "y2": "6", "key": "1owob3"}),
        ("line", {"x1": "4", "x2": "20", "y1": "18", "y2": "18", "key": "yk5zj1"}),
    ),
    "x": (
        ("path", {"d": "M18 6 6 18", "key": "1bl5f8"}),
        ("path", {"d": "m6 6 12 12", "key": "d8bk6v"}),
    ),
    "send": (
        (
            "path",
            {
                "d": "M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z",
                "key": "1ffxy3",
            },
        ),
        ("path", {"d": "m21.854 2.147-10.94 10.939", "key": "12cjpa"}),
    ),
    "globe": (
        ("circle", {"cx": "12", "cy": "12", "r": "10", "key": "1mglay"}),
        ("path", {"d": "M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20", "key": "13o1zl"}),
        ("path", {"d": "M2 12h20", "key": "9i4pu4"}),
    ),
}


def _e(value):
    from html import escape

    return escape(str(value)) if value not in (None, "") else ""


def _icon(name: str, cls: str = "h-4 w-4") -> str:
    """An inline lucide SVG with the exact source paths."""
    nodes = _LUCIDE.get(name)
    if not nodes:
        return ""
    # The generated literal is a tuple of (tag, attrs) pairs -- but a
    # single-element icon collapses to one bare pair, so normalize.
    if isinstance(nodes[0], str):
        nodes = (nodes,)
    parts = "".join(
        "<" + tag + " " + " ".join(f'{k}="{v}"' for k, v in props.items()) + "></" + tag + ">"
        for tag, props in nodes
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" '
        'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        f'stroke-linejoin="round" class="{cls}">{parts}</svg>'
    )


# The preview-walk prefix ("/sites/preview/<id>" or the /api/v1 absolute
# base). None = a published single-document site, where "#page-" anchors
# apply. Set by the preview service before rendering.
_WALK_PREFIX: str | None = None


def set_walk_prefix(prefix: str | None) -> None:
    global _WALK_PREFIX
    _WALK_PREFIX = prefix


def _page_url(slug: str) -> str:
    if _WALK_PREFIX:
        return f"{_WALK_PREFIX}/{slug}"
    return f"#page-{slug}"


BRAND = {
    "name": "Funny Baby",
    "tagline": "ملابس رجالي · القاهرة",
    "phone": "0100 000 0000",
    "whatsapp": "https://wa.me/201000000000",
    "email": "hello@funnybaby.eg",
    "open_hour": 11,
    "close_hour": 22,
    "stage_image": "https://media.base44.com/images/public/6aecd4bc3ec0205e24ad1a44/d096a9b47_generated_image.png",
    "stage_second": "https://media.base44.com/images/public/6aecd4bc3ec0205e24ad1a44/974e16c18_generated_image.png",
    "chap_catalog": "https://media.base44.com/images/public/6aecd4bc3ec0205e24ad1a44/974e16c18_generated_image.png",
    "chap_stores": "https://media.base44.com/images/public/6aecd4bc3ec0205e24ad1a44/982b85299_generated_image.png",
    "chap_offers": "https://media.base44.com/images/public/6aecd4bc3ec0205e24ad1a44/753f5bed6_generated_image.png",
    "chap_care": "https://media.base44.com/images/public/6aecd4bc3ec0205e24ad1a44/9ed38ba5a_generated_image.png",
    "atelier_image": "https://media.base44.com/images/public/6aecd4bc3ec0205e24ad1a44/d10778e87_generated_image.png",
}

TICKER = [
    "توصيل لكل المحافظات",
    "استبدال حتى ١٤ يومًا",
    "مقاسات مكتوبة بالسنتيمتر",
    "قمصان وتيشيرتات وبناطيل",
    "فروع في القاهرة والجيزة",
    "تغليف هدايا في الفرع",
]

PROMISES = [
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
]

BRANCHES = [
    {
        "name": "المعادي",
        "governorate": "القاهرة",
        "address": "٣٧ شارع ٩، المعادي، القاهرة",
        "phone": "0100 000 0001",
        "hours": "١١ ص – ١٠ م",
        "note": "أكبر فرع — ركن لعب للأطفال",
    },
    {
        "name": "مدينة نصر",
        "governorate": "القاهرة",
        "address": "٥ شارع عباس العقاد، مدينة نصر، القاهرة",
        "phone": "0100 000 0002",
        "hours": "١٢ م – ١٠ م",
        "note": "خدمة تغليف الهدايا",
    },
    {
        "name": "الشيخ زايد",
        "governorate": "الجيزة",
        "address": "داون تاون مول، الدور الأول، الشيخ زايد",
        "phone": "0100 000 0003",
        "hours": "١٢ م – ١١ م",
        "note": "استبدال خلال ١٤ يوم",
    },
]

SOCIAL = [
    {
        "platform": "instagram",
        "handle": "@funnybaby.eg",
        "href": "https://instagram.com/funnybaby.eg",
    },
    {"platform": "facebook", "handle": "Funny Baby", "href": "https://facebook.com/funnybaby.eg"},
    {"platform": "tiktok", "handle": "@funnybaby.eg", "href": "https://tiktok.com/@funnybaby.eg"},
]

PRIMARY_NAV = [
    {"label": "الرئيسية", "slug": "home"},
    {"label": "العروض", "slug": "offers"},
    {"label": "الفروع", "slug": "stores"},
    {"label": "الأسئلة الشائعة", "slug": "faq"},
]

FOOTER_COLUMNS = [
    {
        "title": "المتجر",
        "links": [
            {"label": "الرئيسية", "slug": "home"},
            {"label": "الفروع والتواصل", "slug": "stores"},
            {"label": "العروض والكولكشنز", "slug": "offers"},
        ],
    },
    {
        "title": "خدمة العملاء",
        "links": [
            {"label": "الأسئلة الشائعة", "slug": "faq"},
            {"label": "الشحن والتوصيل", "slug": "shipping"},
            {"label": "الاستبدال والاسترجاع", "slug": "exchange-return"},
            {"label": "تتبع الطلب", "slug": "track-order"},
        ],
    },
    {
        "title": "المحل والسياسات",
        "links": [
            {"label": "سياسة الخصوصية", "slug": "privacy"},
            {"label": "الشروط والأحكام", "slug": "terms"},
        ],
    },
]

FAQ_ITEMS = [
    {
        "q": "إزاي أعرف المقاس المناسب لطفلي؟",
        "a": "كل قطعة مكتوب عليها المقاس بالسنتيمتر والمدى العمري. ولو لسه محتار، قيس القطعة اللي بيلبسها ومريحة وقارنها بالجدول المكتوب على صفحة المنتج.",
    },
    {
        "q": "بتوصلوا لكل المحافظات؟",
        "a": "أيوه، نشحن من فروعنا إلى كل محافظات مصر خلال ٤٨ ساعة تقريبًا، ومصاريف الشحن بتظهر عند إتمام الطلب.",
    },
    {
        "q": "أقدر أستبدل المقاس؟",
        "a": "استبدال المقاس أو اللون متاح خلال ١٤ يوم من الاستلام، من أي فرع أو أونلاين بشرط أن القطعة بحالتها وبملصقاتها.",
    },
    {
        "q": "طرق الدفع المتاحة؟",
        "a": "الدفع عند الاستلام أو تحويل قبل الشحن — كل الطرق المعمول بيها موجودة في صفحة طرق الدفع، وأي طريقة لم تُفعل بعد مكتوب عليها صراحة.",
    },
    {
        "q": "كيف أتابع طلبي؟",
        "a": "من صفحة تتبع الطلب، اكتب رقم الطلب وسترى حالته الحالية وتاريخ إنشائه.",
    },
    {
        "q": "هل تتعاملون بالجملة؟",
        "a": "نعم، هناك صفحة مخصصة للبيع بالجملة تتضمن طريقة التواصل والبيانات المطلوبة منك.",
    },
]


def _open_now() -> bool:
    hour = (datetime.now(UTC).hour + 2) % 24  # Africa/Cairo ≈ UTC+2
    return BRAND["open_hour"] <= hour < BRAND["close_hour"]


def _open_status(inverted: bool = False) -> str:
    open_now = _open_now()
    tone = (
        ("bg-background/15 text-background" if open_now else "bg-background/8 text-background/50")
        if inverted
        else ("bg-primary/10 text-primary" if open_now else "bg-muted text-muted-foreground")
    )
    dot = (
        ("bg-background" if open_now else "bg-background/40")
        if inverted
        else ("bg-primary" if open_now else "bg-muted-foreground/60")
    )
    label = "مفتوح الآن" if open_now else "مغلق الآن"
    return (
        f'<span class="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 '
        f'text-[11px] font-medium {tone}"><span class="h-1.5 w-1.5 rounded-full {dot}"></span>'
        f"{label}</span>"
    )


def _site_header(prefix: str, active_slug: str) -> str:
    def nav_link(slug, label):
        url = prefix if slug == "home" else f"{prefix}/{slug}"
        active_cls = (
            "bg-accent font-bold text-accent-foreground"
            if slug == active_slug
            else "text-muted-foreground hover:bg-secondary hover:text-secondary-foreground"
        )
        return f'<a href="{url}" class="rounded-full px-3 py-1.5 text-sm transition-colors {active_cls}">{label}</a>'

    links = "".join(nav_link(n["slug"], n["label"]) for n in PRIMARY_NAV)
    groups = ""
    for group in FOOTER_COLUMNS:
        items = "".join(
            f'<a href="{prefix}/{link["slug"]}" class="cursor-pointer rounded-md px-2 py-1.5 '
            f'text-sm text-foreground/80 hover:bg-secondary block">{link["label"]}</a>'
            for link in group["links"]
        )
        groups += (
            f'<div><p class="mb-1.5 px-2 text-[11px] font-medium text-muted-foreground">'
            f"{group['title']}</p>{items}</div>"
        )
    return (
        '<header class="sticky top-0 z-50 border-b border-border/70 bg-background/85 backdrop-blur-xl">'
        '<div class="mx-auto flex h-[78px] w-full max-w-7xl items-center justify-between gap-4 px-5 sm:px-8">'
        f'<a href="{prefix}" class="flex shrink-0 items-center gap-2.5">'
        '<span class="flex h-10 w-10 -rotate-6 items-center justify-center rounded-2xl bg-primary '
        'text-primary-foreground shadow-[3px_3px_0_0_hsl(var(--accent))]" style="transform:rotate(-6deg)">'
        f"{_icon('smile', 'h-5 w-5')}</span>"
        '<span class="leading-none"><span class="block font-heading text-xl font-extrabold '
        f'text-foreground">{BRAND["name"]}</span>'
        f'<span class="mt-0.5 block text-[11px] text-muted-foreground">{BRAND["tagline"]}</span></span></a>'
        f'<nav class="hidden items-center gap-7 lg:flex">{links}'
        '<div class="group relative inline-block">'
        '<button class="inline-flex items-center gap-1 text-sm transition-colors hover:text-foreground '
        f'text-muted-foreground">المزيد{_icon("chevron-down", "h-3.5 w-3.5")}</button>'
        '<div class="invisible absolute end-0 top-full z-50 mt-1 w-[34rem] rounded-lg border '
        "border-border bg-popover p-4 opacity-0 shadow-lg transition-all group-hover:visible "
        f'group-hover:opacity-100"><div class="grid grid-cols-3 gap-x-4 gap-y-1">{groups}</div></div>'
        "</div></nav>"
        '<div class="hidden items-center gap-2 sm:flex">'
        f'<a href="{prefix}/stores" class="inline-flex items-center justify-center gap-2 '
        "whitespace-nowrap rounded-full text-sm font-medium transition-colors bg-primary "
        'text-primary-foreground shadow hover:bg-primary/90 px-5 py-2">زيارة الفرع</a></div>'
        "</div></header>"
    )


def _site_footer(prefix: str) -> str:
    columns = ""
    for column in FOOTER_COLUMNS:
        links = "".join(
            f'<li><a href="{prefix}/{link["slug"]}" class="text-background/65 transition-colors '
            f'hover:text-background">{link["label"]}</a></li>'
            for link in column["links"]
        )
        columns += (
            f'<div><h3 class="font-heading text-sm font-bold text-accent">{column["title"]}</h3>'
            f'<ul class="mt-4 space-y-2.5">{links}</ul></div>'
        )
    social = "".join(
        f'<a href="{_e(s["href"])}" target="_blank" rel="noreferrer" class="flex items-center '
        'gap-2 text-background/65 transition-colors hover:text-background">'
        f"{_icon(s['platform'], 'h-4 w-4')}{_e(s['handle'])}</a>"
        for s in SOCIAL
    )
    branches_line = " · ".join(b["name"] for b in BRANCHES)
    contact = (
        '<div class="rounded-3xl border border-background/15 bg-background/5 p-5">'
        '<h3 class="font-heading text-sm font-bold text-accent">تواصل معنا</h3>'
        '<ul class="mt-4 space-y-3 text-background/65">'
        f'<li><a href="tel:{BRAND["phone"].replace(" ", "")}" class="flex items-center gap-2.5 '
        'transition-colors hover:text-background">'
        f'{_icon("phone", "h-4 w-4 shrink-0")}<span dir="ltr">{BRAND["phone"]}</span></a></li>'
        f'<li><a href="{BRAND["whatsapp"]}" target="_blank" rel="noreferrer" class="flex '
        'items-center gap-2.5 transition-colors hover:text-background">'
        f"{_icon('message-circle', 'h-4 w-4 shrink-0')}واتساب المحل</a></li>"
        f'<li><a href="mailto:{BRAND["email"]}" class="flex items-center gap-2.5 transition-colors '
        f'hover:text-background">{_icon("mail", "h-4 w-4 shrink-0")}<span dir="ltr">{BRAND["email"]}</span></a></li>'
        '<li class="flex items-start gap-2.5">'
        f"{_icon('map-pin', 'mt-0.5 h-4 w-4 shrink-0')}<span>{branches_line}</span></li></ul>"
        f'<div class="mt-4">{_open_status(inverted=True)}</div></div>'
    )
    return (
        '<footer class="bg-foreground text-background">'
        '<div aria-hidden="true" class="flex h-1.5 w-full">'
        '<span class="h-full flex-1 bg-primary"></span>'
        '<span class="h-full flex-1 bg-accent"></span>'
        '<span class="h-full flex-1 bg-[#2a9d8f]"></span></div>'
        '<div class="mx-auto w-full max-w-6xl px-5 pb-10 pt-14 sm:px-8 sm:pt-16">'
        '<div class="flex flex-col items-center text-center">'
        '<span class="flex h-12 w-12 items-center justify-center rounded-2xl bg-primary '
        'text-primary-foreground shadow-[4px_4px_0_0_hsl(var(--accent))]" style="transform:rotate(-6deg)">'
        f"{_icon('smile', 'h-6 w-6')}</span>"
        f'<p class="mt-4 font-heading text-3xl font-extrabold leading-none sm:text-4xl">{BRAND["name"]}</p></div>'
        '<div class="mt-12 h-px w-full bg-background/15"></div>'
        f'<div class="mt-10 grid gap-10 text-sm lg:grid-cols-[1fr_1fr_1fr_1.1fr]">{columns}{contact}</div>'
        f'<div class="mt-8 flex flex-wrap items-center justify-center gap-4">{social}</div>'
        "</div></footer>"
    )


def _floating_whatsapp() -> str:
    return (
        f'<a href="{BRAND["whatsapp"]}" target="_blank" rel="noreferrer" aria-label="تواصل واتساب" '
        'class="fixed bottom-5 end-5 z-50 flex h-14 w-14 items-center justify-center rounded-full '
        "bg-[#25D366] text-white shadow-[0_10px_30px_-10px_rgba(0,0,0,.4)] transition-transform "
        f'hover:scale-105">{_icon("message-circle", "h-6 w-6")}</a>'
    )


def _product_card(p) -> str:
    return (
        '<div class="group flex flex-col overflow-hidden rounded-2xl border border-border bg-card '
        "transition-all duration-300 hover:-translate-y-0.5 hover:border-primary/40 "
        'hover:shadow-[0_24px_45px_-32px_hsl(var(--foreground)/0.55)]">'
        '<div class="relative aspect-[4/5] overflow-hidden bg-secondary/60">'
        f'<img src="{_e(p.get("image") or "")}" alt="{_e(p.get("title"))}" '
        'class="h-full w-full object-contain p-3 transition-transform duration-700 ease-out '
        'group-hover:scale-[1.05]"></div>'
        '<div class="flex flex-1 flex-col gap-2 p-3.5 sm:p-4">'
        f'<h3 class="line-clamp-2 font-heading text-[15px] leading-snug text-foreground">'
        f"{_e(p.get('title'))}</h3>"
        '<div class="mt-auto flex items-end justify-between gap-2 pt-2"><div class="min-w-0">'
        f'<span class="font-heading text-[15px] text-foreground">{_e(p.get("price"))}</span></div>'
        '<span class="shrink-0 rounded-full bg-secondary px-2 py-0.5 text-[10px] '
        'text-foreground/70">متاح</span></div></div></div>'
    )


def _product_grid_section(props, products) -> str:
    title = (props or {}).get("title")
    title_html = (
        f'<h2 class="font-heading text-2xl font-extrabold text-foreground mb-4">{_e(title)}</h2>'
        if title
        else ""
    )
    cards = "".join(_product_card(p) for p in products)
    return (
        '<section class="py-10"><div class="mx-auto w-full max-w-6xl px-5 sm:px-8">'
        f'{title_html}<div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{cards}</div>'
        "</div></section>"
    )


def _branch_card(b) -> str:
    digits = str(b.get("phone", "")).replace(" ", "").replace("-", "")
    wa = "https://wa.me/" + ("2" + digits if digits.startswith("0") else digits)
    return (
        '<article class="flex flex-col overflow-hidden rounded-2xl border border-border bg-card">'
        '<div class="relative aspect-[16/10] w-full bg-secondary">'
        '<div class="flex h-full w-full flex-col items-center justify-center gap-1.5 border-b '
        'border-dashed border-border bg-secondary/50 text-muted-foreground">'
        f'{_icon("store", "h-6 w-6 text-primary/60")}<p class="text-xs">صورة الواجهة لم تُضف بعد</p>'
        "</div></div>"
        '<div class="flex flex-1 flex-col gap-3 p-5">'
        '<div class="flex items-start justify-between gap-3"><div>'
        f'<h3 class="font-heading text-xl text-foreground">{_e(b.get("name", ""))}</h3>'
        f'<p class="mt-0.5 text-xs text-muted-foreground">{_e(b.get("governorate", ""))}</p></div>'
        f"{_open_status()}</div>"
        '<p class="flex items-start gap-2 text-sm leading-7 text-muted-foreground">'
        f"{_icon('map-pin', 'mt-1.5 h-4 w-4 shrink-0 text-primary')}<span>{_e(b['address'])}"
        f'<span class="mt-1 block text-xs text-foreground/60">{_e(b.get("note"))}</span></span></p>'
        '<p class="flex items-start gap-2 text-sm text-muted-foreground">'
        f"{_icon('clock', 'mt-1 h-4 w-4 shrink-0 text-primary')}<span>{_e(b['hours'])}</span></p>"
        '<div class="mt-auto flex flex-wrap gap-2 pt-3">'
        f'<a href="tel:{digits}" class="inline-flex items-center justify-center gap-1.5 rounded-full '
        "border border-border px-3 py-2 text-xs text-foreground transition-colors hover:border-primary "
        f'hover:text-primary">{_icon("phone", "h-3.5 w-3.5")}<span dir="ltr">{_e(b.get("phone", ""))}</span></a>'
        f'<a href="{wa}" target="_blank" rel="noreferrer" class="inline-flex items-center '
        "justify-center gap-1.5 rounded-full bg-whatsapp px-3.5 py-2 text-xs font-medium "
        'text-whatsapp-foreground transition-colors hover:bg-whatsapp/90">'
        f"{_icon('message-circle', 'h-3.5 w-3.5')}واتساب</a>"
        f'<a href="https://www.google.com/maps/dir/?api=1&destination={_e(b.get("address", ""))}" '
        'target="_blank" rel="noreferrer" class="inline-flex items-center justify-center gap-1.5 '
        "rounded-full border border-border px-3 py-2 text-xs text-foreground transition-colors "
        f'hover:border-primary hover:text-primary">{_icon("navigation", "h-3.5 w-3.5")}الاتجاهات</a>'
        "</div></div></article>"
    )


def _faq_accordion(items) -> str:
    rows = "".join(
        f'<details class="border-b border-border"{" open" if i == 0 else ""}>'
        '<summary class="flex cursor-pointer items-center justify-between gap-3 py-5 text-start '
        f'font-heading text-base text-foreground">{_e(item["q"])}'
        f"{_icon('chevron-down', 'h-4 w-4 shrink-0 text-muted-foreground')}</summary>"
        f'<p class="pb-5 text-sm leading-8 text-muted-foreground">{_e(item["a"])}</p></details>'
        for i, item in enumerate(items)
    )
    return f'<div class="w-full">{rows}</div>'


def _page_hero(eyebrow: str, title: str, description: str) -> str:
    desc = (
        f'<p class="mt-4 max-w-2xl text-[15px] leading-8 text-muted-foreground sm:text-base">'
        f"{_e(description)}</p>"
        if description
        else ""
    )
    eb = f'<p class="eyebrow">{_e(eyebrow)}</p>' if eyebrow else ""
    return (
        '<section class="relative overflow-hidden border-b-2 border-foreground/10 bg-secondary/50">'
        '<div aria-hidden="true" class="pointer-events-none absolute -top-36 end-[-10%] h-80 w-80 '
        'rounded-full bg-accent/70 blur-3xl"></div>'
        '<div aria-hidden="true" class="pointer-events-none absolute bottom-[-40%] start-[-4%] h-64 '
        'w-64 rounded-full bg-primary/15 blur-3xl"></div>'
        '<div class="relative mx-auto w-full max-w-6xl px-5 py-14 sm:px-8 sm:py-20">'
        f'{eb}<h1 class="mt-3 max-w-3xl font-heading text-3xl font-extrabold leading-[1.2] '
        f'text-foreground sm:text-5xl">{_e(title)}</h1>{desc}</div></section>'
    )


def _home_stage() -> str:
    stats = [
        ("S – XXL", "المقاسات المتاحة"),
        ("٣", "فروع بالقاهرة والجيزة"),
        ("٤٨ س", "توصيل لكل المحافظات"),
    ]
    cells = "".join(
        f'<div class="st"><b>{_e(v)}</b><span>{_e(lbl)}</span></div>' for v, lbl in stats
    )
    return (
        '<section class="blk"><div class="hero"><div>'
        '<span class="eb">مجموعة الموسم ٢٠٢٦</span>'
        "<h1>ستايل هادي<br />يفرق في <span>إطلالتك</span></h1>"
        '<p class="lead">أقمشة مريحة وقصّات هادية ومقاسات مكتوبة بالسنتيمتر — قمصان '
        "وتيشيرتات وبناطيل وبدل، مع تغليف هدايا جاهز. الكتالوج كامل بمقاساته وأسعاره "
        "على الموقع.</p>"
        '<div class="btns">'
        '<a class="b b1" href="#page-products">ابدأ التسوق ←</a>'
        '<a class="b b2" href="#page-stores">زيارة الفروع ↗</a></div>'
        '<div class="gift">★ تغليف هدايا مجاني في الفروع — كل أيام الأسبوع</div>'
        '</div><div class="fr">'
        '<img class="fr-img" src="https://media.base44.com/images/public/'
        '6aecd4bc3ec0205e24ad1a44/b75a5343f_generated_0b98436c.jpg" '
        'alt="رجل بملابس عصرية هادئة"><span class="tag">✦ جديد كل أسبوع</span>'
        "</div></div></section>"
        f'<dl class="stats">{cells}</dl>'
    )


def _home_ticker() -> str:
    phrases = [
        "توصيل لكل المحافظات",
        "استبدال حتى ١٤ يومًا",
        "مقاسات مكتوبة بالسنتيمتر",
        "قمصان وتيشيرتات وبناطيل",
        "فروع في القاهرة والجيزة",
        "تغليف هدايا في الفرع",
    ]
    spans = "".join(f'<span>{_e(p)}<i aria-hidden="true">✳</i></span>' for p in phrases)
    return (
        '<section class="tick" aria-hidden="true"><div class="tk">'
        f'<div class="tg">{spans}</div><div class="tg">{spans}</div></div></section>'
    )


def _home_rows() -> str:
    chapters = [
        ("الكتالوج", "قمصان وبناطيل وبدل بأسعارها", "#page-products"),
        ("الفروع", "٣ فروع للزيارة والتجربة", "#page-stores"),
        ("العروض", "عروض الموسم وأكواد الخصم", "#page-offers"),
        ("العناية والتوصيل", "دليل العناية وسياسة الاستبدال", "#page-shipping"),
    ]
    head = (
        '<div class="sh"><div><span class="eb2">أقسام الموقع</span>'
        "<h2>ابدأ من الباب اللي يريحك</h2></div>"
        "<p>أربعة أبواب مختصرة: تسوّق، زور فرعًا، شوف العروض، أو اعرف كل حاجة عن "
        "العناية والتوصيل.</p></div>"
    )
    rows = "".join(
        f'<a class="row" href="{_e(href)}"><span class="n">{i + 1:02d}</span>'
        f"<h3>{_e(title)}<small>{_e(note)}</small></h3>"
        f'<span class="row-img" aria-hidden="true"></span></a>'
        for i, (title, note, href) in enumerate(chapters)
    )
    return f'<section class="sec">{head}<div class="rows">{rows}</div></section>'


def _home_pro() -> str:
    cols = "".join(
        f'<div class="col"><span class="pn">{i + 1:02d}</span>'
        f"<h3>{_e(p['title'])}</h3><p>{_e(p['text'])}</p>"
        "<span>مضمون</span></div>"
        for i, p in enumerate(PROMISES)
    )
    return (
        '<section class="pro"><div class="sh"><div>'
        '<span class="eb2">وعدنا لك</span>'
        "<h2>لا نعرض قطعة <em>لم نقتنع بها.</em></h2></div></div>"
        '<p class="ld">نختار القليل ونشرحه جيدًا: الخامة، المقاس، وطريقة العناية. '
        "حتى تصلك القطعة كما توقعتها.</p>"
        f'<div class="cols">{cols}</div></section>'
    )


def _home_path() -> str:
    steps = [
        (
            "user-plus",
            "أنشئ حسابك",
            "تسجيل الدخول يفتح الكتالوج الكامل بالأسعار والمقاسات المتاحة.",
        ),
        ("ruler", "اختر بدقة", "كل قطعة مكتوب عليها المقاس بالسنتيمتر إلى جانب المدى العمري."),
        ("package-check", "استلم وتابع", "توصيل لكل المحافظات، ومتابعة الطلب برقمه في أي وقت."),
    ]
    items = "".join(
        f'<div class="sp"><div class="big">{i + 1:02d}</div>'
        f"{_icon(ic, 'h-[34px] w-[34px] text-[#f2f0e9]')}"
        f"<h3>{title}</h3><p>{text}</p></div>"
        for i, (ic, title, text) in enumerate(steps)
    )
    return (
        '<section class="path"><div class="top"><div>'
        '<span class="eb2">مسار الشراء</span><h2>ثلاث خطوات، بلا مفاجآت</h2></div>'
        '<a class="b b4" href="#page-products">ابدأ الآن ←</a></div>'
        f'<div class="steps">{items}</div></section>'
    )


def render_section_street_poster(kind: str, props: dict, ctx) -> str:
    """Dispatch our section kinds to THEIR poster components."""
    props = props or {}
    if kind == "hero":
        return _home_stage() + _home_ticker()
    if kind == "features":
        items = props.get("items") or []
        if any(item.get("href") for item in items):
            return _home_rows()
        return _home_pro()
    if kind == "manifesto":
        return _home_pro()
    if kind == "steps":
        return _home_path()
    if kind == "product_grid":
        collection = str(props.get("collection_id") or "")
        products = ctx.products_by_collection.get(collection, [])
        return _product_grid_section(props, products)
    if kind == "branches":
        items = props.get("items") or BRANCHES
        cards = "".join(_branch_card(b) for b in items)
        return (
            '<section class="sec"><div class="grid gap-5 md:grid-cols-2 lg:grid-cols-3">'
            f"{cards}</div></div></section>"
        )
    if kind == "faq":
        return (
            '<section class="py-10"><div class="mx-auto w-full max-w-4xl px-5 sm:px-8">'
            f"{_faq_accordion(props.get('items') or FAQ_ITEMS)}</div></section>"
        )
    if kind == "rich_text":
        return (
            '<section class="py-10"><div class="mx-auto w-full max-w-4xl px-5 sm:px-8 text-[15px] '
            f'leading-8 text-muted-foreground space-y-4">{_e(props.get("content"))}</div></section>'
        )
    if kind == "cta":
        url = props.get("button_url") or "#page-products"
        return (
            '<section class="py-14"><div class="mx-auto w-full max-w-4xl px-5 sm:px-8 text-center">'
            f'<h2 class="font-heading text-3xl font-extrabold">{_e(props.get("heading"))}</h2>'
            f'<a class="b b1 mt-6 inline-block" href="{_e(url)}">'
            f"{_e(props.get('button_label'))}</a></div></section>"
        )
    return ""


def _template_css() -> str:
    from app.modules.website.templates import catalog

    try:
        return catalog.get("funny-baby").css
    except Exception:  # noqa: BLE001 - degrade, never 500 a live site
        return ""


def render_shell_street_poster(
    *,
    body: str,
    title: str,
    page_slug: str | None = None,
    page_url_prefix: str | None = None,
    banner_html: str | None = None,
    site_slug: str | None = None,
    **_ignored,
) -> str:
    prefix = page_url_prefix or (f"/sites/{site_slug}" if site_slug else "/")
    active = page_slug or "home"
    css = _template_css()
    banner = banner_html or ""
    return (
        "<!doctype html>"
        '<html dir="rtl" lang="ar">'
        f'<head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_e(title)}</title>"
        f"<style>{css}</style></head>"
        f'<body class="site-body bg-background text-foreground font-body antialiased">{banner}'
        f"{_site_header(prefix, active)}<main>{body}</main>{_site_footer(prefix)}"
        f"{_floating_whatsapp()}</body></html>"
    )


def _template_css() -> str:
    from app.modules.website.templates import catalog

    try:
        return catalog.get("warm-paper").css
    except Exception:  # noqa: BLE001
        return ""
