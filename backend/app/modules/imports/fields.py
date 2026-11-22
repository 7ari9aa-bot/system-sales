"""The fields a merchant can import, with the header spellings we recognise for each.

One table drives both the automatic column matching and the template generator, so the two
cannot disagree about what a column is called. Synonyms are matched after ``normalize_header``
(case, spaces, punctuation and Arabic diacritics/letter variants removed).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FieldSpec:
    key: str
    label_ar: str
    label_en: str
    synonyms: tuple[str, ...]
    required: bool = False


# Sheet names are part of the template contract: Products / Variants / Opening Stock / Images.
SHEET_PRODUCTS = "Products"
SHEET_VARIANTS = "Variants"
SHEET_STOCK = "Opening Stock"
SHEET_IMAGES = "Images"
SHEET_ITEM_CODES = "Item Codes"

PRODUCT_FIELDS: tuple[FieldSpec, ...] = (
    # Optional here: a one-sheet file of names and prices is what most shops have, and the
    # validator derives the handle from the name (and refuses two names that collapse to one).
    # On the Variants sheet it stays required: a variant has to say which product it belongs to.
    FieldSpec(
        "product_ref",
        "معرّف المنتج",
        "Product ref",
        ("productref", "productid", "handle", "slug", "parentsku", "معرفالمنتج", "كودالمنتج"),
    ),
    FieldSpec(
        "title",
        "اسم المنتج",
        "Product name",
        ("title", "name", "productname", "producttitle", "اسمالمنتج", "الاسم", "المنتج", "الصنف"),
        required=True,
    ),
    FieldSpec(
        "category", "التصنيف", "Category", ("category", "type", "producttype", "التصنيف", "القسم")
    ),
    FieldSpec("brand", "الماركة", "Brand", ("brand", "vendor", "الماركة", "العلامةالتجارية")),
    FieldSpec(
        "description", "الوصف", "Description", ("description", "body", "details", "الوصف", "تفاصيل")
    ),
    FieldSpec(
        "season",
        "الموسم",
        "Season",
        ("season", "collection", "موسم", "الموسم", "المجموعة"),
    ),
    FieldSpec(
        "material",
        "الخامة",
        "Material",
        ("material", "fabric", "composition", "خامة", "الخامة", "القماش", "نوعالقماش"),
    ),
    FieldSpec("status", "الحالة", "Status", ("status", "state", "الحالة")),
)

VARIANT_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(
        "product_ref",
        "معرّف المنتج",
        "Product ref",
        ("productref", "productid", "handle", "slug", "parentsku", "معرفالمنتج", "كودالمنتج"),
        required=True,
    ),
    FieldSpec("sku", "SKU", "SKU", ("sku", "itemcode", "code", "كود", "كودالصنف", "رمزالصنف")),
    FieldSpec(
        "barcode",
        "الباركود",
        "Barcode",
        ("barcode", "ean", "upc", "gtin", "ean13", "الباركود", "باركود"),
    ),
    FieldSpec("color", "اللون", "Color", ("color", "colour", "اللون", "لون")),
    FieldSpec("size", "المقاس", "Size", ("size", "المقاس", "مقاس", "الحجم")),
    FieldSpec(
        "price",
        "سعر البيع",
        "Price",
        ("price", "saleprice", "sellingprice", "retailprice", "سعرالبيع", "السعر", "سعر"),
        required=True,
    ),
    FieldSpec(
        "cost",
        "التكلفة",
        "Cost",
        ("cost", "costprice", "purchaseprice", "التكلفة", "سعرالشراء", "سعرالتكلفة"),
    ),
    # حد التنبيه كان في نموذج الإضافة اليدوي بس، فالتاجر اللي بيستورد 1000 صنف كان لازم يظبطه
    # واحد واحد من شاشة المخزون بعدين.
    FieldSpec(
        "reorder_level",
        "حد التنبيه",
        "Reorder level",
        (
            "reorderlevel",
            "reorder",
            "minstock",
            "minimumstock",
            "minlevel",
            "lowstock",
            "restocklevel",
            "حدالتنبيه",
            "الحدالأدنى",
            "حدإعادةالطلب",
            "أقلرصيد",
        ),
    ),
)

STOCK_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("sku", "SKU", "SKU", ("sku", "itemcode", "code", "كود", "كودالصنف"), required=True),
    FieldSpec("barcode", "الباركود", "Barcode", ("barcode", "ean", "الباركود", "باركود")),
    FieldSpec(
        "warehouse",
        "المخزن",
        "Warehouse",
        ("warehouse", "location", "store", "branch", "المخزن", "الفرع", "المستودع"),
    ),
    FieldSpec(
        "quantity",
        "الكمية",
        "Quantity",
        ("quantity", "qty", "stock", "onhand", "الكمية", "كمية", "الرصيد"),
        required=True,
    ),
)

IMAGE_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("sku", "SKU", "SKU", ("sku", "itemcode", "code", "كود"), required=True),
    FieldSpec(
        "file_name",
        "رابط الصورة",
        "Image link",
        (
            "image",
            "imagelink",
            "imageurl",
            "url",
            "link",
            "photo",
            "picture",
            "imagefile",
            "filename",
            "file",
            "الصورة",
            "رابطالصورة",
            "اسمالصورة",
            "صورة",
        ),
        required=True,
    ),
)

ITEM_CODE_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(
        "sku", "SKU", "SKU", ("sku", "itemcode", "كود", "كودالصنف", "رمزالصنف"), required=True
    ),
    FieldSpec(
        "code_type",
        "نوع الكود",
        "Code type",
        ("codetype", "type", "scheme", "itemtype", "نوعالكود", "النوع", "نوع"),
        required=True,
    ),
    FieldSpec(
        "code",
        "كود الصنف الضريبي",
        "Tax item code",
        (
            "code",
            "egs",
            "gs1",
            "egscode",
            "gs1code",
            "gtin",
            "taxcode",
            "etacode",
            "كودالصنفالضريبي",
            "كودالضريبة",
            "الكود",
            "كودمصلحةالضرائب",
        ),
        required=True,
    ),
)

SHEET_FIELDS: dict[str, tuple[FieldSpec, ...]] = {
    SHEET_PRODUCTS: PRODUCT_FIELDS,
    SHEET_VARIANTS: VARIANT_FIELDS,
    SHEET_STOCK: STOCK_FIELDS,
    SHEET_IMAGES: IMAGE_FIELDS,
    SHEET_ITEM_CODES: ITEM_CODE_FIELDS,
}
