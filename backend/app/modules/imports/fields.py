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

PRODUCT_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec(
        "product_ref",
        "معرّف المنتج",
        "Product ref",
        ("productref", "productid", "handle", "slug", "parentsku", "معرفالمنتج", "كودالمنتج"),
        required=True,
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
    FieldSpec("barcode", "الباركود", "Barcode", ("barcode", "ean", "الباركود", "باركود")),
    FieldSpec(
        "file_name",
        "اسم الصورة",
        "Image file",
        ("image", "imagefile", "filename", "file", "photo", "الصورة", "اسمالصورة"),
        required=True,
    ),
)

SHEET_FIELDS: dict[str, tuple[FieldSpec, ...]] = {
    SHEET_PRODUCTS: PRODUCT_FIELDS,
    SHEET_VARIANTS: VARIANT_FIELDS,
    SHEET_STOCK: STOCK_FIELDS,
    SHEET_IMAGES: IMAGE_FIELDS,
}
